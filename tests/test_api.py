import asyncio
import io
import json

import httpx
from fastapi import UploadFile

from server.app import app, review
from server.jev import JevError
from server.sample import sample_pdf
from tests.conftest import result_for


async def post_review(data=None, profile="research"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/review",
            files={"file": ("same-name.pdf", data or sample_pdf(), "application/pdf")},
            data={"profile": profile},
        )


async def test_stream_order_and_same_file_starts_fresh(mocked_jev):
    runs = []
    for _ in range(2):
        response = await post_review()
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["type"] == "status"
        assert events[1]["type"] == "paper"
        assert events[-1]["type"] == "complete"
        assert sum(e["type"] == "section_result" for e in events) == 8
        assert all(not e["summary"]["complete"] for e in events if e["type"] == "section_result")
        assert events[-1]["report"]["summary"]["complete"]
        assert events[-1]["report"]["summary"]["score"] == 75
        runs.append(events[-1]["review_id"])
    assert runs[0] != runs[1]


async def test_missing_key_is_actionable(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    response = await post_review()
    assert response.status_code == 503
    assert "JEV_API_KEY" in response.json()["detail"]


async def test_invalid_profile(mocked_jev):
    response = await post_review(profile="made-up")
    assert response.status_code == 422


async def test_invalid_pdf_streams_error_without_final(mocked_jev):
    response = await post_review(b"not a PDF")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "complete" for e in events)


async def test_oversize_upload_is_rejected(mocked_jev):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/review", content=b"x", headers={"content-length": str(23 * 1024 * 1024)}
        )
    assert response.status_code == 413


async def test_section_failure_never_yields_final_score(mocked_jev, monkeypatch):
    async def fail(self, paper, section, profile):
        if section.id == "s2":
            raise JevError("Fixture: upstream unavailable")
        return result_for(section)

    monkeypatch.setattr("server.jev.JevClient.review_section", fail)
    events = [json.loads(line) for line in (await post_review()).text.splitlines()]
    assert events[-1]["type"] == "error"
    assert "Fixture" in events[-1]["message"]
    assert not any(e["type"] == "complete" for e in events)


async def test_disconnect_cancels_pending_jev_tasks(mocked_jev, monkeypatch):
    cancelled = []

    async def delayed(self, paper, section, profile):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(section.id)
            raise

    class Request:
        async def is_disconnected(self):
            return False

    monkeypatch.setattr("server.jev.JevClient.review_section", delayed)
    response = await review(
        Request(), UploadFile(file=io.BytesIO(sample_pdf()), filename="test.pdf"), "research"
    )
    iterator = response.body_iterator
    assert json.loads(await anext(iterator))["type"] == "status"
    assert json.loads(await anext(iterator))["type"] == "paper"
    assert json.loads(await anext(iterator))["type"] == "section_start"
    await iterator.aclose()
    assert len(cancelled) == 3


async def test_health_never_exposes_credential(mocked_jev):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.json()["configured"]
    assert "test-key-never-sent" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_latex_export_escapes_manuscript_content(mocked_jev):
    response = await post_review()
    report = json.loads(response.text.splitlines()[-1])["report"]
    report["paper"]["title"] = r"Study & findings: 100% $x$ \input{malicious}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        export = await client.post("/api/export/latex", json=report)
    assert export.status_code == 200
    assert r"\input{malicious}" not in export.text
    assert r"\textbackslash{}input\{malicious\}" in export.text
    assert r"100\%" in export.text
    assert r"Study \& findings" in export.text
    assert r"\end{document}" in export.text
