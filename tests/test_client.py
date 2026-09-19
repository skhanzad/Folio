import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from jev_completion.client import BudgetExceeded, JevClient, JevError, Ledger, api_key, validate_questions

QUESTIONS = {"next": {"type": "choice", "instructions": "Pick.", "criteria": {"a": "apple", "b": "banana"}}}
RESPONSE = {"model": "jev-1.13.0", "answers": {"next": {"type": "choice", "choice": "a",
            "confidence": 0.8, "probabilities": {"a": 0.9, "b": 0.1}}},
            "usage": {"input_tokens": 100, "output_tokens": 40}}


def make_client(tmp_path, handler, **kwargs):
    return JevClient("test-secret", Ledger(tmp_path/"ledger.sqlite", .01),
                     http=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_cache_counts_zero_new_spend_and_preserves_option_order(tmp_path):
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json=RESPONSE)
    c = make_client(tmp_path, handler)
    first = c.evaluate("text", QUESTIONS)
    second = c.evaluate("text", QUESTIONS)
    assert first.new_cost_usd == pytest.approx(.0000042)
    assert second.cached and second.new_cost_usd == 0 and second.new_input_tokens == 0
    assert len(sent) == 1 and c.ledger.summary()["attempted_requests"] == 1
    assert "test-secret" not in repr(c)
    c.close()
    offline = make_client(tmp_path, lambda _: pytest.fail("No network"), offline=True)
    assert offline.evaluate("text", QUESTIONS).cached
    with pytest.raises(JevError, match="cache miss"):
        offline.evaluate("new text", QUESTIONS)
    assert offline.ledger.summary()["attempted_requests"] == 1
    offline.close()
    assert b"test-secret" not in (tmp_path/"ledger.sqlite").read_bytes()


def test_budget_reservations_are_atomic_and_persist(tmp_path):
    path = tmp_path/"ledger.sqlite"
    Ledger(path, .003).close()
    def reserve(_):
        ledger = Ledger(path, .003)
        try:
            ledger.reserve("hash")
            return True
        except BudgetExceeded:
            return False
        finally:
            ledger.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(reserve, range(2))) == 1
    ledger = Ledger(path, .003)
    assert ledger.summary()["uncertain_reservation_usd"] == pytest.approx(.002688)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("again")
    ledger.close()


@pytest.mark.parametrize("response", [httpx.Response(429, text="private prompt"),
    httpx.Response(200, json={**RESPONSE, "usage": {}}),
    httpx.Response(200, json={**RESPONSE, "answers": {}})])
def test_failures_retain_reservation_and_do_not_retry(tmp_path, response):
    sent=[]
    def handler(request):
        sent.append(request)
        return response
    client=make_client(tmp_path, handler)
    with pytest.raises(JevError) as error:
        client.evaluate("text", QUESTIONS)
    assert "private prompt" not in str(error.value)
    assert len(sent) == 1
    assert client.ledger.summary()["uncertain_reservation_usd"] == pytest.approx(.002688)
    assert client.ledger.summary()["known_cost_usd"] == 0
    client.close()


def test_invalid_cardinality_prevents_network(tmp_path):
    c=make_client(tmp_path, lambda _: pytest.fail("No network"))
    q={"n": {"type": "choice", "instructions": "choose", "criteria": {str(i): None for i in range(256)}}}
    with pytest.raises(ValueError, match="255"):
        c.evaluate("x",q)
    assert c.ledger.summary()["attempted_requests"] == 0
    c.close()


def test_env_key_alias_does_not_evaluate_or_interpolate(tmp_path, monkeypatch):
    for key in ["JEV_APIKEY", "JEV-APIKEY", "JEV_API_KEY", "TYPESAFE_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    path=tmp_path/".env"
    path.write_text("JEV-APIKEY='literal${HOME}$(not-a-command)'\n")
    assert api_key(path) == "literal${HOME}$(not-a-command)"


@pytest.mark.parametrize("cap,rate", [(float("nan"),.042), (.1,float("nan")), (0,.042),(.1,-1)])
def test_invalid_budget_configuration(tmp_path,cap,rate):
    with pytest.raises(ValueError):
        Ledger(tmp_path/"ledger.sqlite",cap,rate)
