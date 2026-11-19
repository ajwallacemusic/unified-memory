"""Stores as plain Markdown files with a lineage sidecar.

Each non-empty line of a Markdown file is one entry. `.lineage.jsonl` at the root of a stores folder
records, for lines written by a checked pass, where they came from. A line with no record is
"legacy": it predates lineage and its source is unknown.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ORIGIN_RANK = {"user-said": 3, "assistant": 2, "legacy": 2, "probe": 2, "tool-output": 1, "file-edit": 1}
LINEAGE_FILE = ".lineage.jsonl"


@dataclass
class Change:
    op: str                      # "add" | "replace" | "remove"
    file: str                    # path relative to the stores root
    old: str | None              # exact existing line, for replace and remove
    new: str | None              # the new line, for add and replace
    citations: list[dict] = field(default_factory=list)   # [{"evidence": id, "quote": text}]
    duplicate_of: dict | None = None                      # {"file": ..., "line": ...} for de-duplicating removes
    question: dict | None = None                          # {"attr": ..., "text": ...}


class Lineage:
    def __init__(self, root: Path):
        self.path = Path(root) / LINEAGE_FILE
        self._rows: dict[tuple[str, str], dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._rows[(row["file"], row["line"])] = row

    def origin_of(self, file: str, line: str) -> str:
        row = self._rows.get((file, line.strip()))
        return row["origin"] if row else "legacy"

    def record(self, file: str, line: str, origin: str, asserted: str, citations: list[dict]) -> None:
        row = {"file": file, "line": line.strip(), "origin": origin, "asserted": asserted, "citations": citations}
        self._rows[(file, row["line"])] = row
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def lines_of(root: Path) -> list[tuple[str, str]]:
    """Every non-empty line of every Markdown file under `root`, as (relative file, stripped line)."""
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue   # hidden: lineage, answers and pass records are not store content
        rel = p.relative_to(root).as_posix()
        out += [(rel, line.strip()) for line in p.read_text().splitlines() if line.strip()]
    return out


def _find(lines: list[str], old: str) -> list[int]:
    return [i for i, line in enumerate(lines) if line.strip() == old.strip()]


def _copy(src_root: Path, out_root: Path) -> None:
    if out_root.exists():
        shutil.rmtree(out_root)
    shutil.copytree(src_root, out_root)


def apply_changes(src_root: Path, out_root: Path, changes: list[Change], origins: dict[int, str], as_of: str) -> None:
    """Copy `src_root` to `out_root` and apply the changes there; the first bad change raises.
    The source is never written to."""
    src_root, out_root = Path(src_root), Path(out_root)
    _copy(src_root, out_root)
    lineage = Lineage(out_root)
    for i, c in enumerate(changes):
        _apply_one(out_root, lineage, c, origins.get(i, "legacy"), as_of)


def apply_each(src_root: Path, out_root: Path, changes: list[Change], origins: dict[int, str], as_of: str) -> list[bool]:
    """Like apply_changes, but a change that no longer fits (for example two changes aimed at the same
    line) is skipped instead of stopping the rest. Returns which changes landed."""
    src_root, out_root = Path(src_root), Path(out_root)
    _copy(src_root, out_root)
    lineage = Lineage(out_root)
    landed = []
    for i, c in enumerate(changes):
        try:
            _apply_one(out_root, lineage, c, origins.get(i, "legacy"), as_of)
            landed.append(True)
        except ValueError:
            landed.append(False)
    return landed


_TAG = re.compile(r"^([-*]\s+)(\[[a-z-]+\]\s+)")


def _tagged(new: str, like: list[str]) -> str:
    """Give a new line the `[tag]` its neighbours carry (account memory's live format tags every fact
    line, e.g. `- [stated]`): the tag of the replaced line, or for an add the one tag every bullet in the
    file shares. A line that already has a tag, or a file without one, is left alone."""
    new = new.strip()
    m = _TAG.match(new)
    if m or not re.match(r"[-*]\s+", new):
        return new
    tags = {t.group(2) for t in map(_TAG.match, like) if t}
    if len(tags) != 1 or any(not _TAG.match(x) for x in like):
        return new
    bullet = re.match(r"[-*]\s+", new).group(0)
    return bullet + tags.pop() + new[len(bullet):]


def _apply_one(out_root: Path, lineage: Lineage, c: Change, origin: str, as_of: str) -> None:
    if True:
        path = out_root / c.file
        if out_root.resolve() not in path.resolve().parents:
            raise ValueError(f"{c.file!r} is outside the stores folder")
        if c.op == "add":
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text() if path.exists() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            new = _tagged(c.new, [x.strip() for x in text.splitlines() if re.match(r"\s*[-*]\s+", x)])
            path.write_text(text + new + "\n")
        elif c.op in ("replace", "remove"):
            if not path.is_file():
                raise ValueError(f"{c.file!r} does not exist")
            lines = path.read_text().splitlines(keepends=True)
            hits = _find(lines, c.old or "")
            if c.op == "remove" and c.duplicate_of and len(hits) >= 2:
                hits = hits[-1:]   # an exact duplicate within one file: drop the later copy
            if len(hits) != 1:
                raise ValueError(f"expected exactly one line matching {c.old!r} in {c.file!r}, found {len(hits)}")
            if c.op == "replace":
                new = _tagged(c.new, [lines[hits[0]].strip()])
                lines[hits[0]] = new + "\n"
            else:
                del lines[hits[0]]
            path.write_text("".join(lines))
        else:
            raise ValueError(f"unknown op {c.op!r}")
        if c.op in ("add", "replace"):
            lineage.record(c.file, new, origin, as_of, c.citations)
