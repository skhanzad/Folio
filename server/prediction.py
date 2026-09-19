"""Inference for a supervised acceptance model trained on Jev outputs.

Only numeric Jev judgments enter the classifier. Decisions, reviewer scores,
authors, paper IDs, filenames, and venue-status metadata are never features.
Model artifacts are inspectable JSON, not executable pickle files.
"""

import hashlib
import json
import math
import os
import re
from pathlib import Path

from .models import Paper, SectionResult, VenueContext

VENUE_ID = "ICLR.cc/2026/Conference"
FEATURE_VERSION = "jev-scientific-moments-1"
CRITERIA = ("clarity", "rigor", "support", "completeness", "venue_fit")
FEATURE_NAMES = [f"{key}_{stat}" for stat in ("mean", "spread") for key in CRITERIA]
SCIENTIFIC_ROLES = {
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "results",
    "discussion",
    "conclusion",
}
BANDS = [
    {"minimum": 0.0, "maximum": 0.15, "label": "Strong reject"},
    {"minimum": 0.15, "maximum": 0.30, "label": "Reject"},
    {"minimum": 0.30, "maximum": 0.50, "label": "Weak reject"},
    {"minimum": 0.50, "maximum": 0.70, "label": "Weak accept"},
    {"minimum": 0.70, "maximum": 0.85, "label": "Accept"},
    {"minimum": 0.85, "maximum": 1.0, "label": "Strong accept"},
]
STATUS_LINE = re.compile(
    r"^.*(?:published as (?:a )?(?:conference|workshop) paper|under review as (?:a )?(?:conference|workshop) paper|"
    r"paper under (?:double[- ]blind|review)|anonymous authors|camera[- ]ready version).*$",
    re.IGNORECASE | re.MULTILINE,
)
METADATA_SECTION = re.compile(r"acknowledg|author contributions?|funding|competing interests?", re.IGNORECASE)


def clean_scoring_text(text: str) -> str:
    return STATUS_LINE.sub("", text)


def text_fingerprint(paper: Paper) -> str:
    text = " ".join(clean_scoring_text(s.text) for s in paper.sections if s.role in SCIENTIFIC_ROLES)
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()


def guidance_fingerprint(venue: VenueContext) -> str:
    payload = [{"url": source.url, "passages": source.passages} for source in venue.sources]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def acceptance_features(paper: Paper, results: list[SectionResult]) -> list[float]:
    by_id = {r.section_id: r for r in results}
    if len(by_id) != len(paper.sections) or any(s.id not in by_id for s in paper.sections):
        raise ValueError("Acceptance prediction requires every section result.")
    sections = [
        s for s in paper.sections if s.role in SCIENTIFIC_ROLES and not METADATA_SECTION.search(s.title)
    ]
    if len(sections) < 3 or not any(s.role in ("methods", "results") for s in sections):
        raise ValueError(
            "At least three scientific sections, including methods or results, are needed for this model."
        )
    # Equal role mass, then word weighting within a role, avoids overweighting subdivided roles.
    role_words = {
        role: sum(max(1, s.word_count) for s in sections if s.role == role)
        for role in {s.role for s in sections}
    }
    weights = [max(1, s.word_count) / role_words[s.role] / len(role_words) for s in sections]
    values = []
    for section in sections:
        dimensions = {d.key: d.score / 100 for d in by_id[section.id].dimensions}
        if any(key not in dimensions or not math.isfinite(dimensions[key]) for key in CRITERIA):
            raise ValueError("A required Jev criterion is missing or invalid.")
        values.append([dimensions[key] for key in CRITERIA])
    means = [sum(w * row[i] for w, row in zip(weights, values)) for i in range(len(CRITERIA))]
    spreads = [
        math.sqrt(sum(w * (row[i] - means[i]) ** 2 for w, row in zip(weights, values)))
        for i in range(len(CRITERIA))
    ]
    return means + spreads


def prediction_label(probability: float) -> str:
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Probability must be finite and between zero and one.")
    return next(band["label"] for band in BANDS if probability < band["maximum"] or band["maximum"] == 1)


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(-700, min(700, value))))


def model_path() -> Path:
    return Path(
        os.getenv(
            "FOLIO_ACCEPTANCE_MODEL",
            str(Path(__file__).resolve().parents[1] / "artifacts/iclr2026-model.json"),
        )
    )


def load_model() -> dict | None:
    path = model_path()
    if not path.exists():
        return None
    artifact = json.loads(path.read_text())
    if artifact["feature_version"] != FEATURE_VERSION or artifact["feature_names"] != FEATURE_NAMES:
        raise ValueError("The acceptance model uses incompatible features.")
    if artifact["venue_id"] != VENUE_ID:
        raise ValueError("The acceptance model belongs to a different venue.")
    for key in ("mean", "scale", "coefficients"):
        if len(artifact[key]) != len(FEATURE_NAMES) or not all(math.isfinite(v) for v in artifact[key]):
            raise ValueError("Invalid acceptance model coefficients.")
    if any(v <= 0 for v in artifact["scale"]):
        raise ValueError("Invalid acceptance model scaling.")
    if not all(
        math.isfinite(v)
        for v in (
            artifact["intercept"],
            artifact["calibration"]["slope"],
            artifact["calibration"]["intercept"],
        )
    ):
        raise ValueError("Invalid acceptance model calibration.")
    return artifact


def model_summary() -> dict:
    try:
        artifact = load_model()
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "status": "unavailable",
            "reason": "The trained acceptance model could not be loaded.",
            "bands": BANDS,
        }
    if artifact is None:
        return {
            "status": "unavailable",
            "reason": "The ICLR 2026 pilot has not been trained yet.",
            "bands": BANDS,
        }
    keys = (
        "model_id",
        "venue_id",
        "trained_at",
        "counts",
        "metrics",
        "baseline",
        "limitations",
        "sources",
        "split_seed",
        "cohort",
    )
    return {"status": "ready", "bands": BANDS, **{key: artifact[key] for key in keys}}


def predict_acceptance(
    paper: Paper, results: list[SectionResult], venue: VenueContext | None, profile: str, rubric_version: str
) -> dict:
    def unavailable(reason):
        return {"status": "unavailable", "reason": reason, "bands": BANDS}

    if not venue or venue.openreview_id != VENUE_ID:
        return unavailable(
            "Acceptance training is available for the ICLR 2026 OpenReview venue. Other venues need their own labeled study."
        )
    if profile != "research":
        return unavailable("The ICLR 2026 acceptance model was trained with the research-paper profile.")
    try:
        artifact = load_model()
        if artifact is None:
            return unavailable("The ICLR 2026 pilot has not been trained yet.")
        if artifact["rubric_version"] != rubric_version or artifact[
            "guidance_fingerprint"
        ] != guidance_fingerprint(venue):
            return unavailable(
                "The rubric or venue guidance changed since training. Retrain before producing an acceptance estimate."
            )
        if {r.model for r in results} != {artifact["jev_model"]}:
            return unavailable("This review used a different Jev model than the acceptance training run.")
        features = acceptance_features(paper, results)
        linear = artifact["intercept"] + sum(
            (x - mean) / scale * coef
            for x, mean, scale, coef in zip(
                features, artifact["mean"], artifact["scale"], artifact["coefficients"]
            )
        )
        probability = sigmoid(
            artifact["calibration"]["slope"] * linear + artifact["calibration"]["intercept"]
        )
        fingerprint = text_fingerprint(paper)
        matched = next(
            (
                row
                for row in artifact["papers"]
                if row["pdf_sha256"] == paper.sha256 or row["text_sha256"] == fingerprint
            ),
            None,
        )
        return {
            "status": "ready",
            "model_id": artifact["model_id"],
            "venue_id": artifact["venue_id"],
            "acceptance_probability": probability,
            "label": prediction_label(probability),
            "binary_prediction": "Accept" if probability >= 0.5 else "Reject",
            "bands": BANDS,
            "counts": artifact["counts"],
            "metrics": artifact["metrics"],
            "baseline": artifact["baseline"],
            "limitations": artifact["limitations"],
            "known_paper": {k: matched[k] for k in ("forum_id", "split", "decision")} if matched else None,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return unavailable(f"Acceptance estimate unavailable: {exc}")
