"""Claude Code transcripts as evidence, with origin taken from structure, never from a model.

- `user-said`: a user message whose `origin.kind` is "human" (typed or queued) and that is not `isMeta`.
  Older transcripts have no `origin` field; there a non-meta plain-text user message counts as typed
  unless it starts with a tag such as <command-name> or <local-command-stdout>.
- `tool-output`: every tool_result block (user messages carrying `toolUseResult`).
- `assistant`: text blocks the assistant wrote (thinking and tool calls are dropped).
Everything else is dropped: meta messages, task notifications, subagent reports, sidechains.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

_SLUG = {"user-said": "user", "assistant": "assistant", "tool-output": "tool"}


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
    for line in Path(jsonl).read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") not in ("user", "assistant") or d.get("isSidechain") or not isinstance(d.get("message"), dict):
            continue
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
