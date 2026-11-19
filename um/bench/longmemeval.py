"""Loader, fixed sample and file layout for LongMemEval (cleaned release, MIT licence).

Field names as found in `longmemeval_s_cleaned.json` on 2026-11-10: question_id, question_type,
question, question_date, answer, answer_session_ids, haystack_dates, haystack_session_ids,
haystack_sessions (a list of sessions, each a list of {role, content} turns). Dates look like
"2023/05/20 (Sat) 02:21". Abstention questions are the ones whose id ends in "_abs"; they are
given their own type here so they can be reported separately.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SAMPLE_COUNTS = {"knowledge-update": 40, "temporal-reasoning": 30, "abstention": 20, "multi-session": 10}
SEED = 20261110


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


@dataclass(frozen=True)
class Session:
    id: str
    date: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Item:
    qid: str
    qtype: str
    question: str
    answer: str
    question_date: str
    sessions: tuple[Session, ...]
    is_abstention: bool


def parse_date(text: str) -> datetime:
    """Parse "2023/05/20 (Sat) 02:21"; the weekday in brackets is ignored."""
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    return datetime.strptime(cleaned, "%Y/%m/%d %H:%M")


def load(path: Path) -> list[Item]:
    items = []
    for row in json.loads(Path(path).read_text()):
        sessions = [
            Session(str(sid), date, tuple(Turn(t["role"], t["content"]) for t in turns))
            for sid, date, turns in zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"])
        ]
        sessions.sort(key=lambda s: parse_date(s.date))
        qid = str(row["question_id"])
        is_abstention = qid.endswith("_abs")
        items.append(Item(
            qid=qid,
            qtype="abstention" if is_abstention else row["question_type"],
            question=row["question"],
            answer=str(row["answer"]),
            question_date=row["question_date"],
            sessions=tuple(sessions),
            is_abstention=is_abstention,
        ))
    return items


def sample(items: list[Item], counts: dict[str, int] = SAMPLE_COUNTS, seed: int = SEED) -> list[Item]:
    rng = random.Random(seed)
    chosen: list[Item] = []
    for qtype in sorted(counts):
        pool = sorted((i for i in items if i.qtype == qtype), key=lambda i: i.qid)
        if len(pool) < counts[qtype]:
            raise ValueError(f"need {counts[qtype]} items of type {qtype!r}, found {len(pool)}")
        chosen += rng.sample(pool, counts[qtype])
    return sorted(chosen, key=lambda i: i.qid)


def render_session(session: Session) -> str:
    lines = [f"# Conversation on {session.date}", ""]
    lines += [f"{t.role}: {t.content}" for t in session.turns]
    return "\n".join(lines) + "\n"


def materialize(item: Item, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for n, session in enumerate(item.sessions, 1):
        stamp = parse_date(session.date).strftime("%Y-%m-%d_%H%M")
        (out_dir / f"{n:03d}_{stamp}.md").write_text(render_session(session))
