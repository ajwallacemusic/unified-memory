"""Shared mechanics for arms that rewrite stores with a tool loop: copy first, run one pass, keep the
result only if it is still a complete set of stores. The source is never written to."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from um.llm import LLM, outcome_of
from um.tools import Toolbox

MAX_TURNS = 40
MAX_TOKENS = 16_000


def copy_store(src_store: Path, out_store: Path) -> None:
    if Path(out_store).exists():
        shutil.rmtree(out_store)
    shutil.copytree(src_store, out_store)


def _visible(root: Path) -> list[Path]:
    root = Path(root)
    return [p for p in root.rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(root).parts)]


def wrecked(src_root: Path, out_root: Path) -> bool:
    """True when an index the source had is gone, or the stores lost more than half their bytes."""
    src_root, out_root = Path(src_root), Path(out_root)
    for p in _visible(src_root):
        if p.name == "MEMORY.md" and not (out_root / p.relative_to(src_root)).exists():
            return True
    return sum(p.stat().st_size for p in _visible(out_root)) < sum(p.stat().st_size for p in _visible(src_root)) / 2


def run_pass(src_root: Path, out_root: Path, llm: LLM, model: str, system: str, user: str, label: str,
             scope: str = "", evidence_dir: Path | None = None) -> str:
    """One tool-loop pass. `scope` limits the tools to a subfolder. With `evidence_dir`, the tools see a
    working folder holding `stores/` (the copy being edited) and `evidence/`; only `stores/` is kept."""
    copy_store(src_root, out_root)
    work = None
    if evidence_dir is not None:
        work = Path(tempfile.mkdtemp(prefix="um-arm-"))
        shutil.copytree(out_root, work / "stores")
        shutil.copytree(evidence_dir, work / "evidence")
        box = work
    else:
        box = Path(out_root) / scope if scope else Path(out_root)
    try:
        reply = llm.run_tools(model=model, system=system, user=user, tools=Toolbox(box, writable=True),
                              max_turns=MAX_TURNS, max_tokens=MAX_TOKENS, label=label)
        if work is not None:
            copy_store(work / "stores", out_root)
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    if wrecked(src_root, out_root):
        copy_store(src_root, out_root)
        return "arm_failed"
    return outcome_of(reply)
