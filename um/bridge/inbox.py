"""Turn account-memory files the bridge pulled into evidence.

Each `inbox/*.json` is {"path", "version", "updated", "content"}, written by the scheduled task. Edits in
account memory are made by Claude in chats, so their origin is `assistant`. A file whose content is
exactly what we last pushed is our own echo and is skipped. `inbox/conflicts/` and `inbox/held/` are
left for the digest and the compile.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def ingest_inbox(inbox: Path, evidence_dir: Path, state: dict) -> list[str]:
    inbox, evidence_dir = Path(inbox), Path(evidence_dir)
    if not inbox.is_dir():
        return []
    ids = []
    for f in sorted(inbox.glob("*.json")):
        item = json.loads(f.read_text())
        content = item["content"]
        pushed = state.get(item["path"], {}).get("pushed_sha256")
        if pushed == hashlib.sha256(content.encode()).hexdigest():
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", item["path"].lower()).strip("-")
        eid = f"mem-{slug}-v{item['version']}"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / f"{eid}.md").write_text(f"origin: assistant\ndate: {item['updated'][:10]}\n\n{content.strip()}\n")
        ids.append(eid)
    return ids


def materialize_inbox(inbox: Path, out: Path) -> list[str]:
    """Write each pulled memory file's content, verbatim, at its memory path under `out`. Account memory's
    live format (frontmatter with sources and aliases, a [stated] tag per line) is richer than its export,
    so a profile is bootstrapped from a pull, not from the export. Paths that would leave `out` are skipped."""
    out = Path(out)
    written = []
    for f in sorted(Path(inbox).glob("*.json")):
        item = json.loads(f.read_text())
        path = item.get("path") or ""
        target = (out / path.lstrip("/")).resolve()
        if not path.startswith("/") or out.resolve() not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"])
        written.append(path)
    return written
