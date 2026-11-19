"""Code-enforced checks on proposed changes. A model proposes; this decides.

Rules, in order, for each change:
  0. It must be well formed and aim at a line that exists exactly once (or be a real de-duplication).
  1. Every citation must name known evidence, quote text that evidence contains, and mention what
     the change asserts (one of its key tokens), so authority cannot be borrowed from an unrelated
     quote. No citations means reject, unless it removes a line that is an exact duplicate. For the
     person's answer to a question Claude asked, the quote must come from the answer, and the
     question counts toward the mention (a reply of "correct." confirms what was asked).
  2. The change's origin is the highest-ranked origin among its cited evidence.
  3. Adding a line is allowed from any origin, unless it restates a labelled attribute an existing line
     already gives another value for ("Room: X" beside "Room: Y", in any file). Such an add is an override
     of those lines, judged by rules 4 and 5, and becomes a question when blocked (code writes the
     question if the model did not).
  4. Tool output can never replace or remove a line, whatever that line's origin.
  5. A line the user stated can only be replaced or removed on the strength of something the user said.
  6. At most max(cap_floor, cap_share x lines) changes land in one pass; the rest are held.
A change that fails rule 4 or 5 becomes a question when it carries one, and is held otherwise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from um.evidence import Evidence, _squash, contains_quote, question_and_answer
from um.profile import ORIGIN_RANK, Change, Lineage, lines_of


STOP = {"the", "and", "now", "is", "are", "was", "user", "user's", "has", "have", "with", "for", "from", "this",
        "that", "its", "it's", "currently", "called", "named", "uses", "use", "lives", "works", "who", "which"}


# Notes a line may carry that assert nothing: anything in round brackets, and a date in square brackets
# ("[2026-01-05]"; the compile prompt asks for "the evidence date in brackets"). A tag such as "[stated]" is kept.
_NOTES = re.compile(r"\([^)]*\)|\[[^\]]*\d{4}-\d{2}-\d{2}[^\]]*\]")


def _words(line: str | None) -> list[str]:
    return re.findall(r"[\w][\w'-]*", _NOTES.sub(" ", line or ""))


def key_tokens(line: str | None, minus: str | None = None) -> set[str]:
    """What a line asserts, as lower-case words: its capitalised or numeric words after the first
    (names, values), or failing that its ordinary words; anything also in `minus`, anything in
    brackets and filler words are ignored. A heuristic, made for short bullet lines."""
    ws = _words((line or "").strip().lstrip("-* ").strip())
    base = {w.lower() for w in _words(minus)}
    keys = {w.lower() for i, w in enumerate(ws)
            if i > 0 and len(w) >= 3 and any(ch.isupper() or ch.isdigit() for ch in w)} - base - STOP
    return keys or ({w.lower() for w in ws if len(w) >= 3} - base - STOP)


def _change_keys(c: Change) -> set[str]:
    if c.op == "add":
        return key_tokens(c.new)
    if c.op == "replace":
        return key_tokens(c.new, minus=c.old)
    return key_tokens(c.old)


@dataclass
class Verdict:
    index: int
    decision: str        # "apply" | "reject" | "hold" | "ask"
    reason: str
    origin: str | None
    overrides: list[tuple[str, str]] | None = None   # an add that restates these (file, line) pairs


def label_value(line: str | None) -> tuple[str, str] | None:
    """('room', 'sablecrest') for '- Room: Sablecrest (noted 2026-01-01).': a short label before the first
    colon, and the value after it, lower-cased, ignoring anything in brackets. None for an unlabelled line."""
    text = _NOTES.sub(" ", (line or "").strip().lstrip("-* ").strip())
    label, sep, value = text.partition(":")
    label = " ".join(label.lower().split())
    if not sep or not label or len(label.split()) > 5:
        return None
    return label, " ".join(value.lower().split()).rstrip(".")


def _malformed(c: Change, root: Path, counts: dict[tuple[str, str], int]) -> str | None:
    if c.op not in ("add", "replace", "remove"):
        return f"unknown op {c.op!r}"
    if not isinstance(c.file, str) or not c.file or Path(c.file).is_absolute():
        return "bad file path"
    resolved = (Path(root) / c.file).resolve()
    if Path(root).resolve() not in resolved.parents:
        return "file is outside the stores folder"
    if c.op in ("add", "replace") and not (c.new or "").strip():
        return "no new line given"
    if c.op in ("replace", "remove"):
        if not (c.old or "").strip():
            return "no existing line given"
        n = counts.get((c.file, c.old.strip()), 0)
        if n == 0:
            return "target line not found"
        if n > 1 and not (c.op == "remove" and c.duplicate_of):
            return "target line is ambiguous"
    return None


def _is_real_duplicate(c: Change, counts: dict[tuple[str, str], int]) -> bool:
    d = c.duplicate_of or {}
    other = (d.get("file"), (d.get("line") or "").strip())
    if other[1] != (c.old or "").strip() or counts.get(other, 0) == 0:
        return False
    same_place = other == (c.file, c.old.strip())
    return counts[other] >= 2 if same_place else True


def review(changes: list[Change], root: Path, lineage: Lineage, evidence: dict[str, Evidence],
           cap_share: float = 0.2, cap_floor: int = 5) -> list[Verdict]:
    lines = lines_of(root)
    counts: dict[tuple[str, str], int] = {}
    for key in lines:
        counts[key] = counts.get(key, 0) + 1
    cap = max(cap_floor, int(cap_share * len(lines)))
    applied = 0
    verdicts = []

    def decide(i: int, c: Change) -> Verdict:
        problem = _malformed(c, root, counts)
        if problem:
            return Verdict(i, "reject", problem, None)
        if not c.citations:
            if c.op == "remove" and c.duplicate_of and _is_real_duplicate(c, counts):
                return Verdict(i, "apply", "exact duplicate", None)
            return Verdict(i, "reject", "no evidence cited", None)
        keys = _change_keys(c)
        for cit in c.citations:
            ev = evidence.get(cit.get("evidence"))
            if ev is None:
                return Verdict(i, "reject", f"unknown evidence {cit.get('evidence')!r}", None)
            quote = cit.get("quote") or ""
            if not contains_quote(ev, quote):
                return Verdict(i, "reject", f"quote not found in {ev.id}", None)
            qa = question_and_answer(ev)
            if qa and not (_squash(quote) and _squash(quote) in _squash(qa[1])):
                return Verdict(i, "reject", "the quote is from Claude's question, not the person's answer", None)
            said = (quote + " " + qa[0]).lower() if qa else quote.lower()
            if keys and not any(k in said for k in keys):
                return Verdict(i, "reject", "a citation does not mention what the change asserts", None)
        origin = max((evidence[cit["evidence"]].origin for cit in c.citations), key=lambda o: ORIGIN_RANK.get(o, 0))
        if c.op == "add":
            lv = label_value(c.new)
            targets = [(f, l) for f, l in dict.fromkeys(lines)
                       if lv and (o := label_value(l)) and o[0] == lv[0] and o[1] != lv[1]]
            blocked = _blocked(origin, targets)
            if blocked:
                return Verdict(i, "ask", f"{blocked} (an add restating {len(targets)} line(s))", origin, targets)
            return Verdict(i, "apply", "supported addition", origin)
        blocked = _blocked(origin, [(c.file, c.old)])
        if blocked:
            return Verdict(i, "ask" if c.question else "hold", blocked, origin)
        return Verdict(i, "apply", "supported change", origin)

    def _blocked(origin: str, targets: list[tuple[str, str]]) -> str | None:
        if not targets:
            return None
        if ORIGIN_RANK.get(origin, 0) <= ORIGIN_RANK["tool-output"]:
            return "tool output cannot override an existing line"
        if origin != "user-said" and any(lineage.origin_of(f, l) == "user-said" for f, l in targets):
            return "only something the user said can override what the user said"
        return None

    for i, c in enumerate(changes):
        v = decide(i, c)
        if v.decision == "apply":
            if applied >= cap:
                v = Verdict(i, "hold", "change cap", v.origin)
            else:
                applied += 1
        verdicts.append(v)
    return verdicts
