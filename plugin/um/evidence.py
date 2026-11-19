"""Evidence: dated, unmodified source text with the origin it came from.

An evidence file is Markdown whose first line is `origin: <origin>` and second line `date: <ISO date>`;
the rest is the text. Origin is set by whatever produced the file, from structure, never by a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ORIGINS = ("user-said", "assistant", "tool-output", "file-edit", "probe", "legacy")


@dataclass(frozen=True)
class Evidence:
    id: str
    origin: str
    date: str
    text: str
    path: Path


def load_evidence(dir: Path) -> dict[str, Evidence]:
    out = {}
    for p in sorted(Path(dir).glob("*.md")):
        lines = p.read_text().splitlines()
        ok = (len(lines) >= 2 and lines[0].startswith("origin: ") and lines[1].startswith("date: ")
              and lines[0][8:].strip() in ORIGINS and re.fullmatch(r"\d{4}-\d{2}-\d{2}", lines[1][6:].strip()))
        if not ok:
            raise ValueError(f"{p.name} does not start with a valid `origin:` line and `date:` line")
        out[p.stem] = Evidence(p.stem, lines[0][8:].strip(), lines[1][6:].strip(), "\n".join(lines[2:]).strip(), p)
    return out


def _squash(text: str) -> str:
    return " ".join(text.split())


def contains_quote(ev: Evidence, quote: str) -> bool:
    """True when the quote occurs in the evidence text, ignoring differences in whitespace."""
    q = _squash(quote)
    return bool(q) and q in _squash(ev.text)


_QA = re.compile(r"^Q \(asked by [^)]*\):(?P<q>.*?)^A \([^)]*\):(?P<a>.*)\Z", re.S | re.M)


def question_and_answer(ev: Evidence) -> tuple[str, str] | None:
    """(question, answer) for an answer the person gave to a question Claude asked, recorded as
    `Q (asked by Claude): ...` then `A (<name>): ...`; None for any other evidence."""
    m = _QA.search(ev.text)
    return (m["q"].strip(), m["a"].strip()) if m else None
