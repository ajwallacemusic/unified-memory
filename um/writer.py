"""The shared, deliberately plain memory writer.

It turns a dated chat history into a memory store, a few sessions at a time, standing in for how an
assistant writes memory during conversations today. Every arm starts from the store it produces.
It has no origin fields and no conflict rules; those belong to the arms being compared.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from um.bench.longmemeval import Session, render_session
from um.llm import LLM, outcome_of
from um.prompts import load_prompt
from um.tools import Toolbox

MAX_TURNS = 16
MAX_TOKENS = 8_000


def _estimate_tokens(session: Session) -> int:
    return sum(len(t.content) for t in session.turns) // 4


def chunk_sessions(sessions: Sequence[Session], chunk_tokens: int) -> list[list[Session]]:
    """Consecutive sessions grouped so each group is at most `chunk_tokens`; a session larger than
    the limit is a group on its own."""
    chunks: list[list[Session]] = []
    current: list[Session] = []
    size = 0
    for s in sessions:
        n = _estimate_tokens(s)
        if current and size + n > chunk_tokens:
            chunks.append(current)
            current, size = [], 0
        current.append(s)
        size += n
    if current:
        chunks.append(current)
    return chunks


def write_memory(sessions: Sequence[Session], store_dir: Path, llm: LLM, model: str,
                 chunk_tokens: int = 20_000, prompt: str = "writer.md") -> list[str]:
    system = load_prompt(prompt)
    tools = Toolbox(store_dir, writable=True)
    outcomes = []
    for chunk in chunk_sessions(sessions, chunk_tokens):
        user = (
            f"Here are the conversations since you last updated the notes ({len(chunk)} in this batch). "
            "Update the notes.\n\n" + "\n---\n\n".join(render_session(s) for s in chunk)
        )
        reply = llm.run_tools(model=model, system=system, user=user, tools=tools, max_turns=MAX_TURNS,
                              max_tokens=MAX_TOKENS, label="writer")
        outcomes.append(outcome_of(reply))
    return outcomes
