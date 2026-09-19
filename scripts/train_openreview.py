"""Reproduce the ICLR 2026 pilot: download, score with Jev, train, and evaluate.

Uses a pinned public OpenReview PDF mirror when direct access is challenged.
Labels must agree with an independent Paper Copilot snapshot. Withdrawals,
conditional accepts, desk rejections, and disputes are never negative labels.
The held-out test split is not used for model selection or calibration.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pymupdf
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.jev import JevClient
from server.models import Paper, VenueContext, VenueRequest
from server.pdf import extract_pdf
from server.prediction import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    VENUE_ID,
    acceptance_features,
    guidance_fingerprint,
    prediction_label,
    text_fingerprint,
)
from server.rubric import RUBRIC_VERSION
from server.venue import load_venue

REVISION = "7a02654128d0ecb559ae5ef9b670dcaa564ad199"
MIRROR = "weathon/iclr_2026"
COPILOT_REVISION = "875df9d6550849ec07c9c6feba24986be2dd4551"
COPILOT_URL = (
    f"https://media.githubusercontent.com/media/papercopilot/paperlists/{COPILOT_REVISION}/iclr/iclr2026.json"
)
SEED = 20260919
MAX_PDF = 20 * 1024 * 1024
LIMITATIONS = [
    "Retrospective pilot: accepted PDFs can be camera-ready revisions. Removing explicit status text does not remove revision-content leakage; pre-decision forecasting is unvalidated.",
    "The cohort is a selected public PDF mirror, not a random sample of all ICLR submissions. Estimates describe this cohort and may not transfer to another venue or year.",
    "Only final accept/reject decisions are training labels. The six displayed outcomes are probability bands, not six observed ground-truth classes.",
    "The test set is small. Public papers may have appeared in Jev pretraining; base-model contamination cannot be ruled out.",
    "Jev evaluates extracted text. Figures, external novelty, mathematical correctness, and citation validity are not verified.",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def label_for(decision: str) -> int | None:
    if decision in ("Accept (Poster)", "Accept (Oral)", "Poster", "Oral"):
        return 1
    return 0 if decision == "Reject" else None


def eligible_records(
    notes: list[dict], corroboration: list[dict], pdfs: list[dict]
) -> tuple[list[dict], dict]:
    notes = {r["paper_id"]: r for r in notes}
    corroboration = {r["id"]: r for r in corroboration}
    rows, exclusions, seen_titles = [], Counter(), set()
    for pdf in sorted(pdfs, key=lambda p: p["path"]):
        forum = Path(pdf["path"]).stem
        a, b = notes.get(forum), corroboration.get(forum)
        if not a or not b:
            exclusions["missing_corroboration"] += 1
            continue
        label = label_for(a["decision"])
        if label is None or label_for(b["status"]) != label:
            exclusions["nonfinal_or_disputed_decision"] += 1
            continue
        if pdf["size"] > MAX_PDF:
            exclusions["pdf_over_20mb"] += 1
            continue
        title_key = re.sub(r"\W+", "", a["title"]).lower()
        if title_key in seen_titles:
            exclusions["duplicate_title"] += 1
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", forum):
            raise ValueError("Invalid OpenReview forum identifier.")
        seen_titles.add(title_key)
        rows.append(
            {
                "forum_id": forum,
                "title": a["title"],
                "label": label,
                "decision": a["decision"],
                "corroborated_status": b["status"],
                "forum_url": f"https://openreview.net/forum?id={forum}",
                "openreview_pdf": a["pdf_url"],
                "mirror_path": pdf["path"],
                "expected_sha256": pdf["lfs"]["oid"],
                "mirror_url": f"https://huggingface.co/datasets/{MIRROR}/resolve/{REVISION}/{pdf['path']}",
            }
        )
    return rows, dict(exclusions)


async def download(client: httpx.AsyncClient, url: str, path: Path, limit: int, expected: str | None = None):
    if path.exists() and (not expected or sha(path.read_bytes()) == expected):
        return
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            size = 0
            with temporary.open("wb") as output:
                async for block in response.aiter_bytes():
                    size += len(block)
                    if size > limit:
                        raise ValueError("Download exceeds its declared limit.")
                    output.write(block)
        if expected and sha(temporary.read_bytes()) != expected:
            raise ValueError("Downloaded file did not match the pinned SHA-256.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def prepare(args, root: Path):
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    (root / "pdfs").mkdir(exist_ok=True)
    (root / "papers").mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        await download(
            client,
            f"https://huggingface.co/datasets/{MIRROR}/resolve/{REVISION}/all_notes.json",
            source / "all_notes.json",
            250_000_000,
        )
        await download(client, COPILOT_URL, source / "papercopilot.json", 100_000_000)
        response = await client.get(
            f"https://huggingface.co/api/datasets/{MIRROR}/tree/{REVISION}/pdfs", params={"limit": 1000}
        )
        response.raise_for_status()
        if response.headers.get("link"):
            raise RuntimeError("PDF index is paginated; retrieve every page before sampling.")
        pdfs = response.json()
        (source / "pdf-index.json").write_text(json.dumps(pdfs, indent=2))
        candidates, exclusions = eligible_records(
            json.loads((source / "all_notes.json").read_text()),
            json.loads((source / "papercopilot.json").read_text()),
            pdfs,
        )
        if len(candidates) < args.limit:
            raise RuntimeError(
                f"Only {len(candidates)} eligible PDFs are available, below the requested {args.limit}."
            )
        # Sample before inspecting Jev outputs; preserve this available cohort's class proportion.
        indices, _ = train_test_split(
            np.arange(len(candidates)),
            train_size=args.limit,
            random_state=SEED,
            stratify=[r["label"] for r in candidates],
        )
        selected = [candidates[int(i)] for i in indices]
        records, failures, hashes = [], [], set()
        for i, row in enumerate(selected):
            path = root / "pdfs" / f"{row['forum_id']}.pdf"
            try:
                await download(client, row["mirror_url"], path, MAX_PDF, row["expected_sha256"])
                data = path.read_bytes()
                paper = extract_pdf(data, "manuscript.pdf")
                if len(
                    [
                        s
                        for s in paper.sections
                        if s.role
                        in ("abstract", "introduction", "methods", "results", "discussion", "conclusion")
                    ]
                ) < 3 or not any(s.role in ("methods", "results") for s in paper.sections):
                    raise ValueError("Scientific sections could not be identified for acceptance features.")
                digest = text_fingerprint(paper)
                if digest in hashes:
                    raise ValueError("Duplicate normalized manuscript text.")
                hashes.add(digest)
                with pymupdf.open(stream=data, filetype="pdf") as doc:
                    publication_marker = bool(
                        re.search(r"published as a conference paper", doc[0].get_text(), re.IGNORECASE)
                    )
                (root / "papers" / f"{row['forum_id']}.json").write_text(paper.model_dump_json())
                records.append(
                    {
                        **row,
                        "pdf_sha256": sha(data),
                        "text_sha256": digest,
                        "pages": paper.pages,
                        "sections": len(paper.sections),
                        "publication_marker_detected": publication_marker,
                    }
                )
            except (httpx.HTTPError, ValueError) as exc:
                failures.append({"forum_id": row["forum_id"], "reason": str(exc)})
            if (i + 1) % 10 == 0:
                print(f"Downloaded/inspected {i + 1}/{len(selected)}; usable={len(records)}", flush=True)
    if len(records) < 60:
        raise RuntimeError("Too few usable papers for a three-way pilot split.")
    dev, test = train_test_split(
        np.arange(len(records)), test_size=0.2, random_state=SEED, stratify=[r["label"] for r in records]
    )
    train, calibration = train_test_split(
        dev, test_size=0.25, random_state=SEED + 1, stratify=[records[int(i)]["label"] for i in dev]
    )
    for split, indices in (("train", train), ("calibration", calibration), ("test", test)):
        for index in indices:
            records[int(index)]["split"] = split
    venue = await load_venue(
        VenueRequest(
            name="ICLR 2026", website=f"https://openreview.net/group?id={VENUE_ID}", track="Main conference"
        )
    )
    (source / "venue.json").write_text(venue.model_dump_json(indent=2))
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "split_seed": SEED,
        "requested": args.limit,
        "eligible_cohort": len(candidates),
        "cohort": "Public mirrored ICLR 2026 PDFs with independently corroborated final decisions",
        "records": records,
        "pre_sampling_exclusions": exclusions,
        "download_or_parse_exclusions": failures,
        "sources": [
            {
                "url": f"https://huggingface.co/datasets/{MIRROR}/tree/{REVISION}",
                "revision": REVISION,
                "metadata_sha256": sha((source / "all_notes.json").read_bytes()),
            },
            {
                "url": COPILOT_URL,
                "revision": COPILOT_REVISION,
                "metadata_sha256": sha((source / "papercopilot.json").read_bytes()),
            },
        ],
        "limitations": LIMITATIONS,
        "access": "Direct OpenReview notes, invitations, and PDFs returned HTTP 403 challenges. PDFs were downloaded from a public mirror; no access challenge was bypassed.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Frozen {len(records)} papers: {dict(Counter(r['split'] for r in records))}", flush=True)


async def score(root: Path):
    load_dotenv(ROOT / ".env")
    key = os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("Set JEV_API_KEY before scoring the pilot.")
    manifest = json.loads((root / "manifest.json").read_text())
    venue = VenueContext.model_validate_json((root / "source/venue.json").read_text())
    output = root / "scores"
    output.mkdir(exist_ok=True)
    gate = asyncio.Semaphore(3)
    model = os.getenv("JEV_MODEL", "jev-1.13.0")
    started = time.perf_counter()
    for i, row in enumerate(manifest["records"]):
        path = output / f"{row['forum_id']}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            if (
                saved["pdf_sha256"] != row["pdf_sha256"]
                or saved["rubric_version"] != RUBRIC_VERSION
                or saved["guidance_fingerprint"] != guidance_fingerprint(venue)
                or saved["jev_model"] != model
            ):
                raise RuntimeError(
                    "Cached scores have incompatible input/model/guidance. Use a new study directory."
                )
            continue
        paper = Paper.model_validate_json((root / "papers" / f"{row['forum_id']}.json").read_text())
        client = JevClient(key, model, gate)
        client.venue = venue
        section_gate = asyncio.Semaphore(3)

        async def assess(section, section_gate=section_gate, client=client, paper=paper):
            async with section_gate:
                return await client.review_section(paper, section, "research")

        try:
            results = await asyncio.gather(*(assess(section) for section in paper.sections))
            if {result.model for result in results} != {model}:
                raise ValueError("Jev returned a different model version from the pinned study model.")
            features = acceptance_features(paper, results)
            path.write_text(
                json.dumps(
                    {
                        "forum_id": row["forum_id"],
                        "pdf_sha256": row["pdf_sha256"],
                        "rubric_version": RUBRIC_VERSION,
                        "feature_version": FEATURE_VERSION,
                        "jev_model": model,
                        "guidance_fingerprint": guidance_fingerprint(venue),
                        "features": features,
                        "results": [result.model_dump() for result in results],
                        "input_tokens": client.input_tokens,
                        "output_tokens": client.output_tokens,
                    }
                )
            )
        finally:
            await client.close()
        print(
            f"Jev {i + 1}/{len(manifest['records'])}: {len(results)} sections, {client.input_tokens} input tokens, elapsed {time.perf_counter() - started:.1f}s",
            flush=True,
        )


def measurements(y, p):
    return {
        "accuracy": float(accuracy_score(y, p >= 0.5)),
        "balanced_accuracy": float(balanced_accuracy_score(y, p >= 0.5)),
        "roc_auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "confusion_matrix": confusion_matrix(y, p >= 0.5, labels=[0, 1]).tolist(),
    }


def fit(root: Path):
    manifest = json.loads((root / "manifest.json").read_text())
    rows = manifest["records"]
    scores = [json.loads((root / "scores" / f"{r['forum_id']}.json").read_text()) for r in rows]
    for row, result in zip(rows, scores):
        if result["forum_id"] != row["forum_id"] or result["pdf_sha256"] != row["pdf_sha256"]:
            raise ValueError("A score does not match its frozen manuscript record.")
        if {section["model"] for section in result["results"]} != {result["jev_model"]}:
            raise ValueError("The returned Jev model differs from the recorded study version.")
    x, y = np.array([s["features"] for s in scores]), np.array([r["label"] for r in rows])
    split = {
        name: np.array([i for i, r in enumerate(rows) if r["split"] == name])
        for name in ("train", "calibration", "test")
    }
    if len({r["text_sha256"] for r in rows}) != len(rows):
        raise ValueError("Duplicate manuscripts across the study.")
    if not np.isfinite(x).all() or x.shape != (len(rows), len(FEATURE_NAMES)):
        raise ValueError("Invalid Jev feature matrix.")
    if sum(len(indices) for indices in split.values()) != len(rows):
        raise ValueError("Every manuscript must belong to exactly one frozen split.")
    for key in ("jev_model", "rubric_version", "feature_version", "guidance_fingerprint"):
        if len({s[key] for s in scores}) != 1:
            raise ValueError(f"Inconsistent {key} in scored papers.")
    pipeline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, random_state=SEED))
    search = GridSearchCV(
        pipeline,
        {"logisticregression__C": [0.01, 0.1, 1.0, 10.0]},
        scoring="neg_log_loss",
        cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
        n_jobs=1,
    )
    train, validation, test = split["train"], split["calibration"], split["test"]
    search.fit(x[train], y[train])
    best = search.best_estimator_
    calibration = LogisticRegression(C=1.0, max_iter=3000, random_state=SEED)
    calibration.fit(best.decision_function(x[validation]).reshape(-1, 1), y[validation])
    p = calibration.predict_proba(best.decision_function(x[test]).reshape(-1, 1))[:, 1]
    metrics = measurements(y[test], p)
    baseline = measurements(y[test], np.full(len(test), y[train].mean()))
    # Bootstrap the untouched test predictions; this does not tune or refit the selected model.
    rng = np.random.default_rng(SEED)
    intervals = {key: [] for key in ("accuracy", "roc_auc", "brier")}
    for _ in range(2000):
        indices = rng.integers(0, len(test), len(test))
        if len(np.unique(y[test][indices])) < 2:
            continue
        subset = measurements(y[test][indices], p[indices])
        for key, values in intervals.items():
            values.append(subset[key])
    metrics["bootstrap_95_ci"] = {
        key: [float(v) for v in np.quantile(values, [0.025, 0.975])] for key, values in intervals.items()
    }
    scaler, logistic = best.named_steps["standardscaler"], best.named_steps["logisticregression"]
    counts = {
        name: {
            "total": len(indices),
            "accepted": int(y[indices].sum()),
            "rejected": int(len(indices) - y[indices].sum()),
        }
        for name, indices in split.items()
    }
    model_id = (
        "iclr2026-jev-"
        + sha(
            json.dumps(
                {
                    "rows": [(r["forum_id"], r["split"]) for r in rows],
                    "features": x.tolist(),
                    "C": search.best_params_,
                }
            ).encode()
        )[:12]
    )
    artifact = {
        "model_id": model_id,
        "venue_id": VENUE_ID,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "rubric_version": scores[0]["rubric_version"],
        "jev_model": scores[0]["jev_model"],
        "guidance_fingerprint": scores[0]["guidance_fingerprint"],
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": logistic.coef_[0].tolist(),
        "intercept": float(logistic.intercept_[0]),
        "calibration": {
            "slope": float(calibration.coef_[0, 0]),
            "intercept": float(calibration.intercept_[0]),
        },
        "selected_C": search.best_params_["logisticregression__C"],
        "training_cv_log_loss": -float(search.best_score_),
        "counts": counts,
        "metrics": metrics,
        "baseline": baseline,
        "split_seed": SEED,
        "limitations": LIMITATIONS,
        "sources": manifest["sources"],
        "cohort": manifest["cohort"],
        "input_tokens": sum(s["input_tokens"] for s in scores),
        "output_tokens": sum(s["output_tokens"] for s in scores),
        "papers": [
            {k: r[k] for k in ("forum_id", "split", "decision", "pdf_sha256", "text_sha256")} for r in rows
        ],
    }
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "iclr2026-model.json").write_text(json.dumps(artifact, indent=2) + "\n")
    (ROOT / "reports/iclr2026-features.json").write_text(
        json.dumps(
            {
                "model_id": model_id,
                "feature_names": FEATURE_NAMES,
                "feature_version": FEATURE_VERSION,
                "rubric_version": scores[0]["rubric_version"],
                "jev_model": scores[0]["jev_model"],
                "guidance_fingerprint": scores[0]["guidance_fingerprint"],
                "records": [
                    {
                        "forum_id": row["forum_id"],
                        "split": row["split"],
                        "label": row["label"],
                        "features": score["features"],
                    }
                    for row, score in zip(rows, scores)
                ],
            },
            indent=2,
        )
        + "\n"
    )
    public_rows = [
        {
            k: r[k]
            for k in (
                "forum_id",
                "title",
                "decision",
                "label",
                "split",
                "forum_url",
                "mirror_url",
                "pdf_sha256",
                "text_sha256",
                "publication_marker_detected",
                "pages",
                "sections",
            )
        }
        for r in rows
    ]
    for index, probability in zip(test, p):
        public_rows[int(index)].update(
            acceptance_probability=float(probability), prediction=prediction_label(float(probability))
        )
    results = {
        **{
            k: artifact[k]
            for k in (
                "model_id",
                "trained_at",
                "counts",
                "metrics",
                "baseline",
                "sources",
                "cohort",
                "limitations",
                "selected_C",
                "training_cv_log_loss",
                "input_tokens",
                "output_tokens",
            )
        },
        "sampling": {
            k: manifest[k]
            for k in (
                "requested",
                "eligible_cohort",
                "pre_sampling_exclusions",
                "download_or_parse_exclusions",
                "access",
            )
        },
        "papers": public_rows,
        "jev_sections": sum(len(score["results"]) for score in scores),
        "jev_requests": sum(section["chunk_count"] for score in scores for section in score["results"]),
    }
    (ROOT / "reports/iclr2026-study.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        json.dumps(
            {"counts": counts, "metrics": metrics, "baseline": baseline, "model_id": model_id}, indent=2
        ),
        flush=True,
    )


async def main(args):
    root = Path(args.data_dir)
    if args.stage in ("prepare", "all"):
        await prepare(args, root)
    if args.stage in ("score", "all"):
        await score(root)
    if args.stage in ("fit", "all"):
        fit(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "score", "fit", "all"), default="all")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--data-dir", default=str(ROOT / "data/openreview/iclr2026"))
    args = parser.parse_args()
    if not 60 <= args.limit <= 200:
        parser.error("The authorized pilot supports 60–200 labeled papers.")
    asyncio.run(main(args))
