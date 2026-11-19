"""Build the public repository: allowlisted tracked files only, and refuse if any private term appears.

    .venv/bin/python -m scripts.export_public ~/develop/unified-memory-public

The denylist lives at data/private/public-denylist.txt (one term per line, # comments), never in the repo.
`docs/public/README.md` becomes the export's README.md and the rest of `docs/public/` becomes `docs/`.
The export gets a fresh git history; nothing from this repository's history is carried over.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOW = ["um/", "tests/", "bench/", "plugin_src/", "plugin/", "marketplace/", "scripts/build_plugin.py", "scripts/export_public.py", "scripts/make_charts.py",
         "bridge/task-prompt.md", "results/synth/", "results/longmemeval/", "results/recall-bench/",
         "results/public-bench/", "prototype/data/test/", "experiments/blind-trial/findings_test.json", "docs/public/", "pyproject.toml", ".gitignore", "LICENSE"]
NEVER = ("data/", "docs/research/", ".um/", ".superpowers/", "um/realdata.py", "um/private_check.py",
         "plugin/um/realdata.py", "plugin/um/private_check.py",
         "tests/test_realdata.py", "tests/test_private_check.py")


class ExportError(Exception):
    pass


def _unescape(line: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), line)


def find_terms(text: str, terms: list[str]) -> list[tuple[int, str]]:
    pats = [(t, re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)) for t in terms if t.strip()]
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        line = _unescape(line)
        hits += [(n, t) for t, p in pats if p.search(line)]
    return hits


def _target(rel: str) -> str:
    if rel == "marketplace/marketplace.json":
        return ".claude-plugin/marketplace.json"
    if rel == "docs/public/README.md":
        return "README.md"
    return "docs/" + rel[len("docs/public/"):] if rel.startswith("docs/public/") else rel


def export(src: Path, dst: Path, allow: list[str] = ALLOW, deny_terms: list[str] = (), exempt=frozenset()) -> list[str]:
    src, dst = Path(src), Path(dst)
    tracked = subprocess.run(["git", "-C", str(src), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    ignored = set(subprocess.run(["git", "-C", str(src), "ls-files", "-ci", "--exclude-standard"],  # a fresh repo would drop these
                                 capture_output=True, text=True, check=True).stdout.split())
    chosen = [r for r in tracked if r not in ignored and any(r == a or (a.endswith("/") and r.startswith(a)) for a in allow)
              and not any(r == x or (x.endswith("/") and r.startswith(x)) for x in NEVER)]
    problems = []
    for rel in chosen:
        text = (src / rel).read_bytes().decode("utf-8", errors="replace")
        problems += [f"{rel}:{n}: {t}" for n, t in find_terms(text, list(deny_terms))
                     if (rel, t.lower()) not in exempt]
        problems += [f"{rel}: path: {t}" for _, t in find_terms(rel, list(deny_terms))]
    if problems:
        raise ExportError(f"{len(problems)} private term(s) found:\n" + "\n".join(problems[:200]))
    tmp = Path(tempfile.mkdtemp(prefix="um-export-"))
    out = []
    for rel in chosen:
        t = _target(rel)
        (tmp / t).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, tmp / t)
        out.append(t)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(tmp), str(dst))
    return sorted(out)


def denylist(path: Path) -> tuple[list[str], set[tuple[str, str]]]:
    """Terms, plus reviewed exemptions written as `!path:term` (a harmless hit in one named file)."""
    lines = [x.strip() for x in Path(path).read_text().splitlines() if x.strip() and not x.lstrip().startswith("#")]
    exempt = {tuple(x[1:].rsplit(":", 1)) for x in lines if x.startswith("!")}
    return [x for x in lines if not x.startswith("!")], {(f, t.lower()) for f, t in exempt}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    dst = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/develop/unified-memory-public").expanduser()
    try:
        terms, exempt = denylist(root / "data" / "private" / "public-denylist.txt")
        files = export(root, dst, deny_terms=terms, exempt=exempt)
    except ExportError as e:
        sys.exit(str(e))
    print(f"exported {len(files)} files to {dst}")
