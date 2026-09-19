import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .export import latex_report
from .jev import JevClient, JevError
from .models import ReviewReport, VenueRequest
from .pdf import PDFError, extract_pdf
from .rubric import PROFILES, RUBRIC_VERSION, rubric_metadata, summarize
from .sample import sample_pdf
from .venue import PRESETS, VenueError, load_venue

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
logger = logging.getLogger("folio")
app = FastAPI(title="Folio · Jev paper reviewer", version="1.0.0")
MAX_BYTES = 20 * 1024 * 1024
semaphore = asyncio.Semaphore(max(1, min(8, int(os.getenv("JEV_CONCURRENCY", "3")))))


def api_key():
    return os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY") or ""


@app.middleware("http")
async def limit_requests(request: Request, call_next):
    if request.method == "POST":
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return Response("Invalid content length", status_code=400)
        if size > MAX_BYTES + 1_048_576:
            return Response(
                json.dumps({"detail": "The upload is too large. Maximum PDF size is 20 MB."}),
                status_code=413,
                media_type="application/json",
            )
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "configured": bool(api_key()),
        "model": os.getenv("JEV_MODEL", "jev-1.13.0"),
        "rubric_version": RUBRIC_VERSION,
        "max_file_mb": 20,
    }


@app.get("/api/rubric")
def rubric():
    return rubric_metadata()


@app.get("/api/venues")
def venues():
    return {"presets": PRESETS}


@app.post("/api/venue")
async def preview_venue(venue: VenueRequest):
    try:
        return await load_venue(venue)
    except VenueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/sample.pdf")
def sample():
    return Response(
        sample_pdf(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="folio-example.pdf"'},
    )


@app.post("/api/export/latex")
def export(report: ReviewReport):
    valid_ids = {s.id for s in report.paper.sections}
    if any(r.section_id not in valid_ids for r in report.results):
        raise HTTPException(422, "The report contains an unknown section.")
    return Response(
        latex_report(report),
        media_type="application/x-tex",
        headers={"Content-Disposition": 'attachment; filename="folio-review.tex"'},
    )


@app.post("/api/review")
async def review(
    request: Request,
    file: Annotated[UploadFile, File()],
    profile: Annotated[str, Form()] = "research",
    venue_name: Annotated[str, Form(max_length=160)] = "",
    venue_website: Annotated[str, Form(max_length=2000)] = "",
    venue_track: Annotated[str, Form(max_length=160)] = "",
):
    if profile not in PROFILES:
        raise HTTPException(422, "Choose a valid review profile.")
    if not api_key():
        raise HTTPException(503, "Add JEV_API_KEY to the server .env file and restart to enable reviews.")
    venue_request = None
    if venue_name.strip() or venue_website.strip() or venue_track.strip():
        if len(venue_name.strip()) < 2 or len(venue_website.strip()) < 8:
            raise HTTPException(422, "Enter both a target venue name and its official website.")
        venue_request = VenueRequest(name=venue_name, website=venue_website, track=venue_track)
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The upload is too large. Maximum PDF size is 20 MB.")
    filename = Path((file.filename or "paper.pdf").replace("\\", "/")).name[:200]

    async def stream():
        start = time.perf_counter()
        review_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        tasks = []
        client = JevClient(api_key(), os.getenv("JEV_MODEL", "jev-1.13.0"), semaphore)
        queue: asyncio.Queue = asyncio.Queue()

        def event(kind, **payload):
            return (
                json.dumps(
                    {"type": kind, "review_id": review_id, **payload}, ensure_ascii=False, allow_nan=False
                )
                + "\n"
            )

        try:
            yield event("status", message="Reading the manuscript and identifying sections…")
            paper = await run_in_threadpool(extract_pdf, data, filename)
            venue = None
            if venue_request:
                yield event("status", message=f"Reading published guidance for {venue_request.name}…")
                venue = await load_venue(venue_request)
                client.venue = venue
                yield event("venue", venue=venue.model_dump())
            yield event(
                "paper",
                paper=paper.model_dump(),
                created_at=created_at,
                profile=profile,
                rubric_version=RUBRIC_VERSION,
                venue=venue.model_dump() if venue else None,
            )
            results = []
            section_gate = asyncio.Semaphore(3)

            async def worker(section):
                async with section_gate:
                    await queue.put(("section_start", {"section_id": section.id}))
                    try:
                        result = await client.review_section(paper, section, profile)
                        await queue.put(("result", result))
                    except JevError as exc:
                        await queue.put(("failure", str(exc)))
                    except Exception:
                        logger.exception("Unexpected section review failure")
                        await queue.put(
                            (
                                "failure",
                                "This section could not be reviewed. Re-upload to start a fresh review.",
                            )
                        )

            tasks = [asyncio.create_task(worker(section)) for section in paper.sections]
            while len(results) < len(paper.sections):
                if await request.is_disconnected():
                    return
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=12)
                except TimeoutError:
                    yield event("heartbeat", message="Jev is evaluating the manuscript…")
                    continue
                if kind == "failure":
                    yield event("error", message=payload)
                    return
                if kind == "result":
                    results.append(payload)
                    summary = summarize(paper, results, complete=False, venue=venue)
                    yield event("section_result", result=payload.model_dump(), summary=summary.model_dump())
                else:
                    yield event(kind, **payload)
            results.sort(
                key=lambda result: next(
                    i for i, section in enumerate(paper.sections) if section.id == result.section_id
                )
            )
            report = ReviewReport(
                review_id=review_id,
                created_at=created_at,
                paper=paper,
                results=results,
                summary=summarize(paper, results, complete=True, venue=venue),
                rubric_version=RUBRIC_VERSION,
                profile=profile,
                elapsed_ms=round((time.perf_counter() - start) * 1000),
                input_tokens=client.input_tokens,
                output_tokens=client.output_tokens,
                venue=venue,
            )
            yield event("complete", report=report.model_dump())
        except (PDFError, VenueError) as exc:
            yield event("error", message=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected review failure")
            yield event(
                "error", message="The review could not be completed. Please try another PDF or re-upload."
            )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await client.close()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


# Production serves the built React application on the same origin as the API.
if (ROOT / "dist").exists():
    app.mount("/assets", StaticFiles(directory=ROOT / "dist/assets"), name="assets")

    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(ROOT / "dist/favicon.svg")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "dist/index.html")
