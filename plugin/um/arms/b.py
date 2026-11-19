"""Arm B: a compile pass proposes cited changes; code decides which land.

Differences from Arm A, all enforced in code rather than asked of the model: every change cites
evidence by exact quote; tool output can add but never override; what the user said can only be
overridden by the user; a cap on changes per pass; lineage on every line written; and contradictions
that need the person become questions, within a weekly budget. An answer is kept as evidence of
origin user-said in `.answers/` and travels with the stores.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from um.arms.common import copy_store
from um.checks import review
from um.compile import propose
from um.evidence import load_evidence
from um.llm import LLM
from um.profile import Change, Lineage, apply_each

NAME = "b"
ANSWERS = ".answers"
PASS_FILE = ".pass.json"

_STOP = {"the", "and", "now", "is", "are", "was", "user", "user's", "has", "have", "with", "for", "from", "this",
         "that", "its", "it's", "currently", "called", "named", "uses", "use", "lives", "works", "who", "which"}


def _distinct_tokens(c: Change) -> set[str]:
    """Words the new line adds, ignoring anything in brackets (history notes, dates) and filler words."""
    words = lambda s: {w.lower() for w in re.findall(r"[\w][\w'-]*", re.sub(r"\([^)]*\)", " ", s or "")) if len(w) >= 3}
    return words(c.new) - words(c.old) - _STOP


def confirms(answer: str, c: Change) -> bool:
    """A heuristic: the answer confirms the change when it names every word the change would add."""
    tokens = _distinct_tokens(c)
    low = answer.lower()
    return bool(tokens) and all(t in low for t in tokens)


def apply(src_root: Path, out_root: Path, llm: LLM, model: str, as_of: str, evidence_dir: Path | None = None,
          ask=None, budget=None, cap_floor: int | None = None) -> str:
    """`cap_floor` overrides the checks' minimum change cap per pass (None keeps the deployed default)."""
    src_root, out_root = Path(src_root), Path(out_root)
    evidence = load_evidence(evidence_dir) if evidence_dir else {}
    if (src_root / ANSWERS).is_dir():
        evidence.update(load_evidence(src_root / ANSWERS))
    record: dict = {"as_of": as_of, "changes": [], "questions": []}
    try:
        changes = propose(src_root, evidence, llm, model, as_of)
    except ValueError as e:
        copy_store(src_root, out_root)
        record.update(outcome="compile_failed", error=str(e)[:500])
        (out_root / PASS_FILE).write_text(json.dumps(record, indent=1))
        return "compile_failed"

    caps = {} if cap_floor is None else {"cap_floor": cap_floor}
    verdicts = review(changes, src_root, Lineage(src_root), evidence, **caps)
    to_apply: list[Change] = []
    origins: dict[int, str] = {}
    slot: dict[int, int] = {}      # change index -> position in to_apply
    for i, (c, v) in enumerate(zip(changes, verdicts)):
        if v.decision == "apply":
            slot[i] = len(to_apply)
            origins[len(to_apply)] = v.origin or "legacy"
            to_apply.append(c)

    new_answers: list[tuple[str, str]] = []
    resolution: dict[int, str] = {}   # for asks: what happened after the question
    for i, (c, v) in enumerate(zip(changes, verdicts)):
        if v.decision != "ask":
            continue
        question, answer = dict(c.question or {}), None
        if v.overrides and not question:
            label = c.new.strip().lstrip("-* ").split(":", 1)[0].strip()
            old = v.overrides[0][1].strip().lstrip("-* ")
            question = {"attr": label, "text": f"Your notes say \"{old}\", but a {v.origin} source says "
                                               f"\"{c.new.strip().lstrip('-* ')}\". Which is current?"}
        resolution[i] = "not confirmed"
        if ask is None:
            status = "not asked"
        elif budget is not None and not budget.allow(as_of):
            status = "over budget"
        else:
            answer = ask(question)
            status = "answered" if answer else "no answer"
            if answer:
                aid = f"a{as_of.replace('-', '')}-{len(new_answers) + 1:02d}"
                new_answers.append((aid, answer))
                cites = c.citations + [{"evidence": aid, "quote": answer}]
                # an add that restates existing lines is confirmed as a replace of each of them
                planned = ([Change("replace", f, old, c.new, cites, None, question) for f, old in v.overrides]
                           if v.overrides else [Change(c.op, c.file, c.old, c.new, cites, c.duplicate_of, c.question)])
                if confirms(answer, planned[0]):
                    slot[i] = len(to_apply)
                    for confirmed in planned:
                        origins[len(to_apply)] = "user-said"
                        to_apply.append(confirmed)
                    resolution[i] = "confirmed by the person"
        record["questions"].append({"change": i, "question": question, "status": status, "answer": answer})

    landed = apply_each(src_root, out_root, to_apply, origins, as_of)
    if new_answers:
        (out_root / ANSWERS).mkdir(exist_ok=True)
        for aid, text in new_answers:
            (out_root / ANSWERS / f"{aid}.md").write_text(f"origin: user-said\ndate: {as_of}\n\n{text.strip()}\n")
    for i, (c, v) in enumerate(zip(changes, verdicts)):
        record["changes"].append({**asdict(c), "decision": v.decision, "reason": v.reason, "origin": v.origin,
                                  "resolution": resolution.get(i), "applied": i in slot and landed[slot[i]]})
    record["outcome"] = "ok"
    (out_root / PASS_FILE).write_text(json.dumps(record, indent=1))
    return "ok"
