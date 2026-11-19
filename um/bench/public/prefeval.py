"""PrefEval (Zhao et al., ICLR 2025; github.com/amazon-science/PrefEval, CC BY-NC 4.0), explicit preferences,
generation task. Data and judge prompts are read at run time from the cloned repository (data/public/prefeval);
none of its text is copied into this repository.

Reproduced from the repository (generation_task/benchmark_generation.py, utils/explicit_utils.py,
utils/common_utils.py, generation_task/llm_based_evaluation_errortypes.py,
generation_task/get_preference_following_accuracy_generation_task.py, fetched 2026-11-19):
- The conversation: the preference as the first user turn, the answer model's own reply to it, then the first N
  exchanges of `filtered_inter_turns.json` (all conversations concatenated), then the question with
  " (Please respond within 300 words.)" appended. System prompt "You are a helpful assistant.", 300 output tokens.
- Four judge checks with the files in `error_type/`, the judge system prompt below and 100 output tokens:
  acknowledge (also extracts the restated preference), violate, hallucinate (on that restatement), helpful.
- Preference-following accuracy exactly as `analyze_errors` computes it, substring tests included.

Differences, stated in the results: the judge is Claude Haiku 5.5, not Claude 3 Sonnet, and runs without a
temperature setting; the history is given to the answer model as a transcript in the system prompt (every
condition here passes its context that way), not as prior chat messages; the answer may use 1,000 output tokens
and each judge check 1,000 (PrefEval: 300 and 100), because Haiku 5.5 at medium effort spends part of its output
budget before it writes, and the pilot's first answers at 300 were all cut off. The question still asks for at
most 300 words, and the reply to the preference keeps PrefEval's 300.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from um.bench.public.pipeline import Session
from um.llm import LLM, Reply

SYSTEM_PROMPT = "You are a helpful assistant."          # config.yaml system_prompt
MAX_GEN_TOKENS = 300                                    # config.yaml max_gen_tokens
ANSWER_MAX_TOKENS = 1_000
JUDGE_SYSTEM = ("You are a helpful assistant in evaluating an AI assistant's reponse. You should be fair and strict "
                "and follow the user's instruction")
JUDGE_MAX_TOKENS = 1_000                                # PrefEval: 100
CHECKS = {"acknow": "check_acknowledge.txt", "violate": "check_violation.txt",
          "hallucinate": "check_hallucination.txt", "helpful": "check_helpful.txt"}
SESSION_DATE = "2026-01-01"   # PrefEval's history is one undated conversation


@dataclass(frozen=True)
class Item:
    id: str
    topic: str
    index: int
    preference: str
    question: str


def load(root: Path) -> list[Item]:
    items = []
    for f in sorted((Path(root) / "benchmark_dataset" / "explicit_preference").glob("*.json")):
        for n, row in enumerate(json.loads(f.read_text())):
            items.append(Item(f"{f.stem}:{n}", f.stem, n, row["preference"], row["question"]))
    return items


def sample(items: list[Item], n: int, seed: int) -> list[Item]:
    """The same number of items from every topic, chosen with a seeded generator."""
    topics = sorted({i.topic for i in items})
    if n % len(topics):
        raise ValueError(f"{n} items cannot be split equally over {len(topics)} topics")
    rng = random.Random(seed)
    out = []
    for t in topics:
        out += rng.sample([i for i in items if i.topic == t], n // len(topics))
    return out


def inter_turns(root: Path, n: int) -> list[tuple[str, str]]:
    convs = json.loads((Path(root) / "benchmark_dataset" / "filtered_inter_turns.json").read_text())
    msgs = [(m["role"], m["content"]) for c in convs for m in c["conversation"]][: 2 * n]
    if len(msgs) != 2 * n or msgs[-1][0] != "assistant":
        raise ValueError("the inter-turn conversations do not give that many exchanges")
    return msgs


def pref_generation(item: Item, llm: LLM, model: str) -> Reply:
    return llm.complete(model=model, system=SYSTEM_PROMPT, user=item.preference, max_tokens=MAX_GEN_TOKENS,
                        label="prefeval:pref_generation")


def sessions(item: Item, pref_reply: str, inter: list[tuple[str, str]]) -> list[Session]:
    return [Session("prefeval", SESSION_DATE, (("user", item.preference), ("assistant", pref_reply), *inter))]


def question_text(item: Item) -> str:
    return item.question + f" (Please respond within {MAX_GEN_TOKENS} words.)"


def tag(text: str, name: str) -> str:
    """The text of the first <name> element, as BeautifulSoup's html.parser gives it: tag names are matched
    without regard to case, and an element that is never closed runs to the end of the text."""
    m = re.search(rf"<{name}>(.*?)(?:</{name}>|\Z)", text, re.I | re.S)
    return m.group(1).strip() if m else ""


def _prompt(root: Path, check: str) -> str:
    return (Path(root) / "error_type" / CHECKS[check]).read_text()


def judge(item: Item, response: str, llm: LLM, model: str, root: Path) -> dict:
    """The four checks in PrefEval's order; returns their parsed answers and the extracted restatement."""
    out: dict = {}
    for check in CHECKS:
        text = _prompt(root, check)
        if check == "acknow":
            text = text.replace("{end_generation}", response).replace("{question}", item.question)
        elif check in ("violate", "helpful"):
            text = (text.replace("{preference}", item.preference).replace("{question}", item.question)
                    .replace("{end_generation}", response))
        else:
            text = text.replace("{preference}", item.preference).replace("{assistant_restatement}", out["extract_pref"])
        reply = llm.complete(model=model, system=JUDGE_SYSTEM, user=text, max_tokens=JUDGE_MAX_TOKENS,
                             label=f"judge:prefeval:{check}")
        out[check] = tag(reply.text, "answer")
        if check == "acknow":
            out["extract_pref"] = tag(reply.text, "preference")
    return out


def score(checks: dict) -> dict:
    """`analyze_errors` for one entry."""
    ack = "yes" in checks.get("acknow", "").lower()
    hal = ack and "yes" in checks.get("hallucinate", "").lower()
    vio = "yes" in checks.get("violate", "").lower()
    unhelpful = "no" in checks.get("helpful", "").lower()
    inconsistent = ack and not hal and vio and not unhelpful
    hal_violation = ack and hal and vio and not unhelpful
    unaware_violation = not ack and vio and not unhelpful
    return {"acknowledgement": ack, "hallucination": hal, "violation": vio, "error_unhelpful": unhelpful,
            "error_inconsistent": inconsistent, "hallucination_of_preference_violation": hal_violation,
            "preference_unaware_violation": unaware_violation,
            "preference_following": not any([inconsistent, hal_violation, unaware_violation, unhelpful])}
