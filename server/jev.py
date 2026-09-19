import asyncio
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from .models import Dimension, Paper, Section, SectionResult, VenueContext
from .pdf import chunks
from .rubric import DIMENSIONS, dimensions_for, questions

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevError(RuntimeError):
    pass


def validate_answers(payload: dict, dimensions: dict | None = None) -> dict:
    try:
        answers = payload["answers"]
        for key in dimensions or DIMENSIONS:
            answer = answers[key]
            score, confidence = float(answer["score"]), float(answer["confidence"])
            probabilities = answer["probabilities"]
            if answer["type"] != "score" or not math.isfinite(score) or not 0 <= score <= 4:
                raise ValueError("Invalid score")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid confidence")
            if set(probabilities) != {"0", "1", "2", "3", "4"}:
                raise ValueError("Missing probability levels")
            values = [float(probabilities[str(i)]) for i in range(5)]
            if any(not math.isfinite(p) or p < 0 or p > 1 for p in values) or abs(sum(values) - 1) > 0.025:
                raise ValueError("Invalid distribution")
            if abs(sum(i * p for i, p in enumerate(values)) - score) > 0.08:
                raise ValueError("Score does not match distribution")
        return answers
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise JevError("Jev returned an incomplete or invalid scoring response. Re-upload to retry.") from exc


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return min(30, max(0, float(value)))
        except ValueError:
            try:
                return min(30, max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()))
            except (ValueError, TypeError):
                pass
    return 1.5 * 2**attempt


class JevClient:
    def __init__(self, key: str, model: str, semaphore: asyncio.Semaphore, transport=None):
        self.key = key
        self.model = model
        self.semaphore = semaphore
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(65, connect=12), transport=transport)
        self.input_tokens = 0
        self.output_tokens = 0
        self.venue: VenueContext | None = None

    async def close(self):
        await self.http.aclose()

    async def evaluate(self, state: dict, role: str, profile: str) -> tuple[dict, str]:
        grounded = self.venue is not None
        payload = {"state": state, "model": self.model, "questions": questions(role, profile, grounded)}
        for attempt in range(3):
            try:
                async with self.semaphore:
                    response = await self.http.post(
                        ENDPOINT, json=payload, headers={"Authorization": f"Bearer {self.key}"}
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < 2:
                    await asyncio.sleep(retry_delay(None, attempt))
                    continue
                raise JevError(
                    "Jev could not be reached in time. Check your connection and re-upload to retry."
                ) from exc
            if response.status_code in (401, 403):
                raise JevError(
                    "Jev rejected the server API key. Check JEV_API_KEY in .env and restart the server."
                )
            if response.status_code in (429, 500, 502, 503, 504, 529) and attempt < 2:
                await asyncio.sleep(retry_delay(response.headers.get("retry-after"), attempt))
                continue
            if not response.is_success:
                raise JevError(
                    f"Jev could not complete this review (HTTP {response.status_code}). Re-upload to retry."
                )
            try:
                body = response.json()
                answers = validate_answers(body, dimensions_for(grounded))
            except (ValueError, TypeError) as exc:
                raise JevError("Jev returned an unreadable response. Re-upload to retry.") from exc
            self.input_tokens += int(body.get("usage", {}).get("input_tokens", 0))
            self.output_tokens += int(body.get("usage", {}).get("output_tokens", 0))
            return answers, body.get("model", self.model)
        raise JevError("Jev is busy. Please try again shortly.")

    async def review_section(self, paper: Paper, section: Section, profile: str) -> SectionResult:
        started = time.perf_counter()
        passages = chunks(section.text)
        abstract = next((s.text for s in paper.sections if s.role == "abstract"), "")
        # The context is deliberately bounded; the complete target text is always reviewed.
        context = {
            "title": paper.title,
            "abstract_excerpt": abstract[:1800],
            "section_headings": [s.title for s in paper.sections],
        }
        answers = []
        models = []
        venue_state = (
            {
                "venue_context": {
                    "name": self.venue.name,
                    "track": self.venue.track,
                    "sources": [
                        {"url": source.url, "title": source.title, "passages": source.passages}
                        for source in self.venue.sources
                    ],
                }
            }
            if self.venue
            else {}
        )
        for index, passage in enumerate(passages):
            result, model = await self.evaluate(
                {
                    "paper_context": context,
                    "section_heading": section.title,
                    "passage": f"{index + 1} of {len(passages)}; assess this passage only",
                    "target_passage": passage,
                    **venue_state,
                },
                section.role,
                profile,
            )
            answers.append((len(passage), result))
            models.append(model)
        total = sum(length for length, _ in answers)
        dimensions = []
        for key, dim in dimensions_for(self.venue is not None).items():
            score = sum(length * float(answer[key]["score"]) / 4 * 100 for length, answer in answers) / total
            confidence = sum(length * float(answer[key]["confidence"]) for length, answer in answers) / total
            probabilities = {
                str(i): sum(
                    length * float(answer[key]["probabilities"][str(i)]) for length, answer in answers
                )
                / total
                for i in range(5)
            }
            level = max(0, min(4, int(score / 25 + 0.5)))
            dimensions.append(
                Dimension(
                    key=key,
                    label=dim["label"],
                    score=round(score, 2),
                    confidence=round(confidence, 4),
                    weight=dim["weight"],
                    probabilities=probabilities,
                    finding=dim["criteria"][level],
                    suggestion=dim["suggestion"],
                )
            )
        return SectionResult(
            section_id=section.id,
            score=round(sum(d.score * d.weight for d in dimensions), 2),
            confidence=round(sum(d.confidence * d.weight for d in dimensions), 4),
            dimensions=dimensions,
            excerpt=section.text[:550],
            chunk_count=len(passages),
            latency_ms=round((time.perf_counter() - started) * 1000),
            model=", ".join(sorted(set(models))),
        )
