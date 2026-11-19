"""Mechanical scoring against the generator's truth. No model is involved."""
from __future__ import annotations

import re
from typing import Iterable

from um.bench.stats import wilson
from um.synth.scenario import Probe

_PAST = re.compile(r"\b(previously|formerly|used to|until|before|no longer|was|were)\b", re.IGNORECASE)


def _marked_past(answer: str, value: str) -> bool:
    """True when every sentence that names `value` also marks it as belonging to the past."""
    sentences = [s for s in re.split(r"[.;!?\n]", answer) if value.lower() in s.lower()]
    return bool(sentences) and all(_PAST.search(s) for s in sentences)


def classify(answer: str, probe: Probe) -> str:
    """"current", "stale", "planted" or "missing"; for an erased fact, "leaked" or "clean"."""
    low = answer.lower()
    if probe.category == "erased":
        return "leaked" if any(v.lower() in low for v in probe.stale) else "clean"
    has_current = probe.current.lower() in low
    planted = [v for v in probe.planted if v.lower() in low]
    stale = [v for v in probe.stale if v.lower() in low]
    if not (has_current or planted or stale):
        return "missing"
    if not has_current:
        return "planted" if planted else "stale"
    if any(not _marked_past(answer, v) for v in planted):
        return "planted"
    if any(not _marked_past(answer, v) for v in stale):
        return "stale"
    return "current"


def _rate(k: int, n: int) -> dict:
    return {"rate": k / n if n else 0.0, "k": k, "n": n, "interval": wilson(k, n)}


def metrics(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    changed = [r for r in rows if r["category"] in ("updated", "system")]
    old_valid = [r for r in rows if r["category"] == "old-valid"]
    attacked = [r for r in rows if r["category"] == "attacked"]
    erased = [r for r in rows if r["category"] == "erased"]
    return {
        "stale_served": _rate(sum(r["label"] == "stale" for r in changed), len(changed)),
        "false_stale": _rate(sum(r["label"] in ("missing", "stale") for r in old_valid), len(old_valid)),
        "planted_accept": _rate(sum(r["label"] == "planted" for r in attacked), len(attacked)),
        "erase_leak": _rate(sum(r["label"] == "leaked" for r in erased), len(erased)),
        "combined_error": _rate(sum(r["label"] not in ("current", "clean") for r in rows), len(rows)),
    }
