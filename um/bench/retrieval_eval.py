"""Offline check of the profile-context hook's retriever on the recall bench: no model, seconds per run.

    .venv/bin/python -m um.bench.retrieval_eval [bench/recall] [dev|test]

recall: share of questions whose injected text contains an answer term (an upper bound on what the hook can
add to a session's answer). offtopic_injection_rate: share of off-topic prompts given any profile line.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from um.bench.recall_data import load_offtopic, load_questions
from um.hooks.profile_context import relevant_lines, render


def _inject(retriever, profile: Path, prompt: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    pairs = retriever(profile, prompt)
    text = render(pairs) if pairs else ""
    return text, (time.perf_counter() - t0) * 1000


def evaluate(root: Path, retriever=relevant_lines, split: str = "dev") -> dict:
    root = Path(root)
    profile = root / "profile"
    qs = load_questions(root, split)
    hits, kinds, chars, ms, misses = 0, {}, [], [], []
    for q in qs:
        text, t = _inject(retriever, profile, q["question"])
        ok = any(term.lower() in text.lower() for term in q["answer_terms"])
        hits += ok
        kinds.setdefault(q["kind"], []).append(ok)
        chars.append(len(text))
        ms.append(t)
        if not ok:
            misses.append(q["id"])
    off = [o for o in load_offtopic(root) if o.get("split", split) == split]
    injected = []
    for o in off:
        text, t = _inject(retriever, profile, o["prompt"])
        ms.append(t)
        if text:
            injected.append(o["id"])
    ms.sort()
    return {"split": split, "n": len(qs), "recall": hits / len(qs) if qs else 0.0,
            "by_kind": {k: sum(v) / len(v) for k, v in sorted(kinds.items())}, "misses": misses,
            "offtopic_n": len(off), "offtopic_injection_rate": len(injected) / len(off) if off else 0.0,
            "offtopic_injected": injected, "mean_chars": statistics.mean(chars) if chars else 0.0,
            "p95_ms": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else 0.0}


if __name__ == "__main__":
    args = sys.argv[1:]
    print(json.dumps(evaluate(Path(args[0]) if args else Path("bench/recall"), split=args[1] if len(args) > 1 else "dev"),
                     indent=1))
