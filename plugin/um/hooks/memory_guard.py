"""Write-time memory guard: a turn that took in tool output may not write memory directly.

    python -m um.hooks.memory_guard clear   # UserPromptSubmit: a new turn starts untainted
    python -m um.hooks.memory_guard taint   # PostToolUse: mark the turn if the tool brought in outside text
    python -m um.hooks.memory_guard guard   # PreToolUse on Write|Edit|MultiEdit|NotebookEdit|Bash and memory MCP tools

A tainted turn's write to a protected path is denied, and the text it tried to write is held in
`$UM_PROFILE/inbox/held/` as tool-output evidence for the next compile, where code decides. A memory MCP tool
that is not a read, and a shell command that names a protected path or records an answer, count as writes.
State holds tool names only, never content. A guard that fails for any reason, or finds no turn state, denies
(exit 2): a hook that exits with any other error would let the write through.

Environment: UM_STATE_DIR (default ~/.cache/um), UM_PROFILE (default: the um.config profile),
UM_PROTECTED (colon-separated paths or globs; default ~/.claude/projects/*/memory, ~/.claude/CLAUDE.md
and the profile).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from um.config import profile_path

TAINTING = {"WebFetch", "WebSearch", "Bash"}
MEMORY_MCP_READS = ("read", "list", "search", "view", "get")
ANSWER = re.compile(r"um[./]cli\b.*\banswer\b|\banswer\s+--text\b")


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default).expanduser()


def _state_file(session: str) -> Path:
    safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_") or "unknown"
    return _env_path("UM_STATE_DIR", "~/.cache/um") / f"session-{safe}.json"


def _protected() -> list[str]:
    raw = os.environ.get("UM_PROTECTED")
    items = raw.split(":") if raw else ["~/.claude/projects/*/memory", "~/.claude/CLAUDE.md", str(profile_path())]
    return [str(Path(x).expanduser()) for x in items if x]


def _norm(p: str) -> str:
    return p.casefold() if sys.platform == "darwin" else p


def _roots() -> list[str]:
    return [_norm(str(Path(r).resolve()) if not any(ch in r for ch in "*?[") else r) for r in _protected()]


def _is_protected(path: str, cwd: str | None = None) -> bool:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = Path(cwd or os.getcwd()) / raw
    p = _norm(str(raw.resolve()))
    for r in _roots():
        if fnmatch.fnmatch(p, r) or fnmatch.fnmatch(p, r.rstrip("/") + "/*") or p == r or p.startswith(r.rstrip("/") + "/"):
            return True
    return False


def _command_touches_memory(cmd: str) -> bool:
    """A shell command that names a protected path, or records an answer, counts as a memory write."""
    text = _norm(cmd)
    home = _norm(str(Path.home()))
    if ANSWER.search(cmd):
        return True
    for r in _roots():
        stem = r.split("*")[0].rstrip("/")
        if stem and (stem in text or stem.replace(home, "~", 1) in text):
            return True
    return False


def _write_state(session: str, state: dict) -> None:
    f = _state_file(session)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state))


def _attempted_text(tool: str, ti: dict) -> str:
    if tool == "Edit":
        return ti.get("new_string", "")
    if tool == "MultiEdit":
        return "\n".join(e.get("new_string", "") for e in ti["edits"])
    if tool == "NotebookEdit":
        return ti.get("new_source", "")
    if tool == "Write":
        return ti.get("content", "")
    if tool == "Bash":
        return ti.get("command", "")
    return json.dumps(ti)


def _target(tool: str, ti: dict) -> str | None:
    if tool.startswith("mcp__memory__"):
        return "account-memory"
    return ti.get("file_path") or ti.get("notebook_path")


def _hold(text: str, sources: list[str]) -> Path:
    held = profile_path() / "inbox" / "held"
    held.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    n = len(list(held.glob(f"{now:%Y%m%dT%H%M%S}-*.md"))) + 1
    path = held / f"{now:%Y%m%dT%H%M%S}-{n}.md"
    path.write_text(f"origin: tool-output\ndate: {now.date().isoformat()}\n\n{text.strip()}\n")
    return path


def main(argv: list[str] | None = None, stdin=None, stdout=None, stderr=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    cmd = argv[0] if argv else ""
    try:
        event = json.loads(stdin.read())
        session = str(event["session_id"])
    except (ValueError, KeyError, TypeError):
        if cmd == "guard":
            print("memory guard could not read the hook input; the memory write is denied", file=stderr)
            return 2
        return 0
    if cmd == "clear":
        _write_state(session, {"tainted": False, "sources": []})
        return 0
    if cmd == "taint":
        tool = event.get("tool_name", "")
        if tool.startswith("mcp__") or tool in TAINTING:
            f = _state_file(session)
            try:
                state = json.loads(f.read_text()) if f.exists() else {}
            except ValueError:
                state = {}
            sources = sorted(set(state.get("sources", [])) | {tool})
            _write_state(session, {"tainted": True, "sources": sources})
        return 0
    if cmd != "guard":
        print(f"unknown command {cmd!r}", file=stderr)
        return 2
    try:
        return _guard(event, session, stdout)
    except Exception as e:                      # any failure inside the guard must deny, never let the write through
        print(f"memory guard failed ({type(e).__name__}); the memory write is denied", file=stderr)
        return 2


def _guard(event: dict, session: str, stdout) -> int:
    tool, ti = event.get("tool_name", ""), event.get("tool_input")
    if not isinstance(ti, dict):
        raise TypeError("tool_input is not an object")
    if tool.startswith("mcp__memory__"):
        if any(r in tool.rsplit("__", 1)[-1] for r in MEMORY_MCP_READS):
            return 0
    elif tool == "Bash":
        if not _command_touches_memory(str(ti.get("command") or "")):
            return 0
    else:
        target = _target(tool, ti)
        if not target or not _is_protected(target, event.get("cwd")):
            return 0
    f = _state_file(session)
    if not f.exists():
        raise FileNotFoundError("no turn state: the UserPromptSubmit hook did not run")
    state = json.loads(f.read_text())
    if not bool(state["tainted"]):
        return 0
    held = _hold(_attempted_text(tool, ti), state.get("sources", []))
    reason = (f"This turn read tool output ({', '.join(state.get('sources', []))}), so it may not write memory directly. "
              f"The text was held for review at {held}. Do not retry; tell the user it is held.")
    stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                    "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
