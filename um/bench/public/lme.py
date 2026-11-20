"""LongMemEval-S (Wu et al., 2024; MIT) for the public-benchmark harness: knowledge-update, single-session-user and
single-session-preference questions. Answers use the earlier runs' answer prompt (um/prompts/answer.md) and are
graded with the earlier runs' judge (um/bench/judge.py: LongMemEval's own per-type prompts), answered by Claude
Haiku 5.5. That is not LongMemEval's official GPT-4o judge."""
from __future__ import annotations

from um.bench.judge import JUDGE_MAX_TOKENS, judge_prompt, verdict_of
from um.bench.longmemeval import Item, parse_date
from um.bench.public.pipeline import Session
from um.llm import LLM
from um.prompts import load_prompt

TYPES = ("knowledge-update", "single-session-user", "single-session-preference")
MAX_TOKENS = 4_000
SOURCES = {
    "none": "only what is in this message; no record of your past conversations with them is available",
    "full-history": "the full record of your past conversations with them, given below in date order",
    "raw-retrieval": "excerpts from your past conversations with them, found by a search on the question and given below",
    "profile-full": "the profile you keep about them, given below",
    "profile-hook": "the lines of the profile you keep about them that matched this question, given below",
    "search": "a search tool over your past conversations with them",
    "profile+search": ("the profile you keep about them, given below, and a search tool over your past conversations "
                       "with them"),
}


def counts_for(n: int, available: dict[str, int] | None = None) -> dict[str, int]:
    """Dealt round-robin over the three types, so the split is even, never more than a type has; what a type
    cannot supply goes to the others."""
    avail = {t: (available or {}).get(t, n) for t in TYPES}
    counts = {t: 0 for t in TYPES}
    left = n
    while left > 0 and any(counts[t] < avail[t] for t in TYPES):
        for t in TYPES:
            if left and counts[t] < avail[t]:
                counts[t] += 1
                left -= 1
    return counts


def sessions(item: Item) -> list[Session]:
    return [Session(s.id, parse_date(s.date).date().isoformat(), tuple((t.role, t.content) for t in s.turns))
            for s in item.sessions]


def instructions(item: Item, condition: str) -> str:
    return load_prompt("answer.md").format(source=SOURCES[condition], question_date=item.question_date)


def question_text(item: Item) -> str:
    return f"Question (asked on {item.question_date}): {item.question}"


def grade(item: Item, response: str, llm: LLM, model: str) -> dict:
    reply = llm.complete(model=model, system="", user=judge_prompt(item, response), max_tokens=JUDGE_MAX_TOKENS,
                         label="judge:longmemeval")
    return {"correct": verdict_of(reply.text), "judge": reply.text.strip()[:20].lower()}
