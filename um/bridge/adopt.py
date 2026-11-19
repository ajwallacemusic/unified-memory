"""Merge what a chat changed in account memory into the profile, without a model.

The compile sees pulled memory files only as evidence, and its writer has proposed nothing for them (2026-11-17:
three facts told to chat, none reached the profile); it also cannot remove a line just because memory dropped it.
So each pulled file is merged three ways against the last text both sides agreed on (the base):

- base: the text the bridge last pushed for that path (`.um/pushed/<sha256>.md`, when state's `pushed_sha256`
  names one), else the memory text the last compile took in (`.um/synced/<slug>.md`);
- a line in the pull but not in the base is a chat addition: appended unless the profile already has it or it
  was erased (`.um/erased.txt`, hashes only);
- a line in the base but not in the pull is a chat removal (or the old half of a rewrite): removed from the
  profile if the profile still has it;
- with no base, nothing is merged and the path is not reported as merged, so its version is not advanced and
  the next push conflicts instead of overwriting the chat's edit;
- a memory file the profile does not have (and that was not deleted on purpose) is copied in, minus erased lines.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from um.bridge.prepare import MIRRORED, _frontmatter_end, _is_structure, fact_lines

SYNCED, PUSHED, ERASED = ".um/synced", ".um/pushed", ".um/erased.txt"


def _slug(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def _evidence_id(path: str, version: str) -> str:
    return f"mem-{_slug(path)}-v{version}"


def line_hash(line: str) -> str:
    return hashlib.sha256(line.strip().lower().encode()).hexdigest()


def erased_hashes(profile: Path) -> set[str]:
    f = Path(profile) / ERASED
    return {x.strip() for x in f.read_text().splitlines() if x.strip()} if f.exists() else set()


def record_erased(profile: Path, lines: list[str]) -> None:
    f = Path(profile) / ERASED
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a") as out:
        out.writelines(line_hash(x) + "\n" for x in lines if x.strip())


def record_synced(profile: Path, path: str, content: str) -> None:
    f = Path(profile) / SYNCED / f"{_slug(path)}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


def record_pushed(profile: Path, text: str) -> str:
    sha = hashlib.sha256(text.encode()).hexdigest()
    f = Path(profile) / PUSHED / f"{sha}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return sha


def base_text(profile: Path, path: str, state: dict) -> str | None:
    profile = Path(profile)
    sha = state.get(path, {}).get("pushed_sha256")
    if sha and (profile / PUSHED / f"{sha}.md").exists():
        return (profile / PUSHED / f"{sha}.md").read_text()
    f = profile / SYNCED / f"{_slug(path)}.md"
    return f.read_text() if f.exists() else None


def _mirrored_path(path: str) -> bool:
    rel = path.lstrip("/")
    return (path.startswith("/") and ".." not in Path(rel).parts
            and any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in MIRRORED))


def _body(content: str) -> list[str]:
    lines = content.splitlines()
    return [x.strip() for x in lines[_frontmatter_end(lines):] if not _is_structure(x)]


def adopt_memory(profile: Path, inbox: Path, state: dict, deleted: set[str]) -> tuple[list[str], set[str]]:
    """(what changed, memory paths whose pull is now fully merged). Only merged paths may advance their version."""
    profile, inbox = Path(profile), Path(inbox)
    done: list[str] = []
    merged: set[str] = set()
    rows: list[dict] = []
    gone = erased_hashes(profile)
    for f in sorted(inbox.glob("*.json")) if inbox.is_dir() else []:
        item = json.loads(f.read_text())
        path, content = item.get("path") or "", item.get("content") or ""
        if not _mirrored_path(path) or path in deleted:
            continue
        rel = path.lstrip("/")
        if state.get(path, {}).get("pushed_sha256") == hashlib.sha256(content.encode()).hexdigest():
            merged.add(path)
            continue
        target = profile / rel
        cite = [{"evidence": _evidence_id(path, item.get("version", "")), "quote": ""}]
        asserted = (item.get("updated") or "")[:10]
        if not target.exists():
            kept = [x for x in content.splitlines(keepends=True) if line_hash(x) not in gone or _is_structure(x)]
            text = "".join(kept)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text if text.endswith("\n") else text + "\n")
            added = fact_lines(text)
            done.append(f"new file {rel} from account memory ({len(added)} lines)")
            rows += [{"file": rel, "line": x, "origin": "assistant", "asserted": asserted, "citations": cite}
                     for x in added]
            merged.add(path)
            continue
        base = base_text(profile, path, state)
        if base is None:
            done.append(f"no common base for {rel}; memory's edits left for review (the next push conflicts)")
            continue
        old, new = set(_body(base)), _body(content)
        local = target.read_text().splitlines()
        have = {x.strip() for x in local}
        removes = {x for x in old - set(new) if x in have}
        adds = [x for x in new if x not in old and x not in have and line_hash(x) not in gone]
        if removes:
            front = _frontmatter_end(local)
            local = [x for n, x in enumerate(local) if n < front or x.strip() not in removes]
            done += [f"remove `{x}` from {rel}" for x in sorted(removes)]
        if adds:
            local += adds
            done += [f"add `{x}` to {rel}" for x in adds]
            rows += [{"file": rel, "line": x, "origin": "assistant", "asserted": asserted, "citations": cite}
                     for x in adds]
        if removes or adds:
            target.write_text("\n".join(local).rstrip("\n") + "\n")
        merged.add(path)
    if rows:
        with (profile / ".lineage.jsonl").open("a") as out:
            out.writelines(json.dumps(r) + "\n" for r in rows)
    return done, merged
