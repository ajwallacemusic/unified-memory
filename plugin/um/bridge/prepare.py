"""Build the bridge's outbox: profile files filtered by the category policy, plus a manifest the scheduled
task follows. Deterministic; no model. The manifest never carries the text of a filtered line, because the
task that reads it runs in the cloud.

    python -m um.bridge.prepare --profile P --mode propose-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from difflib import SequenceMatcher
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from um.bridge.policy import blocked_pattern, decide_line, load_policy

MAX_BYTES = 49_152
MIRRORED = ("profile.md", "areas/", "topics/", "people/")
MODES = ("propose-only", "live")
REVISION = 0.6  # similarity at which a local line counts as a revision of a memory line


@dataclass
class Entry:
    path: str
    sha256: str
    bytes: int
    expected_version: int | None
    removed_by_policy: list[dict] = field(default_factory=list)
    kept_in_memory: int = 0


@dataclass
class Manifest:
    mode: str
    generated_at: str
    entries: list[Entry]
    held: list[dict]
    deletions: list[dict] = field(default_factory=list)


def _frontmatter_end(lines: list[str]) -> int:
    """Index of the first line after a leading `---` frontmatter block (0 if there is none)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def _is_structure(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def fact_lines(text: str) -> list[str]:
    """The stripped lines that policy decides on: not frontmatter, headings or blank lines."""
    lines = text.splitlines()
    return [x.strip() for x in lines[_frontmatter_end(lines):] if not _is_structure(x)]


def _latest_pulls(profile: Path, compiled_only: bool = False) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    dirs = [Path(profile) / ".um" / "inbox-done"] + ([] if compiled_only else [Path(profile) / "inbox"])
    for d in dirs:
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            item = json.loads(f.read_text())
            path = item.get("path") or ""
            if path.startswith("/") and item.get("updated", "") >= latest.get(path, {}).get("updated", ""):
                latest[path] = item
    return latest


def memory_lines(profile: Path, state: dict | None = None) -> dict[str, list[str]]:
    """Fact lines memory holds for each file: its newest pull (`inbox/`, `.um/inbox-done/`) plus the text the
    bridge last pushed there, which a pull taken before that push does not show."""
    from um.bridge.adopt import base_text
    out = {p: fact_lines(i["content"]) for p, i in _latest_pulls(profile).items()}
    for path in [k for k in (state or {}) if k.startswith("/")]:
        base = base_text(profile, path, state)
        if base:
            out[path] = out.get(path, []) + [x for x in fact_lines(base) if x not in out.get(path, [])]
    return out


def pulled_versions(profile: Path) -> dict[str, str]:
    """Memory's version of each file as of the last pull a compile has taken in (`.um/inbox-done/`). A live
    write expects this version, so a file edited in a chat since then is a conflict, not an overwrite."""
    return {p: i.get("version") for p, i in _latest_pulls(profile, compiled_only=True).items()}


def pulled_texts(profile: Path) -> dict[str, str]:
    """Memory's full text of each file as of the last compiled pull (`.um/inbox-done/`)."""
    return {p: i.get("content") for p, i in _latest_pulls(profile, compiled_only=True).items()}


def deleted_paths(profile: Path) -> set[str]:
    """Memory paths a live run has deleted: `.um/deleted.txt`, one `/path` per line. Their old pulls stay in
    `.um/inbox-done/`, so without this list they would be proposed for deletion again."""
    f = Path(profile) / ".um" / "deleted.txt"
    return {x.strip() for x in f.read_text().splitlines() if x.strip().startswith("/")} if f.exists() else set()


def record_done_deletions(profile: Path, state: dict) -> list[str]:
    """Add to `.um/deleted.txt` each deletion in the current manifest that a later live run carried out: the run
    logged no error and at least one deletion, state no longer has the path, and no conflict file names it."""
    profile = Path(profile)
    mf, log = profile / "outbox" / "manifest.json", profile / "bridge-log.jsonl"
    if not (mf.exists() and log.exists()):
        return []
    manifest = json.loads(mf.read_text())
    lines = [x for x in log.read_text().splitlines() if x.strip()]
    last = json.loads(lines[-1]) if lines else {}
    if not (last.get("mode") == "live" and last.get("error") is None and (last.get("deleted") or 0) > 0
            and str(last.get("run_at", "")) > str(manifest.get("generated_at", ""))):
        return []
    known = deleted_paths(profile)
    done = []
    for d in manifest.get("deletions") or []:
        path = d.get("path") or ""
        slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
        if path and path not in known and path not in state and not (profile / "inbox" / "conflicts" / f"{slug}.json").exists():
            done.append(path)
    if done:
        (profile / ".um").mkdir(exist_ok=True)
        with (profile / ".um" / "deleted.txt").open("a") as out:
            out.writelines(x + "\n" for x in done)
    return done


def approved_deletions(profile: Path) -> set[str]:
    """Memory paths the person approved for deletion: `delete-approved.txt`, one `/path` per line."""
    f = Path(profile) / "delete-approved.txt"
    return {x.strip() for x in f.read_text().splitlines() if x.strip().startswith("/")} if f.exists() else set()


def answered_lines(profile: Path) -> dict[str, set[str]]:
    """Lines a compile wrote on the strength of the person's own answer (lineage cites an `.answers/` file)."""
    profile = Path(profile)
    ids = {f.stem for f in (profile / ".answers").glob("*.md")} if (profile / ".answers").is_dir() else set()
    out: dict[str, set[str]] = {}
    lineage = profile / ".lineage.jsonl"
    for row in (json.loads(x) for x in lineage.read_text().splitlines() if x.strip()) if lineage.exists() else []:
        if any((c or {}).get("evidence") in ids for c in row.get("citations") or []):
            out.setdefault("/" + row["file"].lstrip("/"), set()).add(row["line"].strip())
    return out


_NOISE = re.compile(r"^[-*]\s+(\[[a-z-]+\]\s+)?|\s*\(\d{4}-\d{2}-\d{2}\)\s*$")


def _core(line: str) -> str:
    return _NOISE.sub("", line.strip())


def _in_memory(line: str, memory: list[str], local: set[str]) -> bool:
    """The line is in memory, or revises a memory line the local file no longer has. Similarity is measured
    without the bullet, the tag and a trailing date, which would otherwise make unrelated lines look alike."""
    if line in memory:
        return True
    return any(SequenceMatcher(None, _core(line), _core(m)).ratio() >= REVISION for m in memory if m not in local)


def _mirrored(profile: Path) -> list[Path]:
    out = []
    for p in sorted(profile.rglob("*.md")):
        rel = p.relative_to(profile).as_posix()
        if any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in MIRRORED):
            out.append(p)
    return out


def build_outbox(profile: Path, outbox: Path, policy: dict[str, str], categories: dict[str, str], state: dict,
                 mode: str, in_memory: dict[str, list[str]] | None = None,
                 answered: dict[str, set[str]] | None = None, pulled: dict[str, str] | None = None,
                 approved_deletions: set[str] | None = None,
                 memory_text: dict[str, str] | None = None, deleted: set[str] | None = None) -> Manifest:
    """Category policy decides what is added to memory; it never removes a line memory already holds (the person
    put it there), a revised line replaces its memory version, and a line written from the person's own answer
    is pushed. Never-store patterns are removed regardless. A file whose text memory already holds (as of the last
    compiled pull, with no push since) is not sent: writing it would change nothing."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    profile, outbox = Path(profile), Path(outbox)
    if outbox.exists():
        shutil.rmtree(outbox)
    outbox.mkdir(parents=True)
    entries, held, seen = [], [], set()
    for p in _mirrored(profile):
        path = "/" + p.relative_to(profile).as_posix()
        seen.add(path)
        kept, removed, facts, held_over = [], [], 0, 0
        lines = p.read_text().splitlines()
        front = _frontmatter_end(lines)
        memory = (in_memory or {}).get(path, [])
        local = set(fact_lines(p.read_text()))
        for n, line in enumerate(lines):
            s = line.strip()
            if n < front or _is_structure(line):
                if not blocked_pattern(line):
                    kept.append(line)
                continue
            key = hashlib.sha1(s.encode()).hexdigest()
            state_, reason = decide_line(s, categories.get(key), policy)
            if state_ != "push" and not blocked_pattern(s) and (s in memory or (state_ == "local" and _in_memory(s, memory, local))
                                                                 or s in (answered or {}).get(path, set())):
                state_, held_over = "push", held_over + 1
            if state_ == "push":
                kept.append(line)
                facts += 1
            else:
                removed.append({"sha1": key, "state": state_, "reason": reason})
        if not facts:
            held.append({"path": path, "reason": "nothing to push"})
            continue
        text = "\n".join(kept).rstrip() + "\n"
        data = text.encode()
        if len(data) > MAX_BYTES:
            held.append({"path": path, "reason": "too large"})
            continue
        digest = hashlib.sha256(data).hexdigest()
        if state.get(path, {}).get("pushed_sha256") == digest:
            continue
        if (text.rstrip("\n") == ((memory_text or {}).get(path) or "\0").rstrip("\n")
                and state.get(path, {}).get("version") in (None, (pulled or {}).get(path))):
            continue
        target = outbox / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        from um.bridge.adopt import record_pushed
        record_pushed(profile, text)
        expected = state.get(path, {}).get("version") or (pulled or {}).get(path)
        entries.append(Entry(path, digest, len(data), expected, removed, held_over))
    deletions = []
    known = {k: v.get("version") for k, v in state.items() if k.startswith("/") and isinstance(v, dict)}
    known.update({k: v for k, v in (pulled or {}).items() if k not in known})
    for path in sorted(set(known) - seen - (deleted or set())):
        if path in (approved_deletions or set()):
            deletions.append({"path": path, "expected_version": known[path]})
        else:
            held.append({"path": path, "reason": "removal proposal"})
    m = Manifest(mode, datetime.now(timezone.utc).isoformat(timespec="seconds"), entries, held, deletions)
    (outbox / "manifest.json").write_text(json.dumps(asdict(m), indent=1))
    return m


def categorize_profile(profile: Path, llm, model: str) -> dict:
    """Label every mirrored fact line into .um/categories.json; return counts per category and per policy state."""
    from um.bridge.categorize import categorize
    profile = Path(profile)
    lines = [x for f in _mirrored(profile) for x in fact_lines(f.read_text())]
    cats = categorize(lines, llm, model, profile / ".um" / "categories.json")
    policy = load_policy(profile / "policy.json")
    counts: dict = {"categories": {}, "states": {}}
    for line in lines:
        cat = cats[hashlib.sha1(line.encode()).hexdigest()]
        state_, _ = decide_line(line, cat, policy)
        counts["categories"][cat] = counts["categories"].get(cat, 0) + 1
        counts["states"][state_] = counts["states"].get(state_, 0) + 1
    return counts


def ready_for_live(log: list[dict]) -> bool:
    """Two consecutive reviewed propose-only runs with something proposed and nothing rejected."""
    last = log[-2:]
    return len(last) == 2 and all(r.get("mode") == "propose-only" and r.get("reviewed") is True
                                  and r.get("rejected") == 0 and (r.get("proposed") or 0) >= 1 for r in last)


def live_allowed(log: list[dict]) -> bool:
    """Live once the gate has been passed (two clean reviewed propose-only runs in a row), until a live
    run has something rejected; after that the gate has to be passed again."""
    ok = False
    for i, r in enumerate(log):
        if r.get("mode") == "live" and (r.get("rejected") or 0) > 0:
            ok = False
        elif ready_for_live(log[: i + 1]):
            ok = True
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="um.bridge.prepare")
    ap.add_argument("--profile", type=Path, default=None)
    ap.add_argument("--mode", choices=MODES)
    ap.add_argument("--categorize", action="store_true", help="label the profile's lines (Haiku) and print counts")
    ap.add_argument("--model", default="claude-haiku-5-5")
    a = ap.parse_args(argv)
    from um.config import profile_path
    p = profile_path(a.profile)
    if a.categorize:
        from um.cli import _llm
        print(json.dumps(categorize_profile(p, _llm(), a.model), indent=1))
        return
    if not a.mode:
        ap.error("--mode is required unless --categorize is given")
    read = lambda name: json.loads((p / name).read_text()) if (p / name).exists() else {}
    if a.mode == "live":
        log = [json.loads(x) for x in (p / "bridge-log.jsonl").read_text().splitlines()] if (p / "bridge-log.jsonl").exists() else []
        if not live_allowed(log):
            raise SystemExit("not ready for live: needs two reviewed propose-only runs with nothing rejected, "
                             "and no rejection in a live run since")
    if not (p / "state.json").exists():
        (p / "state.json").write_text("{}")
    record_done_deletions(p, read("state.json"))
    m = build_outbox(p, p / "outbox", load_policy(p / "policy.json"), read(".um/categories.json"), read("state.json"), a.mode,
                     memory_lines(p, read("state.json")), answered_lines(p), pulled_versions(p), approved_deletions(p),
                    memory_text=pulled_texts(p), deleted=deleted_paths(p))
    print(f"{len(m.entries)} files to push, {len(m.held)} held, mode {m.mode}")
    for e in m.entries:
        print(f"  {e.path}: {e.bytes} bytes, {len(e.removed_by_policy)} lines kept back by policy, "
              f"{e.kept_in_memory} sensitive lines left as memory has them")
    for h in m.held:
        print(f"  held {h['path']}: {h['reason']}")
    for d in m.deletions:
        print(f"  delete {d['path']} (approved in delete-approved.txt)")


if __name__ == "__main__":
    main()
