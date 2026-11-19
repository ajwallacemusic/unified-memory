"""Plain-text receipt of one compile pass: what changed, why, from which quote, and how to undo it."""
from __future__ import annotations


def _cite(c: dict) -> str:
    cits = c.get("citations") or []
    return "; ".join(f"\"{x.get('quote')}\" ({x.get('evidence')})" for x in cits) or "no citation"


def receipt(pass_record: dict) -> str:
    day = pass_record.get("as_of", "")
    out = [f"# Compile {day}", ""]
    if pass_record.get("outcome") == "compile_failed":
        out += [f"The compile failed and nothing changed: {pass_record.get('error', 'unknown error')}", ""]
    changes = pass_record.get("changes", [])
    groups = (("Applied", lambda c: c.get("applied")),
              ("Held", lambda c: not c.get("applied") and c.get("decision") in ("hold", "ask")),
              ("Rejected", lambda c: not c.get("applied") and c.get("decision") == "reject"))
    for title, pick in groups:
        items = [c for c in changes if pick(c)]
        if not items:
            continue
        out += [f"## {title} ({len(items)})", ""]
        for c in items:
            what = {"add": f"add `{c.get('new')}`", "remove": f"remove `{c.get('old')}`"}.get(
                c.get("op"), f"`{c.get('old')}` -> `{c.get('new')}`")
            word = title.lower()
            out.append(f"- {word}: {what} in {c.get('file')}. Source: {_cite(c)}. Origin {c.get('origin') or 'none'}."
                       + ("" if c.get("applied") else f" Reason: {c.get('reason')}."))
        out.append("")
    qs = pass_record.get("questions", [])
    if qs:
        out += ["## Questions", ""]
        out += [f"- {(q.get('question') or {}).get('text', '')} ({q.get('status')})" for q in qs] + [""]
    if not changes and pass_record.get("outcome") != "compile_failed":
        out += ["No changes proposed.", ""]
    out += ["Undo: /unified-memory:undo reverts this compile's commit.",
            "Instruction files are not checked against code here; run /doctor prompt-audit for those.", ""]
    return "\n".join(out)
