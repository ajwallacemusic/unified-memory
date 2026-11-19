from types import SimpleNamespace as NS

import pytest

from um.budget import Budget, BudgetExceeded
from um.llm import AnthropicLLM, FakeLLM, Reply, outcome_of
from um.tools import Toolbox


def test_outcomes_are_classified():
    assert outcome_of(Reply("hi", "end_turn", 1, 1)) == "ok"
    assert outcome_of(Reply("", "refusal", 1, 0)) == "refusal"
    assert outcome_of(Reply("cut", "max_tokens", 1, 9)) == "max_tokens"
    assert outcome_of(Reply("  ", "end_turn", 1, 0)) == "empty"
    assert outcome_of(Reply("partial", "max_turns", 1, 1)) == "max_turns"


def test_fake_llm_runs_tool_calls_against_the_toolbox(tmp_path):
    llm = FakeLLM([{"tool": "write", "args": {"path": "a.md", "content": "x"}}, Reply("done", "end_turn", 1, 1)])
    r = llm.run_tools(model="m", system="", user="", tools=Toolbox(tmp_path, True), max_turns=5, max_tokens=100, label="t")
    assert r.text == "done" and (tmp_path / "a.md").read_text() == "x"


# --- the real client's loop, driven by a stub transport -------------------------------------


def text_response(text, stop="end_turn", tin=10, tout=5):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop, usage=NS(input_tokens=tin, output_tokens=tout))


def tool_response(name, args, call_id="call_1", tin=10, tout=5):
    block = NS(type="tool_use", id=call_id, name=name, input=args)
    return NS(content=[block], stop_reason="tool_use", usage=NS(input_tokens=tin, output_tokens=tout))


class StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def make(tmp_path, responses, cap=1.0):
    client = StubClient(responses)
    budget = Budget(cap, tmp_path / "ledger.jsonl")
    return AnthropicLLM(budget, client=client), client, budget


def test_complete_charges_the_budget_and_sets_medium_effort(tmp_path):
    llm, client, budget = make(tmp_path, [text_response("ready", tin=1000, tout=100)])
    r = llm.complete(model="claude-sonnet-5-5", system="s", user="u", max_tokens=50, label="x")
    assert (r.text, r.stop_reason, r.input_tokens, r.output_tokens) == ("ready", "end_turn", 1000, 100)
    assert budget.spent() == pytest.approx(0.003)
    assert client.requests[0]["output_config"] == {"effort": "medium"}


def test_tool_loop_runs_tools_returns_results_and_sums_usage(tmp_path):
    store = tmp_path / "store"
    llm, client, budget = make(tmp_path, [
        tool_response("write", {"path": "a.md", "content": "x"}, call_id="c1"),
        text_response("done"),
    ])
    r = llm.run_tools(model="claude-haiku-5-5", system="s", user="u", tools=Toolbox(store, True),
                      max_turns=5, max_tokens=100, label="x")
    assert (store / "a.md").read_text() == "x"
    assert (r.text, r.stop_reason, r.input_tokens, r.output_tokens) == ("done", "end_turn", 20, 10)
    results = client.requests[1]["messages"][-1]
    assert results["role"] == "user" and results["content"][0]["tool_use_id"] == "c1"
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == 2


def test_tool_errors_are_flagged_to_the_model(tmp_path):
    llm, client, _ = make(tmp_path, [tool_response("view", {"path": "../x"}), text_response("ok")])
    llm.run_tools(model="claude-haiku-5-5", system="", user="u", tools=Toolbox(tmp_path / "s", False),
                  max_turns=5, max_tokens=100, label="x")
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and result["content"].startswith("ERROR:")


def test_tool_loop_stops_at_max_turns(tmp_path):
    llm, client, _ = make(tmp_path, [tool_response("view", {"path": ""})])
    r = llm.run_tools(model="claude-haiku-5-5", system="", user="u", tools=Toolbox(tmp_path / "s", False),
                      max_turns=3, max_tokens=100, label="x")
    assert r.stop_reason == "max_turns" and len(client.requests) == 3


def test_refusal_and_max_tokens_end_the_loop(tmp_path):
    for stop in ("refusal", "max_tokens"):
        llm, client, _ = make(tmp_path, [text_response("", stop=stop)])
        r = llm.run_tools(model="claude-haiku-5-5", system="", user="u", tools=Toolbox(tmp_path / "s", False),
                          max_turns=3, max_tokens=100, label="x")
        assert r.stop_reason == stop and len(client.requests) == 1


def test_a_call_over_the_cap_is_refused_before_it_is_sent(tmp_path):
    llm, client, _ = make(tmp_path, [text_response("x")], cap=0.0001)
    with pytest.raises(BudgetExceeded):
        llm.complete(model="claude-sonnet-5-5", system="", user="u" * 3000, max_tokens=1000, label="x")
    assert client.requests == []


def test_replies_carry_what_the_call_cost(tmp_path):
    llm, _, _ = make(tmp_path, [text_response("ready", tin=1000, tout=100)])
    assert llm.complete(model="claude-sonnet-5-5", system="", user="u", max_tokens=50, label="x").usd == pytest.approx(0.003)
    llm, _, budget = make(tmp_path / "b", [tool_response("view", {"path": ""}, tin=1000, tout=100), text_response("done", tin=1000, tout=100)])
    (tmp_path / "b").mkdir(exist_ok=True)
    r = llm.run_tools(model="claude-sonnet-5-5", system="", user="u", tools=Toolbox(tmp_path / "s", False),
                      max_turns=5, max_tokens=100, label="x")
    assert r.usd == pytest.approx(0.006) == pytest.approx(budget.spent())


def test_tool_loops_ask_for_caching_and_are_charged_cache_rates(tmp_path):
    cached = NS(content=[NS(type="text", text="done")], stop_reason="end_turn",
                usage=NS(input_tokens=1_000, output_tokens=0, cache_creation_input_tokens=20_000, cache_read_input_tokens=40_000))
    llm, client, budget = make(tmp_path, [cached])
    r = llm.run_tools(model="claude-haiku-5-5", system="s", user="u", tools=Toolbox(tmp_path / "s", False),
                      max_turns=3, max_tokens=100, label="x")
    assert client.requests[0]["cache_control"] == {"type": "ephemeral"}
    assert budget.spent() == pytest.approx(0.003) == pytest.approx(r.usd) and r.input_tokens == 61_000
    llm, client, _ = make(tmp_path / "c", [text_response("x")])
    (tmp_path / "c").mkdir(exist_ok=True)
    llm.complete(model="claude-haiku-5-5", system="s", user="u", max_tokens=10, label="x")
    assert "cache_control" not in client.requests[0]
