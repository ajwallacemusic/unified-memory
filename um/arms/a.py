"""Arm A: our own whole-store clean-up pass over every store, with no origin or authority rules
(those are Arm B)."""
from pathlib import Path

from um.arms.common import run_pass
from um.llm import LLM
from um.prompts import load_prompt

NAME = "a"


def apply(src_root: Path, out_root: Path, llm: LLM, model: str, as_of: str, evidence_dir=None, ask=None, budget=None) -> str:
    system = load_prompt("arm_a.md").replace("{as_of}", as_of)
    if evidence_dir is None:
        user = "Run the clean-up pass now."
    else:
        user = ("Run the clean-up pass now. The notes are in `stores/`. The conversations since the last pass are in "
                "`evidence/`: read them, but change only files under `stores/`.")
    return run_pass(src_root, out_root, llm, model, system, user, label="arm:a", evidence_dir=evidence_dir)
