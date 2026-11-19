"""Label each profile line with a policy category, using a small model, cached by line hash.

The label is advisory: `um.bridge.policy.decide_line` blocks number and secret patterns whatever it says,
and any label outside the policy becomes "other" (kept local, asked about once).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from um.bridge.policy import DEFAULT_POLICY
from um.llm import LLM
from um.prompts import load_prompt

DEFINITIONS = {
    "identity-work-projects-preferences": "who the person is, where they work and their role, their own projects, tastes and preferences",
    "training-lifts": "training plans, lifts, competition results and gym routines",
    "body-weight-nutrition": "body weight, body composition, calories, diet and nutrition",
    "budgeting-setup": "how they budget: tools, rules, categories and goals, without amounts they hold, earn, owe or spent",
    "financial-figures": "balances, transactions, income, debts, net worth or any amount of their money",
    "account-ids-credentials": "account, card or government ID numbers, passwords, keys and tokens",
    "medical": "diagnoses, conditions, symptoms, medications and treatment",
    "employer-client-knowledge": "an employer's or client's internal systems, code, data or plans",
}
BATCH = 60


def _h(line: str) -> str:
    return hashlib.sha1(line.encode()).hexdigest()


def _system() -> str:
    cats = "\n".join(f"- {k}: {v}" for k, v in DEFINITIONS.items()) + "\n- other: none of the above"
    return load_prompt("categorize.md").replace("{categories}", cats)


def categorize(lines: list[str], llm: LLM, model: str, cache: Path) -> dict[str, str]:
    """{sha1(line): category} for every line; lines already in the cache are never sent again."""
    cache = Path(cache)
    known: dict[str, str] = json.loads(cache.read_text()) if cache.exists() else {}
    todo = list(dict.fromkeys(line for line in lines if _h(line) not in known))
    allowed = set(DEFAULT_POLICY) | {"other"}
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        user = "\n".join(f"{n}. {line}" for n, line in enumerate(batch))
        reply = llm.complete(model=model, system=_system(), user=user, max_tokens=4_000, label="categorize")
        try:
            data = json.loads(reply.text.strip())
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        for n, line in enumerate(batch):
            label = data.get(str(n))
            known[_h(line)] = label if label in allowed else "other"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(known, indent=1, sort_keys=True))
    return {_h(line): known[_h(line)] for line in lines}
