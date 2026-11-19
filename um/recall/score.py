"""Score the cross-surface recall test: the share of probes where a surface did not know a fact
that was stated on a different surface."""
from __future__ import annotations

from typing import Iterable


def miss_rate(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    if not rows:
        raise ValueError("no probe rows")
    by_pair: dict[tuple[str, str], list[bool]] = {}
    for r in rows:
        if r["stated_on"] == r["probed_on"]:
            raise ValueError(f"canary {r['canary_id']} was probed on the surface where it was stated")
        by_pair.setdefault((r["stated_on"], r["probed_on"]), []).append(bool(r["hit"]))
    misses = sum(1 for r in rows if not r["hit"])
    return {
        "overall": misses / len(rows),
        "probes": len(rows),
        "pairs": {pair: 1 - sum(hits) / len(hits) for pair, hits in sorted(by_pair.items())},
    }
