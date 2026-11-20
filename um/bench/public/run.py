"""Runner for the public benchmarks: every item, every condition, one answer model, one judge.

    python -m um.bench.public.run --bench prefeval|longmemeval|mab --n 10 --out DIR --api-cap 30.22

One JSON line per (item, condition) goes to DIR/results.jsonl; a pair already there is not run again, and a
finished compile batch is not compiled again. Compiles go to the Claude subscription only (they are Sonnet calls
on up to ~30k tokens); answers and judging go to the API under a hard dollar cap. Profiles, evidence and any
benchmark text stay under DIR/stores/, which git ignores. Tracked rows hold ids, answers, verdicts and counts.
"""
from __future__ import annotations

import argparse
import json

from um.bench.meta import public_invocation
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from um.bench.public import pipeline as pl
from um.budget import BudgetExceeded
from um.llm import outcome_of
from um.llm_sub import SubscriptionError

ALL = pl.CONDITIONS
HISTORY_HEADER = "The full record of your past conversations with this person:"


class SubscriptionClosed(Exception):
    """Plan usage is over the ceiling (or unknown); subscription-only work stops."""


class Router:
    """Calls whose label starts with one of `sub_prefixes` go to the subscription (one retry), and stop when the
    usage gate is closed; everything else goes to the API."""

    def __init__(self, api, sub, gate, sub_prefixes: tuple[str, ...] = ("compile", "expand", "standing")):
        self.api, self.sub, self.gate, self.sub_prefixes = api, sub, gate, sub_prefixes
        self._lock = threading.Lock()

    def complete(self, *, model, system, user, max_tokens, label):
        kw = dict(model=model, system=system, user=user, max_tokens=max_tokens, label=label)
        if not label.startswith(self.sub_prefixes):
            return self.api.complete(**kw)
        for attempt in (1, 2):
            if not self.gate.is_open():
                raise SubscriptionClosed(f"plan usage gate closed before {label}")
            try:
                return self.sub.complete(**kw)
            except SubscriptionError:
                if attempt == 2:
                    raise

    def run_tools(self, **kw):
        return self.api.run_tools(**kw)


@dataclass
class Bench:
    name: str
    items: list
    key: Callable                       # item -> profile id (items sharing a history share a profile)
    sessions: Callable                  # (item, llm, workdir) -> list[Session]
    question: Callable                  # item -> user message for the answer call
    query: Callable                     # item -> text the retrievers and the hook match against
    instructions: Callable              # (item, condition) -> system prompt before the context
    grade: Callable                     # (item, answer text, judge llm) -> dict with "correct"
    max_tokens: int
    history: Callable | None = None     # (item, sessions) -> full-history text; default renders the sessions
    extra: dict = field(default_factory=dict)   # extra condition -> (item -> context)
    max_evidence_tokens: int = 30_000
    ident: Callable = lambda it: it.id   # item -> id recorded in results


def _done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    text = path.read_text()
    if text and not text.endswith("\n"):
        text = text[: text.rfind("\n") + 1]
        path.write_text(text)
    return {(r["item"], r["condition"]) for r in map(json.loads, text.splitlines()) if r}


def _append(path: Path, row: dict, lock: threading.Lock) -> None:
    with lock, path.open("a") as f:
        f.write(json.dumps(row) + "\n")


class _Judge:
    """Passes judge calls through with the judge model and keeps their token counts."""

    def __init__(self, llm, model):
        self.tally, self.model = pl.Tally(llm), model

    def complete(self, *, model, system, user, max_tokens, label):
        return self.tally.complete(model=self.model, system=system, user=user, max_tokens=max_tokens, label=label)


def run(bench: Bench, out: Path, llm, *, answer_model: str, compile_model: str, judge_model: str,
        conditions: tuple[str, ...] = ALL, workers: int = 1, cap_floor: int | None = None) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    done = _done(results)
    lock, stop = threading.Lock(), threading.Event()
    key_locks: dict[str, threading.Lock] = {}

    def key_lock(k: str) -> threading.Lock:
        with lock:
            return key_locks.setdefault(k, threading.Lock())

    def work(item) -> None:
        iid = bench.ident(item)
        pending = [c for c in conditions if (iid, c) not in done]
        if not pending or stop.is_set():
            return
        key = bench.key(item)
        wd = out / "stores" / key
        try:
            with key_lock(key):
                sessions = bench.sessions(item, llm, wd)
                profile = None
                if {"profile-full", "profile-hook"} & set(pending):
                    profile = pl.profile_from_sessions(sessions, llm, compile_model, wd / "b", cap_floor=cap_floor,
                                                       max_evidence_tokens=bench.max_evidence_tokens)
                    if "profile-hook" in pending:
                        pl.enrich(profile, llm, compile_model)
            for c in pending:
                if stop.is_set():
                    return
                if c == "none":
                    ctx = ""
                elif c == "full-history":
                    ctx = HISTORY_HEADER + "\n\n" + (bench.history(item, sessions) if bench.history
                                                     else pl.render_history(sessions))
                elif c == "raw-retrieval":
                    ctx = pl.raw_retrieval(sessions, bench.query(item))
                elif c == "profile-full":
                    ctx = pl.profile_full(profile)
                elif c == "profile-hook":
                    ctx = pl.profile_hook(profile, bench.query(item))
                else:
                    ctx = bench.extra[c](item)
                reply = pl.answer(bench.question(item), ctx, llm, answer_model, max_tokens=bench.max_tokens,
                                  instructions=bench.instructions(item, c), label=f"answer:{bench.name}:{c}")
                outcome = outcome_of(reply)
                judge = _Judge(llm, judge_model)
                verdict = bench.grade(item, reply.text, judge) if reply.text.strip() else {"correct": False}
                _append(results, {"bench": bench.name, "item": iid, "condition": c, "outcome": outcome,
                                  **verdict, "answer": reply.text, "context_chars": len(ctx),
                                  "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
                                  "backend": reply.backend, "usd": reply.usd,
                                  **{f"judge_{k}": v for k, v in judge.tally.totals().items()}}, lock)
        except (BudgetExceeded, SubscriptionClosed) as e:
            stop.set()
            _append(out / "errors.jsonl", {"item": bench.ident(item), "error": f"stopped: {e}"}, lock)
        except Exception as e:  # left unrecorded so a rerun retries it
            _append(out / "errors.jsonl", {"item": bench.ident(item), "error": repr(e)[:500],
                                           "trace": traceback.format_exc()[-1500:]}, lock)

    if workers <= 1:
        for it in bench.items:
            work(it)
    else:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(work, bench.items))
    if stop.is_set():
        print("stopped early (spend cap or plan usage); rerun to continue", file=sys.stderr)


# ---------------------------------------------------------------- the three benchmarks

def prefeval_bench(root: Path, n: int, seed: int, n_inter: int, answer_model: str,
                   answer_max_tokens: int | None = None) -> Bench:
    """`answer_max_tokens` (default `ANSWER_MAX_TOKENS`) is the output budget of every condition's answer call."""
    from um.bench.public import prefeval as pe
    items = pe.sample(pe.load(root), n, seed)
    inter = pe.inter_turns(root, n_inter)

    def sessions(item, llm, wd):
        f = Path(wd) / "pref_generation.json"
        if not f.exists():
            r = pe.pref_generation(item, llm, answer_model)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"text": r.text, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                                     "usd": r.usd, "backend": r.backend}))
        return pe.sessions(item, json.loads(f.read_text())["text"], inter)

    def grade(item, text, judge):
        checks = pe.judge(item, text, judge, judge.model, root)
        s = pe.score(checks)
        return {"correct": s["preference_following"], **{k: checks[k] for k in pe.CHECKS},
                **{k: v for k, v in s.items() if k != "preference_following"}}

    return Bench("prefeval", items, key=lambda it: it.id.replace(":", "-"), sessions=sessions,
                 question=pe.question_text, query=lambda it: it.question,
                 instructions=lambda it, c: pe.SYSTEM_PROMPT, grade=grade,
                 max_tokens=answer_max_tokens or pe.ANSWER_MAX_TOKENS)


def lme_bench(path: Path, n: int, seed: int) -> Bench:
    from um.bench import longmemeval as lm
    from um.bench.public import lme
    pool = [i for i in lm.load(path) if i.qtype in lme.TYPES]
    available = {t: sum(1 for i in pool if i.qtype == t) for t in lme.TYPES}
    items = lm.sample(pool, lme.counts_for(n, available), seed)
    return Bench("longmemeval", items, key=lambda it: it.qid, ident=lambda it: it.qid, sessions=lambda it, llm, wd: lme.sessions(it),
                 question=lme.question_text, query=lambda it: it.question, instructions=lme.instructions,
                 grade=lambda it, text, judge: lme.grade(it, text, judge, judge.model), max_tokens=lme.MAX_TOKENS)


def mab_bench(path: Path, source: str, n: int, seed: int, per_session: int) -> Bench:
    import random

    from um.bench.public import mab
    ctx = mab.load(path, source)
    items = ctx.items if n >= len(ctx.items) else sorted(random.Random(seed).sample(ctx.items, n),
                                                          key=lambda q: ctx.items.index(q))
    ss = mab.sessions(ctx, per_session)
    return Bench("mab", items, key=lambda it: source, sessions=lambda it, llm, wd: ss,
                 question=lambda it: mab.query(it.question), query=lambda it: it.question,
                 instructions=lambda it, c: mab.SYSTEM_MESSAGE,
                 grade=lambda it, text, judge: {"correct": mab.sub_em(text, it.answers)},
                 max_tokens=mab.MAX_TOKENS, history=lambda it, s: ctx.text,
                 extra={"last-write": lambda it: mab.last_write(ctx, it.question)},
                 max_evidence_tokens=1)   # one chunk of facts per compile, so the reply fits its token limit


def main(argv: list[str] | None = None) -> None:
    from um.budget import Budget
    from um.gate import UsageGate
    from um.llm import AnthropicLLM
    from um.llm_sub import ClaudeCodeLLM

    ap = argparse.ArgumentParser(prog="um.bench.public.run")
    ap.add_argument("--bench", required=True, choices=("prefeval", "longmemeval", "mab"))
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--api-cap", type=float, required=True, help="hard API cap in dollars, whole ledger")
    ap.add_argument("--ledger", type=Path, default=Path("results/spend.jsonl"))
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--conditions", default=None, help="comma list; default: all for the benchmark")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--answer-model", default="claude-haiku-5-5")
    ap.add_argument("--judge-model", default="claude-haiku-5-5")
    ap.add_argument("--compile-model", default="claude-sonnet-5-5")
    ap.add_argument("--cap-floor", type=int, default=100_000,
                    help="Arm B's minimum change cap per pass (deployed: 5); the log records what 5 would have held")
    ap.add_argument("--sub-ceiling", type=float, default=70.0)
    ap.add_argument("--usage-file", type=Path, default=Path.home() / ".claude/usage-now.json")
    ap.add_argument("--prefeval-root", type=Path, default=Path("data/public/prefeval"))
    ap.add_argument("--inter-turns", type=int, default=10)
    ap.add_argument("--answer-max-tokens", type=int, default=None,
                    help="PrefEval: output budget of the answer call, the same for every condition")
    ap.add_argument("--lme-data", type=Path, default=Path("data/public/longmemeval/longmemeval_s_cleaned.json"))
    ap.add_argument("--mab-data", type=Path, default=Path("data/public/memoryagentbench/conflict_resolution.json"))
    ap.add_argument("--mab-source", default="factconsolidation_sh_6k")
    ap.add_argument("--mab-per-session", type=int, default=50)
    a = ap.parse_args(argv)

    budget = Budget(a.api_cap, a.ledger)
    gate = UsageGate(a.sub_ceiling, 900, a.usage_file)
    llm = Router(AnthropicLLM(budget), ClaudeCodeLLM(), gate)
    if a.bench == "prefeval":
        bench = prefeval_bench(a.prefeval_root, a.n, a.seed, a.inter_turns, a.answer_model, a.answer_max_tokens)
    elif a.bench == "longmemeval":
        bench = lme_bench(a.lme_data, a.n, a.seed)
    else:
        bench = mab_bench(a.mab_data, a.mab_source, a.n, a.seed, a.mab_per_session)
    conditions = tuple(a.conditions.split(",")) if a.conditions else ALL + tuple(bench.extra)
    spent_before = budget.spent()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run(bench, a.out, llm, answer_model=a.answer_model, compile_model=a.compile_model, judge_model=a.judge_model,
        conditions=conditions, workers=a.workers, cap_floor=a.cap_floor)
    meta_path = a.out / "run_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"invocations": []}
    meta["invocations"].append(public_invocation({
        "argv": sys.argv[1:] if argv is None else argv, "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": [bench.ident(it) for it in bench.items],
        "conditions": list(conditions), "answer_model": a.answer_model, "judge_model": a.judge_model,
        "compile_model": a.compile_model, "cap_floor": a.cap_floor, "answer_max_tokens": bench.max_tokens,
        **({"inter_turns": a.inter_turns} if a.bench == "prefeval" else {})}, spent_before, budget.spent()))
    meta_path.write_text(json.dumps(meta, indent=1))
    print(f"API cost of this run ${budget.spent() - spent_before:.4f}")


if __name__ == "__main__":
    main()
