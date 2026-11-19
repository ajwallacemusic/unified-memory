"""The recall benchmark's data: a fictional person's profile and questions answerable only from it.

    bench/recall/profile/       account-memory layout (profile.md, areas/, topics/, people/)
    bench/recall/questions.jsonl  {id, split: dev|test, kind: direct|paraphrase|multi, question, answer_terms, file}
    bench/recall/offtopic.jsonl   {id, prompt}: prompts where nothing from the profile should be added

A hit is any answer term appearing in the answer, case-insensitive. `validate` refuses questions that give a
free hit (the term is in the question) or an ambiguous one (the term is in a file other than the cited one).
"""
from __future__ import annotations

import json
from pathlib import Path

KINDS = {"direct", "paraphrase", "multi"}
SPLITS = {"dev", "test"}


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def load_questions(root: Path, split: str | None = None) -> list[dict]:
    return [r for r in _rows(Path(root) / "questions.jsonl") if split is None or r.get("split") == split]


def load_offtopic(root: Path) -> list[dict]:
    return _rows(Path(root) / "offtopic.jsonl")


def validate(root: Path) -> list[str]:
    root = Path(root)
    prof = root / "profile"
    texts = {f.relative_to(prof).as_posix(): f.read_text().lower() for f in prof.rglob("*.md")}
    probs, seen = [], set()
    qs = load_questions(root)
    for r in qs:
        i = r.get("id")
        if i in seen:
            probs.append(f"{i}: duplicate id")
        seen.add(i)
        if r.get("kind") not in KINDS:
            probs.append(f"{i}: kind {r.get('kind')!r}")
        if r.get("split") not in SPLITS:
            probs.append(f"{i}: split {r.get('split')!r}")
        files = r.get("file") if isinstance(r.get("file"), list) else [r.get("file")]
        terms = r.get("answer_terms") or []
        if not terms or not str(r.get("question", "")).strip():
            probs.append(f"{i}: empty question or answer_terms")
        for f in files:
            if f not in texts:
                probs.append(f"{i}: file {f} does not exist")
        for t in terms:
            tl = t.lower()
            if tl in str(r.get("question", "")).lower():
                probs.append(f"{i}: answer term {t!r} appears in the question")
            if not any(tl in texts.get(f, "") for f in files):
                probs.append(f"{i}: answer term {t!r} not in {', '.join(map(str, files))}")
            if r.get("kind") != "multi":
                for other, text in texts.items():
                    if other not in files and tl in text:
                        probs.append(f"{i}: answer term {t!r} also in {other}")
    dev = sum(r.get("split") == "dev" for r in qs)
    if qs and not 0.4 <= dev / len(qs) <= 0.6:
        probs.append(f"split: {dev} of {len(qs)} questions are dev; want 40-60%")
    for o in load_offtopic(root):
        if not str(o.get("prompt", "")).strip():
            probs.append(f"{o.get('id')}: empty off-topic prompt")
    return probs
