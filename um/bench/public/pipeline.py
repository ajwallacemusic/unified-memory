"""The pipeline under test on public benchmarks, and the contexts its baselines are answered with.

Pipeline: a dated chat history is written as evidence (user turns `user-said`, assistant turns `assistant`, set
from structure), then Arm B compiles it into a profile, starting from an empty store and chaining store to store
in date order, one compile per batch of sessions. B's questions go nowhere (no oracle): a public benchmark has
no person to ask, and the deployed compile only files questions for later, so a change that needs an answer is
simply not applied. The profile is then read the way Claude Code reads it: the whole profile (`profile-full`), or
`profile.md` plus the lines the profile-context hook returns for the question (`profile-hook`).

Every condition is answered by one call whose system prompt carries the context.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from um.arms import b
from um.bench.public.bm25 import BM25
from um.bridge.prepare import MIRRORED, fact_lines
from um.evidence import ORIGINS
from um.hooks.profile_context import MAX_CHARS, relevant_lines, render
from um.llm import LLM, Reply
from um.profile import lines_of

CONDITIONS = ("none", "full-history", "raw-retrieval", "profile-full", "profile-hook")
RAW_HEADER = "Excerpts from past conversations with this person, retrieved by search (best match first):"
PROFILE_HEADER = "The profile this person keeps with Claude (lines they told Claude, by file):"
DEPLOYED_CAP_FLOOR, DEPLOYED_CAP_SHARE = 5, 0.2   # um.checks.review defaults
_ORIGIN = {"user": "user-said", "assistant": "assistant"}
assert set(_ORIGIN.values()) <= set(ORIGINS)


@dataclass(frozen=True)
class Session:
    id: str
    date: str                              # YYYY-MM-DD
    turns: tuple[tuple[str, str], ...]     # (role, text), role "user" or "assistant"


def est_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _session_tokens(s: Session) -> int:
    return sum(est_tokens(t) for _, t in s.turns)


def write_evidence(sessions: list[Session], out_dir: Path, start: int = 1) -> list[str]:
    """One evidence file per session and origin, numbered from `start`; returns the evidence ids."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = []
    for n, s in enumerate(sessions, start):
        for role, origin in _ORIGIN.items():
            texts = [t.strip() for r, t in s.turns if r == role and t.strip()]
            if texts:
                eid = f"s{n:03d}-{role}"
                (out_dir / f"{eid}.md").write_text(f"origin: {origin}\ndate: {s.date}\n\n" + "\n\n".join(texts) + "\n")
                ids.append(eid)
    return ids


def batches(sessions: list[Session], max_tokens: int) -> list[list[Session]]:
    """Sessions in date order, grouped so each group's text stays under `max_tokens` (at least one per group)."""
    out: list[list[Session]] = []
    size = 0
    for s in sorted(sessions, key=lambda s: s.date):
        t = _session_tokens(s)
        if out and size + t <= max_tokens:
            out[-1].append(s)
            size += t
        else:
            out.append([s])
            size = t
    return out


class Tally:
    """Wraps a model client and keeps what its calls used."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.replies: list[Reply] = []

    def complete(self, **kw) -> Reply:
        r = self.llm.complete(**kw)
        self.replies.append(r)
        return r

    def run_tools(self, **kw) -> Reply:
        r = self.llm.run_tools(**kw)
        self.replies.append(r)
        return r

    def totals(self) -> dict:
        return {"input_tokens": sum(r.input_tokens for r in self.replies),
                "output_tokens": sum(r.output_tokens for r in self.replies),
                "usd": sum(r.usd for r in self.replies),
                "backend": ",".join(sorted({r.backend for r in self.replies}))}


def _mirrored_rel(rel: str) -> bool:
    return any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in MIRRORED)


def profile_view(store: Path, out: Path) -> Path:
    """The store in the profile layout the hook reads. B's compile prompt files new lines under `memory/`, which
    the profile layout mirrors as `topics/`; such files move there. Hidden records and memory indexes are left out."""
    store, out = Path(store), Path(out)
    keep = None
    if (out / ".um").is_dir():  # expansion words and standing labels are cached by line; keep them
        keep = Path(str(out) + ".um-keep")
        shutil.rmtree(keep, ignore_errors=True)
        shutil.move(str(out / ".um"), keep)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if keep:
        shutil.move(str(keep), out / ".um")
    for p in sorted(store.rglob("*.md")):
        rel = p.relative_to(store).as_posix()
        if any(part.startswith(".") for part in p.relative_to(store).parts) or p.name == "MEMORY.md":
            continue
        target = rel if _mirrored_rel(rel) else "topics/" + rel.removeprefix("memory/")
        dest = out / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = p.read_text()
        if dest.exists():
            prev = dest.read_text()
            text = prev + ("" if prev.endswith("\n") else "\n") + text
        dest.write_text(text)
    return out


def profile_from_sessions(sessions: list[Session], llm: LLM, model: str, workdir: Path, *,
                          max_evidence_tokens: int = 30_000, cap_floor: int | None = None) -> Path:
    """Compile `sessions` into a profile with Arm B and return the profile folder. Resumable: a finished batch
    (`stores/bNNN/.batch.json`) is not run again. One row per batch goes to `compile.jsonl`."""
    workdir = Path(workdir)
    stores = workdir / "stores"
    prev = stores / "b000"
    prev.mkdir(parents=True, exist_ok=True)
    n = 1
    for i, batch in enumerate(batches(sessions, max_evidence_tokens), 1):
        out = stores / f"b{i:03d}"
        marker = out / ".batch.json"
        if marker.exists():
            prev, n = out, n + len(batch)
            continue
        ev = workdir / "evidence" / f"b{i:03d}"
        if ev.exists():
            shutil.rmtree(ev)
        write_evidence(batch, ev, start=n)
        n += len(batch)
        tally = Tally(llm)
        lines_before = len(lines_of(prev))
        outcome = b.apply(prev, out, tally, model, batch[-1].date, evidence_dir=ev, cap_floor=cap_floor)
        record = json.loads((out / b.PASS_FILE).read_text())
        changes = record.get("changes", [])
        applied = sum(1 for c in changes if c.get("applied"))
        deployed = max(DEPLOYED_CAP_FLOOR, int(DEPLOYED_CAP_SHARE * lines_before))
        row = {"batch": i, "sessions": len(batch), "evidence_tokens_est": sum(_session_tokens(s) for s in batch),
               "as_of": batch[-1].date, "outcome": outcome, "proposed": len(changes), "applied": applied,
               "decisions": dict(Counter(c["decision"] for c in changes)),
               "held_by_cap": sum(1 for c in changes if c.get("reason") == "change cap"),
               "lines_before": lines_before, "lines_after": len(lines_of(out)),
               "deployed_cap": deployed, "over_deployed_cap": max(0, applied - deployed),
               "error": record.get("error"), **tally.totals()}
        marker.write_text(json.dumps(row))
        with (workdir / "compile.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        prev = out
    return profile_view(prev, workdir / "profile")


# ---------------------------------------------------------------- contexts

def render_history(sessions: list[Session]) -> str:
    parts = []
    for s in sorted(sessions, key=lambda s: s.date):
        parts.append("\n".join([f"# Conversation on {s.date}", ""] + [f"{r}: {t}" for r, t in s.turns]) + "\n")
    return "\n---\n\n".join(parts)


def raw_retrieval(sessions: list[Session], query: str, budget_chars: int = MAX_CHARS) -> str:
    """Plain BM25 over the raw history: every non-empty line of every turn is a passage, labelled with its date
    and speaker. Best passages first until `budget_chars` (the hook's own size limit by default)."""
    passages = [f"[{s.date}] {r}: {line.strip()}" for s in sessions for r, t in s.turns for line in t.splitlines()
                if line.strip()]
    if not passages:
        return ""
    scores = BM25(passages).scores(query)
    ranked = sorted((i for i, sc in enumerate(scores) if sc > 0), key=lambda i: -scores[i])
    chosen, size = [], 0
    for i in ranked:
        p = passages[i]
        if not chosen and len(p) > budget_chars:
            chosen.append(p[:budget_chars])
            break
        if size + len(p) + 1 > budget_chars:
            continue
        chosen.append(p)
        size += len(p) + 1
    return RAW_HEADER + "\n" + "\n".join(chosen) if chosen else ""


def _profile_files(profile: Path) -> list[Path]:
    profile = Path(profile)
    out = []
    for m in MIRRORED:
        target = profile / m.rstrip("/")
        if m.endswith("/") and target.is_dir():
            out += sorted(target.rglob("*.md"))
        elif target.is_file():
            out.append(target)
    return out


def profile_full(profile: Path) -> str:
    parts = []
    for f in _profile_files(profile):
        lines = fact_lines(f.read_text())
        if lines:
            parts.append(f"[{f.relative_to(profile).as_posix()}]\n" + "\n".join(lines))
    return PROFILE_HEADER + "\n\n" + "\n\n".join(parts) if parts else ""


def enrich(profile: Path, llm: LLM, model: str) -> None:
    """What the deployed compile adds after each run: hook words per line, and standing-preference labels."""
    from um.expand import expand_profile
    from um.standing import label_standing
    expand_profile(profile, llm, model)
    label_standing(profile, llm, model)


def profile_hook(profile: Path, question: str) -> str:
    """What Claude Code would see: profile.md's lines and the standing preferences (both in the imported index),
    then exactly what the hook injects."""
    from um.standing import standing_lines
    pm = Path(profile) / "profile.md"
    head = "\n".join(fact_lines(pm.read_text())) if pm.is_file() else ""
    standing = "\n".join(x for x, _ in standing_lines(Path(profile)))
    head = "\n".join(x for x in (head, standing) if x)
    pairs = relevant_lines(Path(profile), question)
    return "\n\n".join(x for x in (head, render(pairs) if pairs else "") if x)


def answer(question: str, context: str, llm: LLM, model: str, *, instructions: str, max_tokens: int = 4_000,
           label: str = "answer") -> Reply:
    system = instructions + ("\n\n" + context if context.strip() else "")
    return llm.complete(model=model, system=system, user=question, max_tokens=max_tokens, label=label)
