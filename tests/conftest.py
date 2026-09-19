import pytest

from server.models import Dimension, SectionResult
from server.rubric import DIMENSIONS


def result_for(section, score=75, confidence=0.8):
    level = int(score / 25)
    return SectionResult(
        section_id=section.id,
        score=score,
        confidence=confidence,
        dimensions=[
            Dimension(
                key=key,
                label=d["label"],
                score=score,
                confidence=confidence,
                weight=d["weight"],
                probabilities={str(i): float(i == level) for i in range(5)},
                finding=d["criteria"][level],
                suggestion=d["suggestion"],
            )
            for key, d in DIMENSIONS.items()
        ],
        excerpt=section.text[:550],
        chunk_count=1,
        latency_ms=10,
        model="jev-test-fixture",
    )


@pytest.fixture
def mocked_jev(monkeypatch):
    from server.jev import JevClient

    monkeypatch.setenv("JEV_API_KEY", "test-key-never-sent")

    async def review(self, paper, section, profile):
        return result_for(section)

    monkeypatch.setattr(JevClient, "review_section", review)
