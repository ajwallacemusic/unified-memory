import json
from types import SimpleNamespace as NS

import pytest

from um.llm import Reply
from um.llm_sub import ClaudeCodeLLM, HybridLLM, SubscriptionError
from um.tools import Toolbox

ARGS = dict(model="claude-haiku-5-5", system="sys", user="hello", max_tokens=100, label="t")


class StubLLM:
    def __init__(self, backend, fail=False):
        self.backend, self.fail, self.calls = backend, fail, 0

    def complete(self, **kw):
        self.calls += 1
        if self.fail:
            raise SubscriptionError("boom")
        return Reply("x", "end_turn", 1, 1, backend=self.backend)

    def run_tools(self, **kw):
        self.calls += 1
        return Reply("x", "end_turn", 1, 1, backend=self.backend)


class StubGate:
    def __init__(self, is_open):
        self._open = is_open

    def is_open(self):
        return self._open


def test_reply_backend_defaults_to_api():
    assert Reply("x", "end_turn", 1, 1).backend == "api"


def test_hybrid_routes_by_gate_and_never_sends_tools_to_subscription(tmp_path):
    api, sub = StubLLM("api"), StubLLM("subscription")
    assert HybridLLM(api, sub, StubGate(True)).complete(**ARGS).backend == "subscription"
    assert HybridLLM(api, sub, StubGate(False)).complete(**ARGS).backend == "api"
    assert HybridLLM(api, sub, StubGate(True)).run_tools(tools=Toolbox(tmp_path, False), max_turns=1, **ARGS).backend == "api"


def test_hybrid_falls_back_to_api_when_the_subscription_call_fails():
    api, sub = StubLLM("api"), StubLLM("subscription", fail=True)
    assert HybridLLM(api, sub, StubGate(True)).complete(**ARGS).backend == "api"
    assert (sub.calls, api.calls) == (1, 1)


OK_JSON = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ready",
                      "stop_reason": "end_turn",
                      "usage": {"input_tokens": 2, "cache_creation_input_tokens": 616,
                                "cache_read_input_tokens": 0, "output_tokens": 4}})


def test_claude_code_llm_sends_no_tools_and_parses_the_result(tmp_path):
    seen = {}

    def runner(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return NS(returncode=0, stdout=OK_JSON, stderr="")

    r = ClaudeCodeLLM(runner=runner, workdir=tmp_path).complete(**ARGS)
    cmd = seen["cmd"]
    assert cmd[0] == "claude" and "-p" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "sys"
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert seen["input"] == "hello" and str(seen["cwd"]) == str(tmp_path)
    assert (r.text, r.stop_reason, r.input_tokens, r.output_tokens, r.backend) == ("ready", "end_turn", 618, 4, "subscription")


def test_claude_code_llm_raises_on_failure(tmp_path):
    for result in (NS(returncode=1, stdout="", stderr="nope"),
                   NS(returncode=0, stdout="not json", stderr=""),
                   NS(returncode=0, stdout=json.dumps({"is_error": True, "result": "limit reached"}), stderr="")):
        with pytest.raises(SubscriptionError):
            ClaudeCodeLLM(runner=lambda cmd, **kw: result, workdir=tmp_path).complete(**ARGS)


def test_subscription_calls_never_inherit_api_credentials_and_pin_effort(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    seen = {}

    def runner(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return NS(returncode=0, stdout=OK_JSON, stderr="")

    ClaudeCodeLLM(runner=runner, workdir=tmp_path).complete(**ARGS)
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "ANTHROPIC_AUTH_TOKEN" not in seen["env"] and "PATH" in seen["env"]
    assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "medium"
