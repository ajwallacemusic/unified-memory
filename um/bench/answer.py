"""Three ways to answer a benchmark question: from a memory store, from the full history in the
prompt, and from the raw session files with search. All share one answer prompt."""
from __future__ import annotations

from pathlib import Path

from um.bench.longmemeval import Item, render_session
from um.llm import LLM, Reply
from um.prompts import load_prompt
from um.tools import Toolbox

MAX_TOKENS = 4_000
STORE_SOURCE = ("your notes about them: a folder of Markdown files you can view and search with your tools. "
                "Start with the index, `MEMORY.md`")
FULL_SOURCE = "the full record of your past conversations with them, given below in date order"
FILES_SOURCE = ("the saved transcripts of your past conversations with them: one Markdown file per "
                "conversation, named by date, which you can list, view and search with your tools")


def _system(item: Item, source: str) -> str:
    return load_prompt("answer.md").format(source=source, question_date=item.question_date)


def _question(item: Item) -> str:
    return f"Question (asked on {item.question_date}): {item.question}"


def answer_from_store(item: Item, store_dir: Path, llm: LLM, model: str) -> Reply:
    return llm.run_tools(model=model, system=_system(item, STORE_SOURCE), user=_question(item),
                         tools=Toolbox(store_dir, writable=False), max_turns=12, max_tokens=MAX_TOKENS,
                         label="answer:store")


def answer_full_context(item: Item, llm: LLM, model: str) -> Reply:
    history = "\n---\n\n".join(render_session(s) for s in item.sessions)
    user = f"Past conversations:\n\n{history}\n---\n\n{_question(item)}"
    return llm.complete(model=model, system=_system(item, FULL_SOURCE), user=user, max_tokens=MAX_TOKENS,
                        label="answer:full")


def answer_files_agent(item: Item, sessions_dir: Path, llm: LLM, model: str) -> Reply:
    return llm.run_tools(model=model, system=_system(item, FILES_SOURCE), user=_question(item),
                         tools=Toolbox(sessions_dir, writable=False), max_turns=25, max_tokens=MAX_TOKENS,
                         label="answer:files")
