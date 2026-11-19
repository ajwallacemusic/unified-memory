"""A budget for questions to the user: at most `per_week` per ISO week."""
from __future__ import annotations

from datetime import date


class QuestionBudget:
    def __init__(self, per_week: int = 3):
        self.per_week = per_week
        self.asked: list[dict] = []
        self._count: dict[tuple[int, int], int] = {}

    def allow(self, day: str) -> bool:
        """True, and the question is counted, when this ISO week still has room."""
        year, week, _ = date.fromisoformat(day).isocalendar()
        n = self._count.get((year, week), 0)
        if n >= self.per_week:
            return False
        self._count[(year, week)] = n + 1
        return True

    def total(self) -> int:
        """Every question allowed so far, across all weeks."""
        return sum(self._count.values())
