"""Subscription backend: single-shot calls through non-interactive Claude Code, and the router
that chooses between it and the API.

The subscription path has no tools at all, so it cannot touch files. Tool loops always go to the
API, where they run inside the sandboxed toolbox.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from um.llm import EFFORT, Reply
from um.tools import Toolbox


API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def subscription_env() -> dict:
    """The environment for a subscription call. API credentials are removed: non-interactive Claude
    Code uses an API key whenever one is present, which would bill the API with no ledger entry."""
    return {k: v for k, v in os.environ.items() if k not in API_CREDENTIAL_VARS}


class SubscriptionError(Exception):
    """The non-interactive Claude Code call failed or reported an error."""


class ClaudeCodeLLM:
    def __init__(self, runner=subprocess.run, binary: str = "claude", workdir: Path | None = None,
                 timeout_s: int = 900):
        self.runner = runner
        self.binary = binary
        # An empty directory, so no project instructions or memory are picked up.
        self.workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="um-sub-"))
        self.timeout_s = timeout_s

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply:
        cmd = [
            self.binary, "-p",
            "--model", model,
            "--system-prompt", system or "You are a helpful assistant.",
            "--effort", EFFORT,
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources", "",
            "--output-format", "json",
        ]
        try:
            proc = self.runner(cmd, input=user, capture_output=True, text=True, timeout=self.timeout_s,
                               cwd=self.workdir, env=subscription_env())
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SubscriptionError(str(e)) from e
        if proc.returncode != 0:
            raise SubscriptionError(f"exit {proc.returncode}: {proc.stderr[:300]}")
        try:
            data = json.loads(proc.stdout)
        except ValueError as e:
            raise SubscriptionError(f"unreadable output: {proc.stdout[:200]!r}") from e
        if data.get("is_error") or "result" not in data:
            raise SubscriptionError(str(data.get("result") or data.get("subtype") or "error")[:300])
        usage = data.get("usage") or {}
        input_tokens = sum(int(usage.get(k) or 0) for k in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return Reply(data["result"], data.get("stop_reason") or "end_turn", input_tokens,
                     int(usage.get("output_tokens") or 0), backend="subscription")


class HybridLLM:
    """Single-shot calls go to the subscription while the gate is open; everything else to the API."""

    def __init__(self, api, sub, gate):
        self.api, self.sub, self.gate = api, sub, gate
        self._sub_lock = threading.Lock()  # subscription calls run one at a time

    def complete(self, *, model: str, system: str, user: str, max_tokens: int, label: str) -> Reply:
        kwargs = dict(model=model, system=system, user=user, max_tokens=max_tokens, label=label)
        if self.gate.is_open():
            try:
                with self._sub_lock:
                    return self.sub.complete(**kwargs)
            except SubscriptionError:
                pass
        return self.api.complete(**kwargs)

    def run_tools(self, *, model: str, system: str, user: str, tools: Toolbox, max_turns: int,
                  max_tokens: int, label: str) -> Reply:
        return self.api.run_tools(model=model, system=system, user=user, tools=tools, max_turns=max_turns,
                                  max_tokens=max_tokens, label=label)
