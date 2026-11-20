"""Claude desktop local-agent (Cowork) sessions: `local-agent-mode-sessions/<account>/<org>/local_<uuid>.json`
plus the nested Claude Code transcript `local_<uuid>/.claude/projects/*/<cliSessionId>.jsonl` (spec, "Sources and
what is indexed"). Only the metadata file is opened here; credentials, audit logs, uploads and outputs are not.
The transcript itself is read by `um.search.sources.code.read_transcript(path, surface="desktop", meta=meta)`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_ALLOWED = ("sessionId", "cliSessionId", "title", "createdAt", "lastActivityAt", "cwd", "userSelectedFolders")


def _iso(ms) -> str | None:
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return None
    t = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def discover(root: Path) -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for js in sorted(Path(root).glob("*/*/local_*.json")):
        try:
            raw = json.loads(js.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        d = {k: raw.get(k) for k in _ALLOWED}
        cli = d["cliSessionId"]
        if not isinstance(cli, str) or not cli or "/" in cli:
            continue
        hits = sorted(js.with_suffix("").glob(f".claude/projects/*/{cli}.jsonl"))
        if not hits:
            continue
        folders = d["userSelectedFolders"]
        project = folders[0] if isinstance(folders, list) and folders else d["cwd"]
        meta = {"native_id": d["sessionId"] or js.stem, "title": d["title"], "project": project,
                "started_at": _iso(d["createdAt"]), "updated_at": _iso(d["lastActivityAt"])}
        out.append((hits[0], meta))
    return out
