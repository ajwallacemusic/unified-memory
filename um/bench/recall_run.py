"""End-to-end recall run: each held-out question in its own isolated Claude Code session, under each setup.

    .venv/bin/python -m um.bench.recall_run [--split test] [--model sonnet] [--workers 4] [--out results/recall-bench/X]

Writes <out>.jsonl (one row per question and setup; rerunning resumes and retries errors), <out>-offtopic.jsonl
(off-topic prompts under index and hook, for the tokens the hook adds) and <out>-summary.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from um.bench.stats import paired_diff, wilson

SUFFIX = ("\n\nAnswer from what you already know about me. Do not search the web. If you do not know, answer "
          "UNKNOWN. Keep it to one or two sentences.")  # the wording of the project's cross-surface recall test, plus a length cap


def hit(answer: str | None, terms: list[str]) -> bool:
    return bool(answer) and any(t.lower() in answer.lower() for t in terms)


JUDGE = ("You grade an assistant's response against one yes/no question. Answer YES or NO as the first word, "
         "then at most one short sentence. Judge only from the response text.")


def judge(item: dict, answer: str, llm, model: str = "claude-haiku-5-5") -> bool:
    r = llm.complete(model=model, system=JUDGE, user=f"Question: {item['check']}\n\nResponse:\n{answer}",
                     max_tokens=100, label="implicit-judge")
    return r.text.strip().upper().startswith("YES")


def _done(out: Path) -> set[tuple[str, str]]:
    rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()] if out.exists() else []
    return {(r["id"], r["condition"]) for r in rows if not r.get("error")}


def run(items: list[dict], conditions: list[str], probe, out: Path, workers: int = 4, suffix: str = SUFFIX,
        score=None, gate=None) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _done(out)
    todo = [(it, c) for it in items for c in conditions if (it["id"], c) not in done]
    lock = threading.Lock()

    def one(job):
        it, c = job
        if gate and not gate():  # plan usage too high: record an error so a later run picks this item up
            r = {"answer": None, "input_tokens": None, "output_tokens": None, "ms": 0, "error": "usage gate closed"}
        else:
            r = probe(c, (it.get("question") or it.get("prompt")) + suffix)
        if score and not r.get("error"):  # noqa: the probe may have been skipped by the gate
            try:
                ok = bool(score(it, r.get("answer") or ""))
            except Exception as e:  # recorded as an error, so the next run retries this item
                r = {**r, "error": f"scoring: {e}"[:300]}
        row = {"id": it["id"], "kind": it.get("kind", "offtopic"), "condition": c, **r,
               "hit": None if r.get("error") else (ok if score else hit(r.get("answer"), it.get("answer_terms", [])))}
        with lock, out.open("a") as f:
            f.write(json.dumps(row) + "\n")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))


BATCH_HEAD = ("Answer each question from what you already know about me. Do not search the web. If you do not know "
              "one, answer UNKNOWN for it. Number your answers.\n\n")


def run_batched(items: list[dict], conditions: list[str], probe, out: Path, size: int = 5, workers: int = 4) -> None:
    """The recall protocol's format: several questions in one session. Each question is scored on the whole reply
    (answer terms are distinct across the bench, so one answer cannot score another question)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _done(out)
    groups = [items[i:i + size] for i in range(0, len(items), size)]
    todo = [(g, c) for g in groups for c in conditions if not all((it["id"], c) in done for it in g)]
    lock = threading.Lock()

    def one(job):
        g, c = job
        r = probe(c, BATCH_HEAD + "\n".join(f"{i}. {it['question']}" for i, it in enumerate(g, 1)))
        with lock, out.open("a") as f:
            for it in g:
                f.write(json.dumps({"id": it["id"], "kind": it.get("kind"), "condition": c, **r, "batch": len(g),
                                    "hit": None if r.get("error") else hit(r.get("answer"), it["answer_terms"])}) + "\n")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))


def _latest(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["id"], r["condition"]): r for r in rows if not r.get("error")}


def summarize(rows: list[dict], ref: str = "hook") -> dict:
    latest = _latest(rows)
    conds = sorted({c for _, c in latest})
    ids = sorted({i for i, _ in latest})
    out = {"n_items": len(ids), "conditions": {}, "vs_ref": {}, "ref": ref}
    for c in conds:
        rs = [latest[(i, c)] for i in ids if (i, c) in latest]
        k = sum(bool(r["hit"]) for r in rs)
        kinds = {}
        for r in rs:
            kinds.setdefault(r["kind"], []).append(bool(r["hit"]))
        toks = [r["input_tokens"] for r in rs if r.get("input_tokens") is not None]
        out["conditions"][c] = {"n": len(rs), "hits": k, "rate": k / len(rs) if rs else 0.0, "ci": wilson(k, len(rs)),
                                "by_kind": {kk: sum(v) / len(v) for kk, v in sorted(kinds.items())},
                                "mean_input_tokens": statistics.mean(toks) if toks else None}
    for c in conds:
        if c == ref:
            continue
        both = [i for i in ids if (i, c) in latest and (i, ref) in latest]
        d, lo, hi = paired_diff([bool(latest[(i, c)]["hit"]) for i in both], [bool(latest[(i, ref)]["hit"]) for i in both])
        out["vs_ref"][c] = {"n": len(both), "diff": d, "lo": lo, "hi": hi}
    return out


def usage_gate(path: Path, ceiling: float = 70):
    """Pause at a plan-usage ceiling when a usage file exists (the author's status line writes one); else no gate."""
    from um.gate import UsageGate
    return UsageGate(ceiling, 900, path).is_open if Path(path).exists() else None


def main(argv=None) -> None:
    from um.bench.cc_run import CONDITIONS, make_workdir, run_probe
    from um.bench.recall_data import load_offtopic, load_questions
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=Path, default=Path("bench/recall"))
    ap.add_argument("--split", default="test")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--runs", type=Path, default=Path("/tmp/um-recall-runs"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", choices=["questions", "implicit"], default="questions")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--project-md", type=Path, default=None, help="a project CLAUDE.md the sessions sit in")
    ap.add_argument("--batch", type=int, default=0, help="questions per session (the recall protocol's format)")
    ap.add_argument("--usage-file", type=Path, default=Path.home() / ".claude/usage-now.json",
                    help="plan-usage samples; runs pause at 70%% five-hour usage when this file exists")
    a = ap.parse_args(argv)
    CONDITIONS = tuple(a.conditions.split(","))
    work = {c: make_workdir(c, a.bench / "profile", a.runs, a.project_md) for c in CONDITIONS}
    probe = lambda c, prompt: run_probe(work[c], prompt, model=a.model)
    gate = usage_gate(a.usage_file)
    if a.set == "implicit":  # tasks that never ask about the user; a judge checks the stored fact was respected
        from um.llm_sub import ClaudeCodeLLM
        items = [dict(json.loads(x), kind="implicit") for x in (a.bench / "implicit.jsonl").read_text().splitlines()
                 if x.strip() and json.loads(x).get("split") == a.split]
        grader = ClaudeCodeLLM()
        out = a.out.with_suffix(".jsonl")
        run(items, list(CONDITIONS), probe, out, a.workers, suffix="", score=lambda it, ans: judge(it, ans, grader),
            gate=gate)
        summary = summarize([json.loads(x) for x in out.read_text().splitlines() if x.strip()])
        summary.update(model=a.model, judge="claude-haiku-5-5")
        Path(f"{a.out}-summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        return
    if a.batch:
        run_batched(load_questions(a.bench, a.split), list(CONDITIONS), probe, a.out.with_suffix(".jsonl"), a.batch,
                    a.workers)
        summary = summarize([json.loads(x) for x in a.out.with_suffix(".jsonl").read_text().splitlines() if x.strip()])
        summary.update(model=a.model, batch=a.batch)
        Path(f"{a.out}-summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        return
    run(load_questions(a.bench, a.split), list(CONDITIONS), probe, a.out.with_suffix(".jsonl"), a.workers, gate=gate)
    off = [o for o in load_offtopic(a.bench) if o.get("split", a.split) == a.split]
    run(off, ["index", "hook"], probe, Path(f"{a.out}-offtopic.jsonl"), a.workers, suffix="", gate=gate)
    rows = [json.loads(x) for x in a.out.with_suffix(".jsonl").read_text().splitlines() if x.strip()]
    summary = summarize(rows)
    offrows = list(_latest([json.loads(x) for x in Path(f"{a.out}-offtopic.jsonl").read_text().splitlines()]).values())
    summary["offtopic_mean_input_tokens"] = {c: statistics.mean(r["input_tokens"] for r in offrows if r["condition"] == c
                                                                and r.get("input_tokens") is not None)
                                             for c in ("index", "hook")}
    summary["model"] = a.model
    Path(f"{a.out}-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
