import asyncio
import copy
import json
from unittest.mock import AsyncMock

import httpx
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from server.app import app
from server.jev import JevClient
from server.models import Dimension
from server.prediction import (
    BANDS,
    FEATURE_NAMES,
    FEATURE_VERSION,
    VENUE_ID,
    acceptance_features,
    clean_scoring_text,
    guidance_fingerprint,
    load_model,
    predict_acceptance,
    prediction_label,
    text_fingerprint,
)
from server.rubric import RUBRIC_VERSION
from server.sample import sample_pdf
from tests.conftest import result_for
from tests.test_scoring import paper_with, response_body
from tests.test_venue import venue_context


def scored(section, score=75):
    result = result_for(section, score)
    result.dimensions.append(
        Dimension(
            key="venue_fit",
            label="Venue fit",
            score=score,
            confidence=0.8,
            weight=0.2,
            probabilities={str(i): float(i == int(score / 25)) for i in range(5)},
            finding="Fixture",
            suggestion="Fixture",
        )
    )
    return result


@pytest.fixture
def trained_fixture(tmp_path, monkeypatch):
    """Fit an independent sklearn reference, then exercise our JSON-only runtime."""
    rng = np.random.default_rng(47)
    x = rng.uniform(0, 1, (60, len(FEATURE_NAMES)))
    y = (x[:, 0] + x[:, 1] > 1).astype(int)
    scaler = StandardScaler().fit(x[:40])
    classifier = LogisticRegression().fit(scaler.transform(x[:40]), y[:40])
    calibrator = LogisticRegression().fit(
        classifier.decision_function(scaler.transform(x[40:])).reshape(-1, 1), y[40:]
    )
    venue = venue_context()
    venue.openreview_id = VENUE_ID
    artifact = {
        "model_id": "test-only-model",
        "venue_id": VENUE_ID,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "rubric_version": RUBRIC_VERSION,
        "jev_model": "jev-test-fixture",
        "guidance_fingerprint": guidance_fingerprint(venue),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "calibration": {"slope": float(calibrator.coef_[0, 0]), "intercept": float(calibrator.intercept_[0])},
        "papers": [],
        "counts": {},
        "metrics": {},
        "baseline": {},
        "limitations": [],
    }
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact))
    monkeypatch.setenv("FOLIO_ACCEPTANCE_MODEL", str(path))
    return venue, artifact, path, scaler, classifier, calibrator


@pytest.mark.parametrize(
    "probability, expected",
    [
        (0, "Strong reject"),
        (0.14999, "Strong reject"),
        (0.15, "Reject"),
        (0.30, "Weak reject"),
        (0.49999, "Weak reject"),
        (0.50, "Weak accept"),
        (0.70, "Accept"),
        (0.85, "Strong accept"),
        (1, "Strong accept"),
    ],
)
def test_six_probability_bands(probability, expected):
    assert prediction_label(probability) == expected
    assert len(BANDS) == 6


@pytest.mark.parametrize("probability", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_probability_is_not_a_decision(probability):
    with pytest.raises(ValueError):
        prediction_label(probability)


def test_features_exclude_reference_metadata_and_section_confidence():
    paper = paper_with("abstract", "methods", "results", "references", "discussion")
    paper.sections[-1].title = "Acknowledgements"
    results = [scored(section) for section in paper.sections]
    expected = acceptance_features(paper, results)
    for result in results[-2:]:
        for dimension in result.dimensions:
            dimension.score = 0
    for result in results:
        result.confidence = 0.01
    paper.title, paper.filename, paper.sha256 = "Accepted", "reject.pdf", "a" * 64
    assert acceptance_features(paper, results) == expected
    assert expected[:5] == pytest.approx([0.75] * 5)
    assert expected[5:] == pytest.approx([0] * 5)


def test_splitting_one_scientific_role_preserves_its_feature_weight():
    original = paper_with("abstract", "methods", "results")
    divided = paper_with("abstract", "methods", "methods", "results")
    assert acceptance_features(
        original, [scored(s, n) for s, n in zip(original.sections, [50, 75, 100])]
    ) == pytest.approx(
        acceptance_features(divided, [scored(s, n) for s, n in zip(divided.sections, [50, 75, 75, 100])])
    )


def test_partial_reviews_and_missing_criteria_cannot_be_classified():
    paper = paper_with("abstract", "methods", "results")
    with pytest.raises(ValueError, match="every section"):
        acceptance_features(paper, [scored(paper.sections[0])])
    with pytest.raises(ValueError, match="criterion"):
        acceptance_features(paper, [result_for(s) for s in paper.sections])


def test_runtime_matches_sklearn_and_labels_never_change_probability(trained_fixture):
    venue, artifact, path, scaler, classifier, calibrator = trained_fixture
    paper = paper_with("abstract", "methods", "results")
    results = [scored(s, n) for s, n in zip(paper.sections, [50, 75, 100])]
    expected = calibrator.predict_proba(
        classifier.decision_function(scaler.transform([acceptance_features(paper, results)])).reshape(-1, 1)
    )[0, 1]
    prediction = predict_acceptance(paper, results, venue, "research", RUBRIC_VERSION)
    assert prediction["acceptance_probability"] == pytest.approx(expected)
    artifact["papers"] = [
        {
            "forum_id": "known",
            "split": "train",
            "decision": "Reject",
            "pdf_sha256": paper.sha256,
            "text_sha256": text_fingerprint(paper),
        }
    ]
    path.write_text(json.dumps(artifact))
    known = predict_acceptance(paper, results, venue, "research", RUBRIC_VERSION)
    assert known["known_paper"]["split"] == "train"
    assert known["acceptance_probability"] == expected
    artifact["papers"][0]["decision"] = "Accept (Oral)"
    path.write_text(json.dumps(artifact))
    assert (
        predict_acceptance(paper, results, venue, "research", RUBRIC_VERSION)["acceptance_probability"]
        == expected
    )


@pytest.mark.parametrize("mismatch", ["venue", "profile", "guidance", "rubric", "model", "partial"])
def test_distribution_mismatch_is_unavailable(trained_fixture, mismatch):
    venue = trained_fixture[0]
    paper = paper_with("abstract", "methods", "results")
    results, profile, rubric = [scored(s) for s in paper.sections], "research", RUBRIC_VERSION
    if mismatch == "venue":
        venue.openreview_id = "NeurIPS.cc/2026/Conference"
    elif mismatch == "profile":
        profile = "survey"
    elif mismatch == "guidance":
        venue.sources[0].passages.append("Changed criteria")
    elif mismatch == "rubric":
        rubric = "new-rubric"
    elif mismatch == "model":
        results[0].model = "different-jev"
    else:
        results.pop()
    prediction = predict_acceptance(paper, results, venue, profile, rubric)
    assert prediction["status"] == "unavailable"
    assert "acceptance_probability" not in prediction


def test_artifact_rejects_nonfinite_calibration(trained_fixture):
    _, artifact, path, *_ = trained_fixture
    artifact["calibration"]["slope"] = float("nan")
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="calibration"):
        load_model()


async def test_jev_input_withholds_title_and_explicit_publication_status():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        body = copy.deepcopy(response_body())
        body["answers"]["venue_fit"] = body["answers"]["clarity"]
        return httpx.Response(200, json=body)

    paper = paper_with("abstract", "methods", "results")
    paper.title = "A memorized title with an observed outcome"
    paper.sections[1].text = "Published as a conference paper at ICLR 2026\nA scientific claim."
    venue = venue_context()
    venue.openreview_id = VENUE_ID
    client = JevClient("test-only", "jev-1.13.0", asyncio.Semaphore(1), httpx.MockTransport(handler))
    client.venue = venue
    try:
        await client.review_section(paper, paper.sections[1], "research")
    finally:
        await client.close()
    payload = json.dumps(seen)
    assert paper.title not in payload
    assert "Published as a conference paper" not in payload
    assert "A scientific claim." in payload
    assert clean_scoring_text("A supported claim. ") == "A supported claim. "


async def test_stream_emits_prediction_only_on_completion_and_exports_it(trained_fixture, monkeypatch):
    venue = trained_fixture[0]
    monkeypatch.setenv("JEV_API_KEY", "fixture-only")
    monkeypatch.setattr("server.app.load_venue", AsyncMock(return_value=venue))

    async def review(self, paper, section, profile):
        return scored(section)

    monkeypatch.setattr(JevClient, "review_section", review)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/review",
            files={"file": ("paper.pdf", sample_pdf(), "application/pdf")},
            data={"venue_name": "ICLR 2026", "venue_website": "https://openreview.net/group?id=" + VENUE_ID},
        )
        events = [json.loads(line) for line in response.text.splitlines()]
        assert all("prediction" not in event for event in events[:-1])
        report = events[-1]["report"]
        assert report["prediction"]["status"] == "ready"
        export = await client.post("/api/export/latex", json=report)
        assert export.status_code == 200
        assert "Acceptance prediction" in export.text
        assert "test-only-model" in export.text
        assert "probability bands" in export.text
