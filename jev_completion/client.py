"""Authenticated Jev requests with a persistent, conservative spending ledger."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import dotenv_values

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"
INPUT_USD_PER_MILLION = 0.042  # Published direct-API price, checked 2026-09-19.
MAX_REQUEST_TOKENS = 64_000


class BudgetExceeded(RuntimeError):
    pass


class JevError(RuntimeError):
    pass


def api_key(env_file: Path = Path(".env")) -> str:
    """Read keys without shell evaluation, interpolation, printing, or logging."""
    values = dict(dotenv_values(env_file, interpolate=False)) if env_file.exists() else {}
    values.update(os.environ)
    for name in ("JEV_APIKEY", "JEV-APIKEY", "JEV_API_KEY", "TYPESAFE_API_KEY"):
        if values.get(name):
            return str(values[name])
    raise JevError("Set JEV_APIKEY in .env or the environment.")


def canonical(value: Any) -> str:
    # Preserve option order: classifiers can be sensitive to presentation order.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def validate_questions(questions: dict) -> None:
    if not questions:
        raise ValueError("At least one question is required.")
    for question in questions.values():
        kind = question.get("type")
        if kind not in {"choice", "noul", "score"} or not question.get("instructions"):
            raise ValueError("Each question requires a supported type and instructions.")
        criteria = question.get("criteria")
        if kind == "choice" and (not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255):
            raise ValueError("Choice requires 2–255 distinct options.")
        if kind == "score" and (not isinstance(criteria, list) or not 2 <= len(criteria) <= 10):
            raise ValueError("Score requires 2–10 levels.")


def probability(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def validate_response(data: dict, questions: dict) -> None:
    usage = data.get("usage", {})
    for key in ("input_tokens", "output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise JevError("API returned missing or invalid token usage; reservation retained.")
    if usage["input_tokens"] > MAX_REQUEST_TOKENS:
        raise JevError("API input usage exceeded the documented limit; reservation retained.")
    answers = data.get("answers", {})
    if not isinstance(data.get("model"), str):
        raise JevError("API response does not identify its model.")
    for name, question in questions.items():
        answer = answers.get(name, {})
        kind = question["type"]
        if answer.get("type") != kind:
            raise JevError("API returned a missing or mismatched answer type.")
        if kind == "noul":
            if not probability(answer.get("noul")):
                raise JevError("Invalid Noul probability.")
        elif kind == "choice":
            probs = answer.get("probabilities", {})
            if set(probs) != set(question["criteria"]) or not all(probability(p) for p in probs.values()):
                raise JevError("Choice probabilities do not match the requested candidates.")
            if abs(sum(probs.values()) - 1) > 0.025:
                raise JevError("Choice probabilities are not normalized.")
            if answer.get("choice") not in probs or not probability(answer.get("confidence")):
                raise JevError("Invalid selected option or confidence.")
        elif not isinstance(answer.get("score"), (int, float)) or not math.isfinite(answer["score"]):
            raise JevError("Invalid Score result.")


class Ledger:
    """Reserve an entire 64k request before sending; reconcile only known usage.

    The cap applies across processes using this database. Uncertain failures retain
    their full reservation; there are deliberately no automatic paid retries.
    Monetary amounts use integer nanodollars to avoid floating-point budget drift.
    This is a bound under the documented rate/context limit, not a billing invoice.
    """

    def __init__(self, path: Path, cap_usd: float, rate: float = INPUT_USD_PER_MILLION):
        if not math.isfinite(cap_usd) or not math.isfinite(rate) or cap_usd <= 0 or rate <= 0:
            raise ValueError("Budget and input price must be positive finite numbers.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL, reserved_nusd INTEGER NOT NULL, cost_nusd INTEGER,
            input_tokens INTEGER, output_tokens INTEGER, latency_s REAL, model TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS cache (
            request_hash TEXT PRIMARY KEY, response TEXT NOT NULL)""")
        self.cap_nusd = int(cap_usd * 1_000_000_000)
        self.rate = rate

    def cost(self, tokens: int) -> int:
        return math.ceil(tokens * self.rate * 1000)

    def reserve(self, request_hash: str) -> int:
        amount = self.cost(MAX_REQUEST_TOKENS)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            spent = self.db.execute("SELECT COALESCE(SUM(COALESCE(cost_nusd,reserved_nusd)),0) FROM calls").fetchone()[0]
            if spent + amount > self.cap_nusd:
                raise BudgetExceeded(
                    f"Budget limit: ${spent / 1e9:.6f} accounted; next request reserves "
                    f"${amount / 1e9:.6f}; cap ${self.cap_nusd / 1e9:.6f}."
                )
            row = self.db.execute(
                "INSERT INTO calls(request_hash,created,status,reserved_nusd) VALUES (?,?,?,?)",
                (request_hash, time.time(), "pending", amount),
            ).lastrowid
            self.db.execute("COMMIT")
            return int(row)
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, row: int, request_hash: str, data: dict, latency: float) -> None:
        usage = data["usage"]
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "UPDATE calls SET status='ok',cost_nusd=?,input_tokens=?,output_tokens=?,latency_s=?,model=? WHERE id=?",
                (self.cost(usage["input_tokens"]), usage["input_tokens"], usage["output_tokens"], latency, data["model"], row),
            )
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (request_hash, canonical(data)))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def failed(self, row: int) -> None:
        self.db.execute("UPDATE calls SET status='uncertain' WHERE id=?", (row,))

    def cached(self, request_hash: str) -> dict | None:
        row = self.db.execute("SELECT response FROM cache WHERE request_hash=?", (request_hash,)).fetchone()
        return json.loads(row[0]) if row else None

    def summary(self) -> dict:
        row = self.db.execute("""SELECT COUNT(*),COALESCE(SUM(input_tokens),0),
            COALESCE(SUM(output_tokens),0),COALESCE(SUM(cost_nusd),0),
            COALESCE(SUM(CASE WHEN cost_nusd IS NULL THEN reserved_nusd ELSE 0 END),0)
            FROM calls""").fetchone()
        return dict(attempted_requests=row[0], input_tokens=row[1], output_tokens=row[2],
                    known_cost_usd=row[3]/1e9, uncertain_reservation_usd=row[4]/1e9,
                    cap_usd=self.cap_nusd/1e9, input_usd_per_million=self.rate)

    def close(self) -> None:
        self.db.close()


@dataclass
class Call:
    response: dict
    request_hash: str
    cached: bool
    latency_s: float
    new_input_tokens: int
    new_output_tokens: int
    new_cost_usd: float
    request: dict = field(default_factory=dict)


@dataclass
class JevClient:
    key: str = field(repr=False)
    ledger: Ledger
    model: str = DEFAULT_MODEL
    use_cache: bool = True
    offline: bool = False
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=45, follow_redirects=False))
    calls: list[Call] = field(default_factory=list)

    def evaluate(self, state: Any, questions: dict) -> Call:
        validate_questions(questions)
        payload = dict(state=state, model=self.model, questions=questions)
        encoded = canonical(payload)
        request_hash = hashlib.sha256((ENDPOINT + "\n" + encoded).encode()).hexdigest()
        start = time.perf_counter()
        cached = self.ledger.cached(request_hash) if self.use_cache else None
        if cached is not None:
            validate_response(cached, questions)
            call = Call(cached, request_hash, True, time.perf_counter()-start, 0, 0, 0)
        else:
            if self.offline:
                raise JevError("Offline cache miss; no request was sent.")
            if not self.key:
                raise JevError("A Jev API key is required for an uncached request.")
            # This byte cap protects against accidental giant uploads. It is not a
            # tokenizer estimate; the server enforces the separate 32k/64k limits.
            if len(encoded.encode()) > 100_000:
                raise ValueError("Request exceeds the local 100 kB upload limit.")
            row = self.ledger.reserve(request_hash)
            try:
                response = self.http.post(ENDPOINT, content=encoded.encode(), headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                })
                if response.status_code != 200:
                    # Do not echo server bodies: they may contain submitted text.
                    raise JevError(f"Jev returned HTTP {response.status_code}; no automatic retry; reservation retained.")
                data = response.json()
                validate_response(data, questions)
                latency = time.perf_counter()-start
                self.ledger.finish(row, request_hash, data, latency)
            except BaseException as exc:
                self.ledger.failed(row)
                if isinstance(exc, (JevError, KeyboardInterrupt, SystemExit)):
                    raise
                raise JevError(f"Request failed ({type(exc).__name__}); reservation retained.") from None
            usage = data["usage"]
            call = Call(data, request_hash, False, latency, usage["input_tokens"], usage["output_tokens"],
                        self.ledger.cost(usage["input_tokens"])/1e9)
        self.calls.append(call)
        call.request = payload
        return call

    def close(self) -> None:
        self.http.close()
        self.ledger.close()


def call_summary(calls: list[Call]) -> dict:
    return dict(requests=sum(not c.cached for c in calls), cache_hits=sum(c.cached for c in calls),
                input_tokens=sum(c.new_input_tokens for c in calls),
                output_tokens=sum(c.new_output_tokens for c in calls),
                cost_usd=sum(c.new_cost_usd for c in calls),
                request_wall_s=sum(c.latency_s for c in calls),
                models=sorted({c.response["model"] for c in calls}))
