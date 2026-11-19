"""Arm A0: the shipped clean-up, automated.

Runs the body of Anthropic's `consolidate-memory` skill as the instruction. The text is read from
the local Claude install at run time and is not copied into this repository. The skill expects its
host to say where the memory folder is, so one short harness note is added for that.
"""
from __future__ import annotations

import glob
from pathlib import Path

from um.arms.common import run_pass
from um.llm import LLM

NAME = "a0"

_PATTERN = str(Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin"
               / "*/*/skills/consolidate-memory/SKILL.md")
_found = sorted(glob.glob(_PATTERN))
CONSOLIDATE_SKILL_PATH = Path(_found[-1]) if _found else Path(_PATTERN)

HARNESS_NOTE = (
    "\n\n---\nHarness note: the memory directory is the folder your file tools operate on, and its index "
    "is `MEMORY.md`. Topic files are Markdown. Today's date is {as_of}."
)


def skill_body(path: Path) -> str:
    if not Path(path).is_file():
        raise FileNotFoundError(f"consolidate-memory skill not found at {path}")
    text = Path(path).read_text()
    if text.startswith("---"):
        _, _, rest = text.partition("\n---")
        text = rest.partition("\n")[2] if rest else text
    return text.strip()


def apply(src_root: Path, out_root: Path, llm: LLM, model: str, as_of: str, evidence_dir=None, ask=None, budget=None) -> str:
    """The shipped skill works on one memory folder: `memory/` inside the root when there is one,
    otherwise the root itself. It is not given the evidence."""
    system = skill_body(CONSOLIDATE_SKILL_PATH) + HARNESS_NOTE.format(as_of=as_of)
    scope = "memory" if (Path(src_root) / "memory").is_dir() else ""
    return run_pass(src_root, out_root, llm, model, system, "Run the memory consolidation now.", label="arm:a0", scope=scope)
