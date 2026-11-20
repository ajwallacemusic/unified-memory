"""Stands in for the person when Arm B asks a question.

Modes:
  always  answers at once with the value true that day (the replay oracle)
  never   never answers
  late    answers `delay_days` later, with the value true on the day the answer arrives
  flaky   answers at once with probability `p`, decided by a coin derived from the question, so reruns agree
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

from um.synth.scenario import PHRASE, Scenario, truth

MODES = ("always", "never", "late", "flaky")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", " ", (s or "").lower().replace("_", " ")).strip()


class Oracle:
    def __init__(self, scn: Scenario, mode: str = "always", seed: int = 0, p: float = 0.5, delay_days: int = 7):
        if mode not in MODES:
            raise ValueError(f"unknown oracle mode {mode!r}")
        self.scn, self.mode, self.seed, self.p, self.delay = scn, mode, seed, p, delay_days
        self.attrs = sorted({f.attr for f in scn.facts})
        self._queue: list[tuple[str, str]] = []      # (due ISO date, attr)

    def _place(self, question: dict) -> str | None:
        key = _norm(question.get("attr", ""))
        hit = next((a for a in self.attrs if key and key in (_norm(a), _norm(PHRASE[a]))), None)
        if hit is None:
            hay = _norm(f"{question.get('attr', '')} {question.get('text', '')}")
            found = [a for a in self.attrs if _norm(PHRASE[a]) in hay or _norm(a) in hay]
            hit = max(found, key=lambda a: len(PHRASE[a]), default=None)
        return hit

    def _say(self, attr: str, day: date) -> str:
        return f"My {PHRASE[attr]} is {truth(self.scn, attr, day)}."

    def ask(self, question: dict, day: date) -> str | None:
        attr = self._place(question)
        if attr is None or self.mode == "never":
            return None
        if self.mode == "always":
            return self._say(attr, day)
        if self.mode == "flaky":
            h = hashlib.sha256(f"{self.scn.user}|{attr}|{day.isoformat()}|{self.seed}".encode()).digest()
            return self._say(attr, day) if int.from_bytes(h[:8], "big") / 2 ** 64 < self.p else None
        due = (day + timedelta(days=self.delay)).isoformat()
        if not any(a == attr for _, a in self._queue):
            self._queue.append((due, attr))
        return None

    def due(self, day: date) -> list[tuple[str, str]]:
        """Late answers whose time has come, as (answer id, text); each is returned once."""
        ready = [(d, a) for d, a in self._queue if d <= day.isoformat()]
        self._queue = [(d, a) for d, a in self._queue if d > day.isoformat()]
        stamp = day.isoformat().replace("-", "")
        return [(f"late{stamp}-{n:02d}", self._say(a, day)) for n, (_, a) in enumerate(ready, 1)]

    def state(self) -> list:
        return [list(x) for x in self._queue]

    def restore(self, state: list) -> None:
        self._queue = [(d, a) for d, a in state]
