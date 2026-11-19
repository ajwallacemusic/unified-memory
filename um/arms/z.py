"""Arm Z: do nothing. The stores are used as the writer left them."""
from pathlib import Path

from um.arms.common import copy_store
from um.llm import LLM

NAME = "z"


def apply(src_root: Path, out_root: Path, llm: LLM, model: str, as_of: str, evidence_dir=None, ask=None, budget=None) -> str:
    copy_store(src_root, out_root)
    return "ok"
