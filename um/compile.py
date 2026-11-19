"""The compile pass: ask a model for a list of cited changes to the stores. Code decides which land
(see um.checks). This module only builds the request and parses the reply."""
from __future__ import annotations

import json
import re

from um.profile import Change

_FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
_OPS = ("add", "replace", "remove")


def parse_changes(text: str) -> list[Change]:
    """Parse a JSON array of change objects, bare or inside exactly one fenced block."""
    blocks = _FENCE.findall(text)
    if len(blocks) > 1:
        raise ValueError("more than one fenced block in the reply")
    raw = blocks[0] if blocks else text
    try:
        data = json.loads(raw.strip())
    except ValueError as e:
        raise ValueError(f"reply is not JSON: {e}") from e
    if not isinstance(data, list):
        raise ValueError("reply is not a JSON array")
    changes = []
    for n, obj in enumerate(data):
        if not isinstance(obj, dict) or obj.get("op") not in _OPS:
            raise ValueError(f"item {n} has no valid op")
        if not isinstance(obj.get("file"), str):
            raise ValueError(f"item {n} has no file path")
        for field in ("old", "new"):
            if obj.get(field) is not None and not isinstance(obj[field], str):
                raise ValueError(f"item {n} has a non-text {field}")
        citations = obj.get("citations", [])
        if not isinstance(citations, list) or not all(
                isinstance(c, dict) and isinstance(c.get("evidence"), str) and isinstance(c.get("quote"), str) for c in citations):
            raise ValueError(f"item {n} has malformed citations")
        for field, keys in (("duplicate_of", ("file", "line")), ("question", ())):
            value = obj.get(field)
            if value is not None and (not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in keys)):
                raise ValueError(f"item {n} has a malformed {field}")
        changes.append(Change(op=obj["op"], file=obj.get("file"), old=obj.get("old"), new=obj.get("new"),
                              citations=citations, duplicate_of=obj.get("duplicate_of"), question=obj.get("question")))
    return changes


def build_request(root, evidence: dict, as_of: str) -> str:
    """The user message for the compile call: every store line with its recorded origin, then the evidence."""
    from um.profile import Lineage, lines_of

    lineage = Lineage(root)
    out = [f"Today's date: {as_of}", "", "STORE LINES (file | recorded origin | line)"]
    out += [f"{f} | {lineage.origin_of(f, line)} | {line}" for f, line in lines_of(root)]
    out += ["", "EVIDENCE"]
    if not evidence:
        out.append("(none)")
    for ev in sorted(evidence.values(), key=lambda e: (e.date, e.id)):
        out += [f"[{ev.id}] origin: {ev.origin}, date: {ev.date}", ev.text, ""]
    return "\n".join(out).rstrip() + "\n"


def propose(root, evidence: dict, llm, model: str, as_of: str) -> list[Change]:
    """Ask for a list of cited changes. Raises ValueError when the reply cannot be used."""
    from um.llm import outcome_of
    from um.prompts import load_prompt

    system = load_prompt("compile.md").replace("{as_of}", as_of)
    reply = llm.complete(model=model, system=system, user=build_request(root, evidence, as_of), max_tokens=16_000,
                         label="compile")
    outcome = outcome_of(reply)
    if outcome != "ok":
        raise ValueError(f"compile reply ended with {outcome}")
    return parse_changes(reply.text)
