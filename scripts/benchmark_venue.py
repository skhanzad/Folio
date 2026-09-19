"""Live venue-grounding integration check on the original synthetic manuscript.

Requires the running API and makes paid Jev requests. Website retrieval is
included in latency. This is not a test of scientific quality or acceptance.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.export import latex_report
from server.models import ReviewReport
from server.sample import sample_pdf
from server.venue import PRESETS


async def run(args):
    output = Path(__file__).resolve().parents[1] / "reports"
    study = {
        "measured_at": datetime.now(UTC).isoformat(),
        "description": "Two fresh venue-grounded uploads of an original synthetic manuscript. Integration only; no human quality labels.",
        "venue": {"name": args.venue_name, "website": args.website, "track": args.track},
        "trials": [],
    }
    pdf = sample_pdf()
    async with httpx.AsyncClient(timeout=180) as client:
        for trial in range(2):
            start = time.perf_counter()
            timings, report = [], None
            async with client.stream(
                "POST",
                args.base_url + "/api/review",
                files={"file": ("structured-synthetic.pdf", pdf, "application/pdf")},
                data={
                    "profile": "research",
                    "venue_name": args.venue_name,
                    "venue_website": args.website,
                    "venue_track": args.track,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    elapsed = round((time.perf_counter() - start) * 1000, 1)
                    timings.append({"type": event["type"], "elapsed_ms": elapsed})
                    if event["type"] == "error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "complete":
                        report = ReviewReport.model_validate(event["report"])
            if not report or not report.summary.complete or not report.venue:
                raise RuntimeError("No completed venue-grounded report received.")
            if any(len(result.dimensions) != 5 for result in report.results):
                raise RuntimeError("A venue-grounded criterion is missing.")
            measurement = {
                "review_id": report.review_id,
                "rubric_version": report.rubric_version,
                "paper_sha256": report.paper.sha256,
                "sections": len(report.results),
                "model": sorted({result.model for result in report.results}),
                "score": report.summary.score,
                "dimensions": report.summary.dimensions,
                "decision": report.summary.decision,
                "confidence": report.summary.confidence,
                "guidance_ready_ms": next(t["elapsed_ms"] for t in timings if t["type"] == "venue"),
                "first_section_ms": next(t["elapsed_ms"] for t in timings if t["type"] == "section_result"),
                "total_ms": timings[-1]["elapsed_ms"],
                "events": timings,
                "input_tokens": report.input_tokens,
                "output_tokens": report.output_tokens,
                "sources": [
                    {
                        "url": source.url,
                        "title": source.title,
                        "sha256": source.sha256,
                        "retrieved_at": source.retrieved_at,
                        "passage_count": len(source.passages),
                        "passage_bytes": sum(len(p.encode("utf-8")) for p in source.passages),
                    }
                    for source in report.venue.sources
                ],
            }
            study["trials"].append(measurement)
            if trial == 0:
                (output / "venue-example-review.tex").write_text(latex_report(report))
                if args.save_review:
                    Path(args.save_review).write_text(report.model_dump_json(indent=2))
            print(
                f"Trial {trial + 1}: score={measurement['score']}; venue fit={measurement['dimensions']['venue_fit']}; "
                f"first={measurement['first_section_ms']}ms; total={measurement['total_ms']}ms",
                flush=True,
            )
    assert study["trials"][0]["review_id"] != study["trials"][1]["review_id"]
    (output / "venue-validation.json").write_text(json.dumps(study, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--venue-name", default=PRESETS[0]["name"])
    parser.add_argument("--website", default=PRESETS[0]["website"])
    parser.add_argument("--track", default=PRESETS[0]["track"])
    parser.add_argument(
        "--save-review", help="Optional path for the complete report, including selected website passages."
    )
    asyncio.run(run(parser.parse_args()))
