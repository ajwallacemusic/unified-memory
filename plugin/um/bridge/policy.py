"""Category policy: which profile lines may be pushed to account memory, kept local, or never stored.

The category is a model's label, so code also blocks number and secret patterns whatever the label.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STATES = ("push", "local", "never")

DEFAULT_POLICY: dict[str, str] = {  # conservative defaults; a profile's policy.json overrides any of them
    "identity-work-projects-preferences": "push",
    "training-lifts": "local",
    "body-weight-nutrition": "local",
    "budgeting-setup": "local",
    "financial-figures": "never",                        # a connector has the live value
    "account-ids-credentials": "never",
    "medical": "never",
    "employer-client-knowledge": "local",                # never pushed
}

ASK = "category not in policy: ask once"

_DIGIT_RUN = re.compile(r"\d(?:[ .-]?\d)*")
_NINE = re.compile(r"(?<!\d)\d{3}[ .-]?\d{2}[ .-]?\d{4}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
_ACCOUNT = re.compile(r"\b(?:account|acct|routing|iban|sort code)\b\D{0,20}\d{6,}", re.IGNORECASE)
_SECRETS = (
    ("credential", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("credential", re.compile(r"\bghp_[A-Za-z0-9]{30,}")),
    ("credential", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("credential", re.compile(r"\bpassword\s*(?:is\b|:)", re.IGNORECASE)),
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def blocked_pattern(line: str) -> str | None:
    """The name of the first never-store pattern the line contains, or None."""
    for m in _DIGIT_RUN.finditer(line):
        digits = re.sub(r"\D", "", m.group(0))
        for size in range(13, 20):
            if any(_luhn(digits[i:i + size]) for i in range(0, len(digits) - size + 1)):
                return "card-number"
    if _NINE.search(line):
        return "national-id"
    if _IBAN.search(line) or _ACCOUNT.search(line):
        return "bank-account"
    for name, rx in _SECRETS:
        if rx.search(line):
            return name
    return None


def load_policy(path: Path) -> dict[str, str]:
    policy = dict(DEFAULT_POLICY)
    path = Path(path)
    if path.exists():
        for cat, state in json.loads(path.read_text()).items():
            if state not in STATES:
                raise ValueError(f"policy state for {cat!r} must be one of {STATES}, not {state!r}")
            policy[cat] = state
    return policy


def decide_line(line: str, category: str | None, policy: dict[str, str]) -> tuple[str, str]:
    """(state, reason) for one profile line."""
    hit = blocked_pattern(line)
    if hit:
        return "never", f"matches the {hit} pattern"
    if category not in policy:
        return "local", ASK
    return policy[category], f"category {category}"
