import json

import pytest

from um.budget import Budget, BudgetExceeded, PRICES
from um.llm_openai import OpenAIKeyMissing, OpenAILLM, OpenAIError

MODEL = "gpt-6.2-sol"


def body(text="YES. fine", status="completed", incomplete=None, tin=1000, cached=200, tout=300, refusal=None):
    content = [{"type": "refusal", "refusal": refusal}] if refusal else [{"type": "output_text", "text": text,
                                                                           "annotations": []}]
    return {"id": "resp_1", "status": status, "incomplete_details": incomplete,
            "output": [{"type": "reasoning", "id": "rs_1", "summary": []},
                       {"type": "message", "role": "assistant", "content": content}],
            "usage": {"input_tokens": tin, "input_tokens_details": {"cached_tokens": cached},
                      "output_tokens": tout, "output_tokens_details": {"reasoning_tokens": 250}}}


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, headers, data, timeout):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(data), "timeout": timeout})
        return self.responses.pop(0)


def make(tmp_path, http, cap=1.0, monkeypatch=None, key="sk-test"):
    if monkeypatch is not None:
        if key is None:
            monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        else:
            monkeypatch.setenv("OPENAI_API_KEY", key)
    budget = Budget(cap, tmp_path / "ledger.jsonl")
    return OpenAILLM(budget, http=http, sleep=lambda s: None), budget


def test_request_shape(tmp_path, monkeypatch):
    http = FakeHTTP((200, json.dumps(body()).encode()))
    llm, _ = make(tmp_path, http, monkeypatch=monkeypatch)
    llm.complete(model=MODEL, system="be strict", user="Question?", max_tokens=1000, label="judge:x")
    req = http.requests[0]
    assert req["url"] == "https://api.openai.com/v1/responses"
    assert req["headers"]["Authorization"] == "Bearer sk-test"
    assert req["headers"]["Content-Type"] == "application/json"
    b = req["body"]
    assert b["model"] == MODEL and b["instructions"] == "be strict" and b["input"] == "Question?"
    assert b["max_output_tokens"] == 1000 and b["reasoning"] == {"effort": "medium"} and b["store"] is False
    assert "temperature" not in b


def test_empty_system_is_not_sent(tmp_path, monkeypatch):
    http = FakeHTTP((200, json.dumps(body()).encode()))
    llm, _ = make(tmp_path, http, monkeypatch=monkeypatch)
    llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x")
    assert "instructions" not in http.requests[0]["body"]


def test_reply_parsing_and_spend_row(tmp_path, monkeypatch):
    http = FakeHTTP((200, json.dumps(body("NO. it ignores it", tin=1000, cached=200, tout=300)).encode()))
    llm, budget = make(tmp_path, http, monkeypatch=monkeypatch)
    r = llm.complete(model=MODEL, system="s", user="u", max_tokens=1000, label="judge:openai")
    assert (r.text, r.stop_reason, r.input_tokens, r.output_tokens, r.backend) == (
        "NO. it ignores it", "end_turn", 1000, 300, "openai")
    p = PRICES[MODEL].base
    expected = (800 * p.input + 200 * p.cache_read + 300 * p.output) / 1e6
    assert r.usd == pytest.approx(expected)
    row = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])
    assert row["model"] == MODEL and row["label"] == "judge:openai"
    assert (row["input_tokens"], row["cache_read_tokens"], row["output_tokens"]) == (800, 200, 300)
    assert row["usd"] == pytest.approx(expected) and budget.spent() == pytest.approx(expected)


def test_incomplete_and_refusal_map_to_outcomes(tmp_path, monkeypatch):
    http = FakeHTTP((200, json.dumps(body("", status="incomplete",
                                          incomplete={"reason": "max_output_tokens"})).encode()),
                    (200, json.dumps(body(refusal="I can't help")).encode()))
    llm, _ = make(tmp_path, http, monkeypatch=monkeypatch)
    assert llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x").stop_reason == "max_tokens"
    r = llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x")
    assert (r.stop_reason, r.text) == ("refusal", "")


def test_missing_key_fails_clearly_and_charges_nothing(tmp_path, monkeypatch):
    http = FakeHTTP()
    llm, budget = make(tmp_path, http, monkeypatch=monkeypatch, key=None)
    with pytest.raises(OpenAIKeyMissing, match="OPENAI_API_KEY"):
        llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x")
    assert http.requests == [] and budget.spent() == 0


def test_cap_is_checked_before_the_request(tmp_path, monkeypatch):
    http = FakeHTTP()
    llm, _ = make(tmp_path, http, cap=0.000001, monkeypatch=monkeypatch)
    with pytest.raises(BudgetExceeded):
        llm.complete(model=MODEL, system="", user="u", max_tokens=1000, label="x")
    assert http.requests == []


def test_retries_rate_limits_then_raises_without_the_key(tmp_path, monkeypatch):
    err = (429, b'{"error": {"message": "slow down"}}')
    http = FakeHTTP(err, (200, json.dumps(body()).encode()))
    llm, _ = make(tmp_path, http, monkeypatch=monkeypatch)
    assert llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x").text == "YES. fine"
    http = FakeHTTP((400, b'{"error": {"message": "bad model"}}'))
    llm, budget = make(tmp_path, http, monkeypatch=monkeypatch)
    with pytest.raises(OpenAIError, match="400.*bad model") as e:
        llm.complete(model=MODEL, system="", user="u", max_tokens=10, label="x")
    assert "sk-test" not in str(e.value)
    assert budget._reserved == 0


def test_price_override_registers_an_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delitem(PRICES, "gpt-test", raising=False)
    http = FakeHTTP((200, json.dumps(body(tin=1_000_000, cached=0, tout=1_000_000)).encode()))
    llm = OpenAILLM(Budget(100, tmp_path / "l.jsonl"), http=http, prices={"gpt-test": (1.0, 0.1, 2.0)})
    r = llm.complete(model="gpt-test", system="", user="u", max_tokens=10, label="x")
    assert r.usd == pytest.approx(3.0)
    PRICES.pop("gpt-test")
