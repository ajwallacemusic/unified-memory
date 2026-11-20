"""Resumable benchmark runner.

For each sampled question: write a memory store from the history once, apply each store arm to a
copy of it, answer from each, and grade. One JSON line per (question, arm) goes to results.jsonl;
a pair that is already there is never run or charged again.

    python -m um.bench.run --data PATH --out DIR --arms z,a0,a,full,files --n 100 --cap 12
"""
from __future__ import annotations

import argparse
import json

from um.bench.meta import public_invocation
import shutil
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from um.arms import ARMS
from um.bench.answer import answer_files_agent, answer_from_store, answer_full_context
from um.bench.judge import JUDGE_MAX_TOKENS, judge_prompt, verdict_of
from um.bench.longmemeval import SAMPLE_COUNTS, SEED, Item, load, materialize, sample
from um.budget import BudgetExceeded
from um.llm import EFFORT, LLM, Reply, outcome_of
from um.writer import write_memory

STORE_ARMS = tuple(ARMS)            # z, a0, a
REFERENCE_ARMS = ("full", "files")  # full context; plain files with search
DEFAULT_MODEL = "claude-haiku-5-5"


def counts_for(n: int, available: dict[str, int] | None = None) -> dict[str, int]:
    """Per-type sample sizes: the fixed mix at n=100, scaled by largest remainder otherwise, and
    never more than a type has."""
    total = sum(SAMPLE_COUNTS.values())
    exact = {t: n * c / total for t, c in SAMPLE_COUNTS.items()}
    counts = {t: int(v) for t, v in exact.items()}
    for t in sorted(exact, key=lambda t: exact[t] - counts[t], reverse=True)[: n - sum(counts.values())]:
        counts[t] += 1
    if available is not None:
        counts = {t: min(c, available.get(t, 0)) for t, c in counts.items()}
    return {t: c for t, c in counts.items() if c}


class Meter:
    """Wraps a model client and adds up what one stage used."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.input_tokens = self.output_tokens = 0
        self.usd = 0.0

    def _add(self, reply: Reply) -> Reply:
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        self.usd += reply.usd
        return reply

    def complete(self, **kw) -> Reply:
        return self._add(self.llm.complete(**kw))

    def run_tools(self, **kw) -> Reply:
        return self._add(self.llm.run_tools(**kw))


def _done_pairs(results_path: Path) -> set[tuple[str, str]]:
    """Pairs already recorded. A torn final line from an interrupted write is cut off first, so the
    next row starts on a clean line and the pair it belonged to is run again."""
    if not results_path.exists():
        return set()
    text = results_path.read_text()
    if text and not text.endswith("\n"):
        text = text[: text.rfind("\n") + 1]
        results_path.write_text(text)
    return {(r["qid"], r["arm"]) for r in map(json.loads, text.splitlines()) if r}


def _record_invocation(out: Path, invocation: dict, facts: dict, notes: list[str]) -> None:
    """run_meta.json keeps one entry per invocation, plus facts that hold for the whole folder."""
    path = out / "run_meta.json"
    meta = json.loads(path.read_text()) if path.exists() else {}
    meta.update(facts)
    meta.setdefault("invocations", []).append(invocation)
    for note in notes:
        if note not in meta.setdefault("notes", []):
            meta["notes"].append(note)
    path.write_text(json.dumps(meta, indent=1))


def _append(path: Path, row: dict, lock: threading.Lock) -> None:
    with lock:
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def _ensure_written(item: Item, item_dir: Path, llm: LLM, model: str, out: Path, lock: threading.Lock) -> None:
    """Run the shared writer once per question; a marker file says the store is complete."""
    marker = item_dir / ".writer_done"
    src = item_dir / "z_src"
    if marker.exists():
        return
    if src.exists():
        shutil.rmtree(src)  # a half-written store from an interrupted run
    src.mkdir(parents=True)
    meter = Meter(llm)
    outcomes = write_memory(item.sessions, src, meter, model)
    _append(out / "writer.jsonl", {"qid": item.qid, "outcomes": outcomes, "input_tokens": meter.input_tokens,
                                   "output_tokens": meter.output_tokens, "usd": meter.usd}, lock)
    marker.write_text("done\n")


def _run_pair(item: Item, arm: str, item_dir: Path, llm: LLM, model: str) -> dict:
    meter = Meter(llm)
    arm_outcome = None
    if arm == "full":
        reply = answer_full_context(item, meter, model)
    elif arm == "files":
        sessions_dir = item_dir / "sessions"
        if not sessions_dir.exists():
            materialize(item, sessions_dir)
        reply = answer_files_agent(item, sessions_dir, meter, model)
    else:
        store = item_dir / arm
        arm_outcome = ARMS[arm].apply(item_dir / "z_src", store, meter, model, item.question_date)
        reply = answer_from_store(item, store, meter, model)
    outcome = outcome_of(reply)
    correct = judge_raw = judge_backend = None
    if outcome == "ok":
        verdict = meter.complete(model=model, system="", user=judge_prompt(item, reply.text),
                                 max_tokens=JUDGE_MAX_TOKENS, label="judge")
        judge_raw, judge_backend = verdict.text.strip(), verdict.backend
        correct = verdict_of(judge_raw) if outcome_of(verdict) == "ok" else None
        if correct is None:
            outcome = "judge_failed"  # the answer was never graded; it is not a wrong answer
    return {
        "qid": item.qid, "qtype": item.qtype, "arm": arm, "outcome": outcome, "correct": correct,
        "response": reply.text, "backend": reply.backend, "judge_backend": judge_backend,
        "arm_outcome": arm_outcome, "judge_raw": judge_raw,
        "input_tokens": meter.input_tokens, "output_tokens": meter.output_tokens, "usd": meter.usd,
    }


def run(data: Path, out: Path, arms: list[str], n: int, llm: LLM, model: str = DEFAULT_MODEL,
        workers: int = 1, meta: dict | None = None, limit: int | None = None) -> None:
    unknown = [a for a in arms if a not in STORE_ARMS + REFERENCE_ARMS]
    if unknown:
        raise ValueError(f"unknown arms: {unknown}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items = load(Path(data))
    available: dict[str, int] = {}
    for i in items:
        available[i.qtype] = available.get(i.qtype, 0) + 1
    chosen = sample(items, counts_for(n, available), SEED)
    results_path = out / "results.jsonl"
    done = _done_pairs(results_path)
    lock = threading.Lock()
    stop = threading.Event()
    extra = dict(meta or {})
    notes = extra.pop("notes", [])
    _record_invocation(
        out,
        {"arms": arms, "n_requested": n, "limit": limit, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         **extra},
        {"data": str(data), "n_sampled": len(chosen), "seed": SEED, "model": model, "judge_model": model},
        notes,
    )

    def work(item: Item) -> None:
        pending = [a for a in arms if (item.qid, a) not in done]
        if not pending or stop.is_set():
            return
        item_dir = out / "stores" / item.qid
        try:
            if any(a in STORE_ARMS for a in pending):
                _ensure_written(item, item_dir, llm, model, out, lock)
            for arm in pending:
                if stop.is_set():
                    return
                _append(results_path, _run_pair(item, arm, item_dir, llm, model), lock)
        except BudgetExceeded as e:
            stop.set()
            _append(out / "errors.jsonl", {"qid": item.qid, "error": f"budget: {e}"}, lock)
        except Exception as e:  # leave the pair unrecorded so the next run retries it
            _append(out / "errors.jsonl", {"qid": item.qid, "error": repr(e),
                                           "trace": traceback.format_exc()[-1500:]}, lock)

    todo = [i for i in chosen if any((i.qid, a) not in done for a in arms)]
    if limit is not None:
        todo = todo[:limit]  # work through the sample a batch at a time
    if workers <= 1:
        for item in todo:
            work(item)
    else:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(work, todo))
    if stop.is_set():
        print("stopped: spend cap reached; rerun to continue once there is headroom", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    from um.budget import Budget
    from um.gate import UsageGate
    from um.llm import AnthropicLLM
    from um.llm_sub import ClaudeCodeLLM, HybridLLM

    ap = argparse.ArgumentParser(prog="um.bench.run")
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--arms", default="z,a0,a,full,files")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--cap", type=float, required=True, help="hard API spend cap in dollars, across all runs")
    ap.add_argument("--sub-ceiling", type=float, default=70.0, help="plan usage percent above which the subscription is not used")
    ap.add_argument("--sub-max-age", type=int, default=900, help="seconds after which a usage reading is too old to trust")
    ap.add_argument("--usage-file", type=Path, default=None, help="plan usage file to gate on")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="process at most this many unfinished questions, then stop")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ledger", type=Path, default=Path("results/spend.jsonl"))
    a = ap.parse_args(argv)

    budget = Budget(a.cap, a.ledger)
    gate = UsageGate(a.sub_ceiling, a.sub_max_age, a.usage_file) if a.usage_file else UsageGate(a.sub_ceiling, a.sub_max_age)
    llm = HybridLLM(AnthropicLLM(budget), ClaudeCodeLLM(), gate)
    spent_before = budget.spent()
    meta = {"effort": EFFORT}
    run(a.data, a.out, a.arms.split(","), a.n, llm, a.model, a.workers, meta, a.limit)
    meta_path = a.out / "run_meta.json"
    m = json.loads(meta_path.read_text())
    this = m["invocations"][-1]
    this.update(finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    m["invocations"][-1] = public_invocation(this, spent_before, budget.spent())
    meta_path.write_text(json.dumps(m, indent=1))
    print(f"API cost of this run ${budget.spent() - spent_before:.4f}")


if __name__ == "__main__":
    main()
