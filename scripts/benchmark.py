"""Small live integration study; this is not a peer-review accuracy benchmark.

Run the application first, then: uv run python scripts/benchmark.py --public
This intentionally makes paid Jev requests using the configured server credential.
Only original synthetic text is retained in exported full review artifacts.
"""

import argparse
import asyncio
import importlib.metadata
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.export import latex_report
from server.models import ReviewReport
from server.sample import sample_pdf


async def run(args):
    output = Path(__file__).resolve().parents[1] / "reports"
    output.mkdir(exist_ok=True)
    cases = [("structured_synthetic", sample_pdf()), ("vague_synthetic", sample_pdf(weak=True))]
    async with httpx.AsyncClient(timeout=180) as client:
        if args.public:
            response = await client.get("https://arxiv.org/pdf/1706.04599v2", follow_redirects=True)
            response.raise_for_status()
            cases.append(("guo_2017_calibration", response.content))
        study = {
            "measured_at": datetime.now(UTC).isoformat(),
            "description": "Live engineering and sensitivity checks. No human ground truth; no accuracy claim.",
            "python": platform.python_version(),
            "dependencies": {
                name: importlib.metadata.version(name) for name in ["pymupdf", "fastapi", "httpx"]
            },
            "public_source": "https://arxiv.org/abs/1706.04599v2" if args.public else None,
            "cases": [],
        }
        for name, data in cases:
            trials = []
            for trial in range(args.repeats):
                start = time.perf_counter()
                timings = []
                report = None
                async with client.stream(
                    "POST",
                    args.base_url + "/api/review",
                    files={"file": (name + ".pdf", data, "application/pdf")},
                    data={"profile": "research"},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        elapsed = round((time.perf_counter() - start) * 1000, 1)
                        if event["type"] in ("status", "paper", "section_result", "complete", "error"):
                            timings.append({"type": event["type"], "elapsed_ms": elapsed})
                        if event["type"] == "error":
                            raise RuntimeError(event["message"])
                        if event["type"] == "complete":
                            report = ReviewReport.model_validate(event["report"])
                if report is None:
                    raise RuntimeError("The review stream ended without completion.")
                if name == "structured_synthetic" and trial == 0:
                    (output / "example-review.json").write_text(report.model_dump_json(indent=2))
                    (output / "example-review.tex").write_text(latex_report(report))
                trial_data = {
                    "review_id": report.review_id,
                    "score": report.summary.score,
                    "confidence": report.summary.confidence,
                    "decision": report.summary.decision,
                    "first_section_ms": next(
                        t["elapsed_ms"] for t in timings if t["type"] == "section_result"
                    ),
                    "total_ms": timings[-1]["elapsed_ms"],
                    "server_elapsed_ms": report.elapsed_ms,
                    "events": timings,
                    "input_tokens": report.input_tokens,
                    "output_tokens": report.output_tokens,
                    "section_results": [
                        {
                            "title": s.title,
                            "role": s.role,
                            "pages": [s.page_start, s.page_end],
                            "score": r.score,
                            "confidence": r.confidence,
                            "chunks": r.chunk_count,
                            "dimensions": {d.key: d.score for d in r.dimensions},
                        }
                        for s, r in zip(report.paper.sections, report.results)
                    ],
                }
                trials.append(trial_data)
                print(
                    f"{name} trial {trial + 1}: score={trial_data['score']}, confidence={trial_data['confidence']}, first={trial_data['first_section_ms']}ms, total={trial_data['total_ms']}ms",
                    flush=True,
                )
            study["cases"].append(
                {
                    "name": name,
                    "title": report.paper.title,
                    "pages": report.paper.pages,
                    "words": report.paper.word_count,
                    "sections": len(report.paper.sections),
                    "sha256": report.paper.sha256,
                    "model": sorted({r.model for r in report.results}),
                    "rubric_version": report.rubric_version,
                    "warnings": report.paper.warnings,
                    "trials": trials,
                    "mean_score": statistics.mean(t["score"] for t in trials),
                    "score_stdev": statistics.stdev(t["score"] for t in trials) if len(trials) > 1 else 0,
                    "mean_first_section_ms": statistics.mean(t["first_section_ms"] for t in trials),
                    "mean_total_ms": statistics.mean(t["total_ms"] for t in trials),
                }
            )
            (output / "benchmark-results.json").write_text(json.dumps(study, indent=2))
    print(f"Recorded results in {output / 'benchmark-results.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--public", action="store_true")
    arguments = parser.parse_args()
    if not 1 <= arguments.repeats <= 10:
        parser.error("--repeats must be between 1 and 10")
    asyncio.run(run(arguments))
