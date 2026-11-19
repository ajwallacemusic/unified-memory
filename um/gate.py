"""Gate for routing work to the Claude subscription: open only while plan usage is under a ceiling.

The usage figures come from a file the Claude desktop app keeps. Its meaning is inferred, not
documented: each sample is {t: epoch ms, org, u: {fh, sd, xu}}, read here as the five-hour and
seven-day usage percentages. Anything unreadable, missing or stale means the gate is closed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

PLAN_USAGE_PATH = Path.home() / "Library/Application Support/Claude/plan-usage-history.json"


class UsageGate:
    def __init__(self, ceiling_pct: float = 70.0, max_age_s: int = 900, path: Path = PLAN_USAGE_PATH):
        self.ceiling_pct = ceiling_pct
        self.max_age_s = max_age_s
        self.path = Path(path)

    def latest(self) -> dict | None:
        """Newest sample as {"fh", "sd", "age_s"}, or None when there is nothing usable."""
        try:
            samples = json.loads(self.path.read_text())["samples"]
            newest = max(samples, key=lambda s: s["t"])
            return {
                "fh": float(newest["u"]["fh"]),
                "sd": float(newest["u"]["sd"]),
                "age_s": time.time() - newest["t"] / 1000,
            }
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def is_open(self) -> bool:
        s = self.latest()
        if s is None or s["age_s"] > self.max_age_s:
            return False
        return s["fh"] < self.ceiling_pct and s["sd"] < self.ceiling_pct
