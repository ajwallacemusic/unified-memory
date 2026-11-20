"""Claude Code transcripts (`~/.claude/projects/*/*.jsonl`) as sessions of exchanges (spec, "Sources and what
is indexed").

An exchange is one typed user turn plus the assistant `text` blocks after it, up to the next typed turn. "Typed"
is the rule in `um.transcripts._typed`. Tool results, thinking, meta records, compaction summaries, sidechains
and bookkeeping records are never read into an exchange. `sdk-cli` sessions are skipped whole by default.
"""
from __future__ import annotations

import json
from pathlib import Path

from um.search.model import MAX_USER_CHARS, Exchange, SessionDoc
from um.transcripts import _texts, _typed

_KEPT = ("user", "assistant", "ai-title")
_META_KEYS = ("native_id", "title", "project", "started_at", "updated_at")


def discover(projects: Path) -> list[Path]:
    """Session transcripts directly under each project folder; subagent files sit deeper and are not listed."""
    return sorted(p for p in Path(projects).glob("*/*.jsonl") if p.is_file())


def _skipped(d: dict) -> bool:
    if d.get("type") not in _KEPT:
        return True
    if d.get("isSidechain") or d.get("isMeta") or d.get("isCompactSummary") or "toolUseResult" in d:
        return True
    return d["type"] != "ai-title" and not isinstance(d.get("message"), dict)


def _clean(s):
    """Text safe to encode as UTF-8: a lone surrogate (valid in JSON, invalid in UTF-8) becomes "?"."""
    if not isinstance(s, str):
        return s
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return s.encode("utf-8", "replace").decode("utf-8")


def read_transcript(path: Path, *, surface: str = "code", offset: int = 0, idle: bool = False,
                    include_sdk: bool = False, meta: dict | None = None) -> tuple[SessionDoc | None, int]:
    """Read from byte `offset`; return the closed exchanges found and the byte offset where the last exchange
    starts (or where reading stopped). An exchange is closed when a later typed turn follows it, or when `idle`
    is true; an exchange closed by `idle` is still returned as the offset, so text written after it joins it on
    the next read. A last line that is not valid JSON and has no newline ends the read at its start (it may be
    half-written); any other bad line is skipped. An `sdk-cli` record anywhere in the read returns
    (None, offset) unless `include_sdk`."""
    path = Path(path)
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()

    closed: list[Exchange] = []
    current: dict | None = None      # {"start", "id", "at", "user", "texts", "tools"}
    title = ""
    project = native = None
    first_ts = last_ts = None
    pos = offset
    end = offset + len(data)

    for raw in data.splitlines(keepends=True):
        start = pos
        pos += len(raw)
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            if pos == end and not raw.endswith(b"\n"):
                end = start              # half-written tail: read it again once it is complete
                break
            continue                     # a corrupt line mid-file: skip it
        if not isinstance(d, dict) or _skipped(d):
            continue
        kind = d["type"]
        if kind in ("user", "assistant") and d.get("entrypoint") == "sdk-cli" and not include_sdk:
            return None, offset
        if native is None and d.get("sessionId"):
            native = d["sessionId"]
        if project is None and d.get("cwd"):
            project = d["cwd"]
        ts = d.get("timestamp")
        if isinstance(ts, str) and ts:
            first_ts = first_ts or ts
            last_ts = ts
        if kind == "ai-title":
            if isinstance(d.get("aiTitle"), str):
                title = d["aiTitle"]
            continue
        content = d["message"].get("content")
        if kind == "user":
            if not _typed(d):
                continue
            if current is not None:
                closed.append(_close(current))
            current = {"start": start, "id": d.get("uuid", ""), "at": ts or "",
                       "user": "\n\n".join(_texts(content))[:MAX_USER_CHARS], "texts": [], "tools": []}
        elif current is not None:     # assistant text before any typed turn has no exchange to join
            current["texts"] += _texts(content)
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") not in current["tools"]:
                    current["tools"].append(b.get("name"))

    if current is not None:
        if idle:
            closed.append(_close(current))
        end = current["start"]

    doc = {"native_id": native or path.stem, "title": title, "project": project,
           "started_at": first_ts or "", "updated_at": last_ts or ""}
    for k in _META_KEYS:
        if meta and meta.get(k) is not None:
            doc[k] = meta[k]
    doc = {k: _clean(v) for k, v in doc.items()}
    return SessionDoc(surface, doc["native_id"], doc["title"], doc["project"], None, doc["started_at"],
                      doc["updated_at"], tuple(closed), str(path)), end


def _close(cur: dict) -> Exchange:
    return Exchange(_clean(cur["id"]), _clean(cur["at"]), _clean(cur["user"]), _clean("\n\n".join(cur["texts"])),
                    tuple(_clean(t) for t in cur["tools"] if isinstance(t, str)))
