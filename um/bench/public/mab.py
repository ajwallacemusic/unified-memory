"""MemoryAgentBench (Hu et al., 2025; huggingface.co/datasets/ai-hyz/MemoryAgentBench and
github.com/HUST-AI-HYZ/MemoryAgentBench, MIT), Conflict_Resolution split, FactConsolidation single-hop.

Each source is one numbered list of facts (a later, higher-numbered fact overrides an earlier one about the same
thing) and 100 questions on it. Reproduced from the code at commit 538026089d1a (fetched 2026-11-19):
- the long-context agent's system message and query template (utils/templates.py, 'factconsolidation');
- the metric the paper reports for this task, `substring_exact_match`, taken as the better of the raw and the
  parsed output (utils/eval_other_utils.py: normalize_answer, parse_output, default_post_process).
Differences, stated in the results: the context goes in the system prompt instead of a memorise turn, and the
answer may use 1,000 output tokens instead of the config's 10 (Haiku 5.5 at medium effort spends output tokens
before it writes; at 32 the pilot's answers were empty). Substring match on a longer answer is more lenient.

`last_write` is the frozen "newest statement wins" rule: score every fact by how many of the question's content
words it shares (lower-cased, crude plural/tense stemming, a short stop list), keep the best-scoring facts, and
take the one with the highest serial number. Its single fact is the whole context for the answer model.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from um.bench.public.pipeline import Session

SOURCES = ("factconsolidation_sh_6k", "factconsolidation_sh_32k", "factconsolidation_sh_64k", "factconsolidation_sh_262k")
SYSTEM_MESSAGE = "You are a helpful assistant that can read the context and memorize it for future retrieval."
QUERY_TEMPLATE = (
    "Pretend you are a knowledge management system. Each fact in the knowledge pool is provided with a serial number "
    "at the beginning, and the newer fact has larger serial number. \n You need to solve the conflicts of facts in the "
    "knowledge pool by finding the newest fact with larger serial number. You need to answer a question based on this "
    "rule. You should give a very concise answer without saying other words for the question **only** from the "
    "knowledge pool you have memorized rather than the real facts in real world. \n\nFor example:\n\n [Knowledge Pool] "
    "\n\n Question: Based on the provided Knowledge Pool, what is the name of the current president of Russia? \n"
    "Answer: Donald Trump \n\n Now Answer the Question: Based on the provided Knowledge Pool, {question} \nAnswer:")
MEMORIZE_PREFIX = "The following context is the facts I have learned:"
MAX_TOKENS = 1_000
FIRST_DAY = date(2026, 1, 1)
_FACT = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Item:
    id: str
    question: str
    answers: list


@dataclass(frozen=True)
class Context:
    source: str
    text: str
    facts: list          # [(serial, text)]
    items: list          # [Item]


def load(path: Path, source: str) -> Context:
    for row in json.loads(Path(path).read_text()):
        if row["metadata"]["source"] == source:
            facts = [(int(m[1]), m[2]) for m in map(_FACT.match, row["context"].splitlines()) if m]
            items = [Item(qid, q, list(a[0]) if a and isinstance(a[0], list) else list(a))
                     for qid, q, a in zip(row["metadata"]["qa_pair_ids"], row["questions"], row["answers"])]
            return Context(source, row["context"], facts, items)
    raise KeyError(source)


def sessions(ctx: Context, per_session: int = 50) -> list[Session]:
    """The facts in serial order, `per_session` to a user turn, one session a day."""
    out = []
    for k in range(0, len(ctx.facts), per_session):
        chunk = ctx.facts[k:k + per_session]
        text = MEMORIZE_PREFIX + "\n" + "\n".join(f"{n}. {t}" for n, t in chunk)
        out.append(Session(f"c{k // per_session:04d}", (FIRST_DAY + timedelta(days=k // per_session)).isoformat(),
                           (("user", text),)))
    return out


def query(question: str) -> str:
    return QUERY_TEMPLATE.replace("{question}", question)


# ---------------------------------------------------------------- official metric

def normalize_answer(text: str) -> str:
    text = text.lower()
    text = "".join(ch for ch in text if ch not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def parse_output(text: str, prefix: str = "Answer:") -> str | None:
    for pattern in (re.compile(f"(?:{prefix})(.*)(?:\n|$)", flags=re.IGNORECASE), re.compile(r"(?:^)(.*)(?:\n|$)")):
        m = pattern.search(text)
        if m:
            return re.sub(f"^{re.escape(prefix)}", "", m[1].strip(), flags=re.IGNORECASE).strip()
    return None


def _flat(golds) -> list[str]:
    if isinstance(golds, str):
        return [golds]
    return [g for sub in golds for g in sub] if golds and isinstance(golds[0], list) else list(golds)


def sub_em(prediction: str, golds) -> bool:
    preds = [prediction] + ([p] if (p := parse_output(prediction)) is not None else [])
    return any(normalize_answer(g) in normalize_answer(x) for x in preds for g in _flat(golds))


# ---------------------------------------------------------------- newest statement wins

_STOP = set("a an the of in on at to for by with from and or is are was were be been does do did which what who whom "
            "whose where when why how that this".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[^\W_]+", text.lower()) if w not in _STOP}


def last_write(ctx: Context, question: str) -> str:
    q = _words(question)
    scored = [(len(q & _words(t)), n, t) for n, t in ctx.facts]
    best = max((s for s, _, _ in scored), default=0)
    if best == 0:
        return ""
    _, n, t = max((x for x in scored if x[0] == best), key=lambda x: x[1])
    return f"{n}. {t}"
