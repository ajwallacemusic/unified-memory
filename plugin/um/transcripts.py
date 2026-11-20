"""Claude Code transcripts as evidence, with origin taken from structure, never from a model.

- `user-said`: a user message whose `origin.kind` is "human" (typed or queued) and that is not `isMeta`.
  Older transcripts have no `origin` field; there a non-meta plain-text user message counts as typed
  unless it starts with a tag such as <command-name> or <local-command-stdout>.
- `tool-output`: every tool_result block (user messages carrying `toolUseResult`).
- `assistant`: text blocks the assistant wrote (thinking and tool calls are dropped).
Everything else is dropped: meta messages, task notifications, subagent reports, sidechains, and whole
non-interactive (`claude -p`, entrypoint "sdk-cli") sessions, whose prompts come from scripts and benchmarks.
Results of this plugin's own search tools (SEARCH_TOOLS) are dropped too: an old quote is not a new fact. They are
recognised by tool name on any server named for this project, and by the search notice their text starts with
(which also catches `um.cli search query` run through a shell).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

_SLUG = {"user-said": "user", "assistant": "assistant", "tool-output": "tool"}
SEARCH_TOOLS = ("conversation_search", "recent_chats")
_SERVER_MARKS = ("um-search", "unified-memory")


def _is_search_tool(name) -> bool:
    """`mcp__<server>__<tool>` where the tool is one of ours and the server name names this project, however the
    server was registered (as the plugin, or by hand as `um-search`)."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return False
    server, sep, tool = name[len("mcp__"):].rpartition("__")
    return bool(sep) and tool in SEARCH_TOOLS and any(m in server for m in _SERVER_MARKS)


def _search_call_ids(content) -> set[str]:
    return {b.get("id") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
            and _is_search_tool(b.get("name"))} if isinstance(content, list) else set()


def _is_search_output(block) -> bool:
    """A tool_result whose text starts with the search notice: the search tools' output by any route, including
    `um.cli search query` run through Bash."""
    from um.search.tools import NOTICE
    c = block.get("content")
    texts = [c] if isinstance(c, str) else [x.get("text", "") for x in c or [] if isinstance(x, dict)]
    return any(isinstance(t, str) and t.lstrip().startswith(NOTICE) for t in texts)


def _texts(content, kind: str = "text") -> list[str]:
    if isinstance(content, str):
        return [content] if kind == "text" else []
    out = []
    for b in content or []:
        if not isinstance(b, dict) or b.get("type") != kind:
            continue
        if kind == "text":
            out.append(b.get("text", ""))
        else:
            c = b.get("content")
            out += [c] if isinstance(c, str) else [x.get("text", "") for x in c or [] if isinstance(x, dict)]
    return [t.strip() for t in out if t and t.strip()]


def _typed(d: dict) -> bool:
    if d.get("isMeta") or "toolUseResult" in d:
        return False
    origin = d.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    if origin is not None:
        return False
    content = d["message"].get("content")
    return isinstance(content, str) and not content.lstrip().startswith("<")


def _ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evidence_from_transcript(jsonl: Path, out_dir: Path, since: date | None = None,
                             after: str | None = None) -> list[Path]:
    """`since` keeps messages from that day on; `after` (an ISO time, the last build's start) drops every message
    a build has already read, so a value erased from the profile is not read back from the raw transcript."""
    cutoff = _ts(after) if after else None
    parts: dict[str, list[str]] = {o: [] for o in _SLUG}
    last: dict[str, str] = {}
    session = None
    search_ids: set[str] = set()
    for line in Path(jsonl).read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("entrypoint") == "sdk-cli":  # a `claude -p` run: a script or benchmark typed this, not the person
            return []
        if d.get("type") not in ("user", "assistant") or d.get("isSidechain") or not isinstance(d.get("message"), dict):
            continue
        if d["type"] == "assistant":  # before the date filters: the call may predate the cutoff, its result not
            search_ids |= _search_call_ids(d["message"].get("content"))
        day = (d.get("timestamp") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or (since and day < since.isoformat()):
            continue
        if cutoff and (_ts(d.get("timestamp") or "") or cutoff) <= cutoff:
            continue
        session = session or d.get("sessionId") or Path(jsonl).stem
        content = d["message"].get("content")
        if d["type"] == "assistant":
            found = {"assistant": _texts(content)}
        elif "toolUseResult" in d:
            if isinstance(content, list):
                content = [b for b in content if not (isinstance(b, dict) and (
                    b.get("tool_use_id") in search_ids or _is_search_output(b)))]
            found = {"tool-output": _texts(content, "tool_result")}
        elif _typed(d):
            found = {"user-said": _texts(content)}
        else:
            continue
        for origin, texts in found.items():
            if texts:
                parts[origin] += texts
                last[origin] = max(last.get(origin, day), day)
    out_dir = Path(out_dir)
    sid = re.sub(r"[^a-z0-9]", "", (session or "").lower())[:8] or "session"
    written = []
    for origin, texts in parts.items():
        if texts:
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"s{sid}-{_SLUG[origin]}.md"
            p.write_text(f"origin: {origin}\ndate: {last[origin]}\n\n" + "\n\n".join(texts) + "\n")
            written.append(p)
    return written
