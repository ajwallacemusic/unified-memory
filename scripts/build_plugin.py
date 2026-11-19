"""Build the local plugin folder from plugin_src/ plus the parts of `um` the plugin runs.

    .venv/bin/python -m scripts.build_plugin            # writes ./plugin

Nothing private and nothing benchmark-only is copied. The result is for local use (`claude --plugin-dir ./plugin`);
it is not published anywhere.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SKIP_DIRS = {"synth", "bench", "recall", "__pycache__"}
SKIP_FILES = {"private_check.py", "fixture_score.py", "realdata.py"}


def build_plugin(root: Path, out: Path) -> list[str]:
    root, out = Path(root), Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root / "plugin_src", out)
    for p in sorted((root / "um").rglob("*")):
        rel = p.relative_to(root / "um")
        if not p.is_file() or set(rel.parts) & SKIP_DIRS or p.name in SKIP_FILES or p.suffix == ".pyc":
            continue
        target = out / "um" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    (out / "bridge").mkdir(exist_ok=True)
    shutil.copy2(root / "bridge" / "task-prompt.md", out / "bridge" / "task-prompt.md")
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1]
    files = build_plugin(here, Path(sys.argv[1]) if len(sys.argv) > 1 else here / "plugin")
    print(f"built {len(files)} files")
