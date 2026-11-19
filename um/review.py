"""Store self-review: read the profile against itself and today's date and turn what is probably stale or
contradictory into questions. Compiles act only on new cited evidence, so they cannot see a line that another
line contradicts or a plan whose date has passed; this pass can. It never edits: every finding is a question,
and code keeps a finding only if the lines it quotes exist verbatim in the files it names.

    python -m um.cli review [--profile P]
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from um.bridge.prepare import _mirrored, fact_lines
from um.llm import LLM
from um.prompts import load_prompt

KINDS = ("contradiction", "elapsed", "relative-time", "open-status")
MAX_TOKENS = 8_000


def _render(profile: Path) -> dict[str, list[str]]:
    return {"/" + f.relative_to(profile).as_posix(): fact_lines(f.read_text()) for f in _mirrored(profile)}


def _parse(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        return []
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _valid(f: dict, files: dict[str, list[str]]) -> bool:
    line, kind, q = (f.get("line") or "").strip(), f.get("kind"), (f.get("question") or "").strip()
    if kind not in KINDS or not q or line not in files.get(f.get("file") or "", []):
        return False
    if kind == "contradiction":
        other = (f.get("other_line") or "").strip()
        where = files.get(f.get("other_file") or "") or [x for lines in files.values() for x in lines]
        return bool(other) and other != line and other in where
    return True


def review_store(profile: Path, llm: LLM, model: str, as_of: str) -> tuple[list[dict], int]:
    """(findings kept, number dropped). Findings are dicts with file, line, kind, other_file, other_line, question."""
    profile = Path(profile)
    files = _render(profile)
    user = f"Today is {as_of}.\n\n" + "\n\n".join(f"## {path}\n" + "\n".join(lines) for path, lines in files.items())
    system = load_prompt("review.md").replace("{as_of}", as_of)
    reply = llm.complete(model=model, system=system, user=user, max_tokens=MAX_TOKENS, label="review")
    kept, seen, dropped = [], set(), 0
    for f in _parse(reply.text):
        if not _valid(f, files):
            dropped += 1
            continue
        key = (f.get("file"), f["line"].strip())
        if key not in seen:
            seen.add(key)
            kept.append({k: f.get(k) for k in ("file", "line", "kind", "other_file", "other_line", "question")})
    return kept, dropped


def write_review(findings: list[dict], out: Path, as_of: str, dropped: int = 0) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Store review, {as_of}", "",
             f"{len(findings)} questions; {dropped} dropped because a quoted line was not in the store. Nothing was changed.", ""]
    for i, f in enumerate(findings, 1):
        lines += [f"{i}. **{f['question']}** ({f['kind']})", f"   - `{f['file']}`: {f['line']}"]
        if f.get("other_line"):
            lines.append(f"   - `{f.get('other_file') or '?'}`: {f['other_line']}")
    out.write_text("\n".join(lines) + "\n")
