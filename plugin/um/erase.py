"""Erase a fact everywhere this project keeps it: store lines, lineage, pass records, answers, evidence.

Raw copies that belong to other apps (chat exports, transcripts) are only reported, never deleted.
Matching is case-insensitive substring on whole values, so a value must be at least 3 characters.

    python -m um.erase --stores DIR --value V [--value V] [--evidence DIR] --yes
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from um.profile import LINEAGE_FILE

PASS_FILE = ".pass.json"
ANSWERS = ".answers"


@dataclass
class EraseReport:
    lines_removed: list[tuple[str, str]] = field(default_factory=list)
    lineage_rows: int = 0
    pass_entries: int = 0
    answers_deleted: list[str] = field(default_factory=list)
    evidence_deleted: list[str] = field(default_factory=list)


def _check(values: list[str]) -> list[str]:
    if not values or any(len(v.strip()) < 3 for v in values):
        raise ValueError("every value to erase must be at least 3 characters")
    return [v.strip().lower() for v in values]


def _decoded(text: str) -> str:
    """The text plus a decoded copy of any JSON in it (whole file or one value per line), so a value written with
    escapes (Zo\\u00eb, \\") is still found."""
    out = [text]
    for chunk in [text] + text.splitlines():
        try:
            out.append(json.dumps(json.loads(chunk), ensure_ascii=False))
        except ValueError:
            continue
    return "\n".join(out)


def _hit(text: str, low: list[str]) -> bool:
    t = _decoded(text).lower()
    return any(v in t for v in low)


def erase_values(stores: Path, values: list[str], evidence_dirs: list[Path] = ()) -> EraseReport:
    """Erase in place. See the module docstring."""
    stores, low, rep = Path(stores), _check(values), EraseReport()
    for p in sorted(stores.rglob("*.md")):
        rel = p.relative_to(stores)
        if any(part.startswith(".") for part in rel.parts):
            continue
        lines = p.read_text().splitlines(keepends=True)
        keep = [line for line in lines if not _hit(line, low)]
        if len(keep) != len(lines):
            rep.lines_removed += [(rel.as_posix(), line.strip()) for line in lines if _hit(line, low)]
            p.write_text("".join(keep))
    lineage = stores / LINEAGE_FILE
    if lineage.exists():
        rows = [line for line in lineage.read_text().splitlines() if line.strip()]
        keep = [line for line in rows if not _hit(line, low)]
        rep.lineage_rows = len(rows) - len(keep)
        lineage.write_text("".join(line + "\n" for line in keep))
    record_path = stores / PASS_FILE
    if record_path.exists():
        record = json.loads(record_path.read_text())
        for key in ("changes", "questions"):
            entries = record.get(key) or []
            for i, entry in enumerate(entries):
                if _hit(json.dumps(entry, ensure_ascii=False), low):
                    entries[i] = {"erased": True}
                    rep.pass_entries += 1
        if _hit(json.dumps(record, ensure_ascii=False), low):      # anything outside the entries, e.g. an error
            record = {k: v for k, v in record.items() if not _hit(json.dumps(v, ensure_ascii=False), low)}
        record_path.write_text(json.dumps(record, indent=1))
    for p in sorted((stores / ANSWERS).glob("*.md")) if (stores / ANSWERS).is_dir() else []:
        if _hit(p.read_text(), low):
            p.unlink()
            rep.answers_deleted.append(p.relative_to(stores).as_posix())
    for d in evidence_dirs:
        for p in sorted(Path(d).glob("*.md")):
            if _hit(p.read_text(), low):
                p.unlink()
                rep.evidence_deleted.append(p.name)
    return rep


def remaining(root: Path, values: list[str]) -> list[str]:
    """Relative paths of files under `root` (hidden included, .git excluded) that still contain a value."""
    root, low = Path(root), _check(values)
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and ".git" not in rel.parts and _hit(p.read_text(errors="replace"), low):
            out.append(rel.as_posix())
    return out


def raw_copies(values: list[str], roots: list[Path]) -> dict[str, list[Path]]:
    """Where raw copies of each value remain. Search only; nothing is deleted."""
    _check(values)
    out: dict[str, list[Path]] = {v: [] for v in values}
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if not p.is_file():
                continue
            text = p.read_text(errors="ignore").lower()
            for v in values:
                if v.lower() in text:
                    out[v].append(p)
    return out


def _filter_repo_available() -> str | None:
    found = shutil.which("git-filter-repo")
    if found:
        return found
    beside = Path(sys.executable).parent / "git-filter-repo"
    return str(beside) if beside.exists() else None


def purge_history(repo: Path, values: list[str]) -> None:
    """Rewrite every commit of `repo` so no value remains. Irreversible; callers must confirm first."""
    _check(values)
    exe = _filter_repo_available()
    if not exe:
        raise RuntimeError("git filter-repo is not installed; history was not rewritten")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for v in values:
            f.write(f"regex:(?i){re.escape(v.strip())}==>(erased)\n")
        rules = f.name
    try:
        subprocess.run([exe, "--force", "--replace-text", rules], cwd=repo, check=True, capture_output=True, text=True)
    finally:
        Path(rules).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="um.erase")
    ap.add_argument("--stores", type=Path, required=True)
    ap.add_argument("--value", action="append", required=True)
    ap.add_argument("--evidence", type=Path, action="append", default=[])
    ap.add_argument("--yes", action="store_true", help="required: erase cannot be undone")
    a = ap.parse_args(argv)
    if not a.yes:
        raise SystemExit("refusing to erase without --yes")
    rep = erase_values(a.stores, a.value, a.evidence)
    print(f"lines removed {len(rep.lines_removed)}, lineage rows {rep.lineage_rows}, pass entries {rep.pass_entries}, "
          f"answers deleted {len(rep.answers_deleted)}, evidence deleted {len(rep.evidence_deleted)}")
    left = remaining(a.stores, a.value)
    print("still present: " + (", ".join(left) if left else "nowhere"))


if __name__ == "__main__":
    main()
