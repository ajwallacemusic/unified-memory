"""Grade an answer with LongMemEval's own per-type prompts (see um/prompts/judge/README.md)."""
from __future__ import annotations

import re

from um.bench.longmemeval import Item
from um.llm import LLM
from um.prompts import load_prompt

_BY_TYPE = {
    "temporal-reasoning": "temporal-reasoning",
    "knowledge-update": "knowledge-update",
    "single-session-preference": "single-session-preference",
    "abstention": "abstention",
}


def judge_prompt(item: Item, response: str) -> str:
    template = load_prompt(f"judge/{_BY_TYPE.get(item.qtype, 'default')}.md")
    # Plain replacement, not str.format: answers and responses may contain braces.
    return (template.replace("{question}", item.question)
            .replace("{answer}", item.answer)
            .replace("{response}", response))


JUDGE_MAX_TOKENS = 1_000


def verdict_of(text: str) -> bool | None:
    """True for yes, False for no, None when the judge said neither."""
    m = re.match(r"\s*(yes|no)\b", text, re.IGNORECASE)
    return None if m is None else m.group(1).lower() == "yes"


def judge(item: Item, response: str, llm: LLM, model: str) -> bool:
    reply = llm.complete(model=model, system="", user=judge_prompt(item, response), max_tokens=JUDGE_MAX_TOKENS,
                         label="judge")
    return bool(verdict_of(reply.text))
