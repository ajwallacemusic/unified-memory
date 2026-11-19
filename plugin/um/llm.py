"""Model clients.

`AnthropicLLM` calls the Claude API through the official SDK, checks the spend cap before every
request and charges it afterwards. `FakeLLM` replays a script for tests.

No model fallback is configured on purpose: a silent switch to another model would contaminate a
measurement, so a refusal is returned as an outcome and counted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from um.budget import Budget
from um.tools import Toolbox

EFFORT = "medium"
OUTCOMES = ("ok", "refusal", "max_tokens", "empty", "max_turns")


@dataclass
class Reply:
    text: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    backend: str = "api"
    usd: float = 0.0


def outcome_of(reply: Reply) -> str:
    if reply.stop_reason in ("refusal", "max_tokens", "max_turns"):
        return reply.stop_reason
    if not reply.text.strip():
        return "empty"
    return "ok"


class LLM(Protocol):
    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply: ...

    def run_tools(self, *, model: str, system: str, user: str, tools: Toolbox, max_turns: int,
                  max_tokens: int, label: str) -> Reply: ...


def _estimate_tokens(*parts: object) -> int:
    """Deliberately high estimate (3 characters per token) used only for the pre-flight cap check."""
    return sum(len(str(p)) for p in parts) // 3 + 100


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def _input_tokens(usage) -> int:
    return (
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    )


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "ANTHROPIC_API_KEY" and value.strip() and "ANTHROPIC_API_KEY" not in os.environ:
            os.environ["ANTHROPIC_API_KEY"] = value.strip()


class AnthropicLLM:
    def __init__(self, budget: Budget, client=None):
        self.budget = budget
        if client is None:
            import anthropic

            _load_dotenv()
            # Zero-argument construction also picks up an `ant auth login` profile.
            client = anthropic.Anthropic(max_retries=4)
        self.client = client

    def _request(self, *, model: str, system: str, messages: list, max_tokens: int, label: str, tools=None):
        reserved = self.budget.check(model, _estimate_tokens(system, messages, tools or ""), max_tokens)
        kwargs = dict(model=model, max_tokens=max_tokens, messages=messages, output_config={"effort": EFFORT})
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
            # A tool loop resends its whole history every turn; caching the prefix makes the repeats cheap.
            kwargs["cache_control"] = {"type": "ephemeral"}
        try:
            response = self.client.messages.create(**kwargs)
        except BaseException:
            self.budget.release(reserved)
            raise
        u = response.usage
        usd = self.budget.charge(model, getattr(u, "input_tokens", 0) or 0, u.output_tokens, label,
                                 cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                                 cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                                 reserved=reserved)
        return response, usd

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply:
        response, usd = self._request(model=model, system=system, messages=[{"role": "user", "content": user}],
                                      max_tokens=max_tokens, label=label)
        return Reply(_text_of(response), response.stop_reason, _input_tokens(response.usage),
                     response.usage.output_tokens, usd=usd)

    def run_tools(self, *, model: str, system: str, user: str, tools: Toolbox, max_turns: int,
                  max_tokens: int, label: str) -> Reply:
        messages: list = [{"role": "user", "content": user}]
        specs = tools.specs()
        total_in = total_out = 0
        total_usd = 0.0
        text = ""
        for _ in range(max_turns):
            response, usd = self._request(model=model, system=system, messages=messages, max_tokens=max_tokens,
                                          label=label, tools=specs)
            total_usd += usd
            total_in += _input_tokens(response.usage)
            total_out += response.usage.output_tokens
            text = _text_of(response) or text
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason != "tool_use":
                return Reply(_text_of(response), response.stop_reason, total_in, total_out, usd=total_usd)
            # Keep the assistant turn exactly as returned, then answer every tool call in one user turn.
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = tools.call(block.name, dict(block.input))
                result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
                if output.startswith("ERROR:"):
                    result["is_error"] = True
                results.append(result)
            messages.append({"role": "user", "content": results})
        return Reply(text, "max_turns", total_in, total_out, usd=total_usd)


class FakeLLM:
    """Replays a script. A `Reply` ends a call; a dict `{"tool": name, "args": {...}}` is run against
    the toolbox passed to `run_tools` before the next entry is read."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def _next(self):
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        return self.script.pop(0)

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply:
        self.calls.append({"kind": "complete", "model": model, "system": system, "user": user, "label": label})
        entry = self._next()
        if not isinstance(entry, Reply):
            raise AssertionError("FakeLLM.complete needs a Reply next in the script")
        return entry

    def run_tools(self, *, model: str, system: str, user: str, tools: Toolbox, max_turns: int,
                  max_tokens: int, label: str) -> Reply:
        self.calls.append({"kind": "run_tools", "model": model, "system": system, "user": user, "label": label,
                           "tools": tools})
        while True:
            entry = self._next()
            if isinstance(entry, Reply):
                return entry
            tools.call(entry["tool"], entry["args"])
