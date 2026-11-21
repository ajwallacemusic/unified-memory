"""Re-score saved benchmark answers with a judge from another model family, and measure agreement with Haiku.

    .venv/bin/python -m um.bench.rejudge SOURCE [SOURCE ...] --api-cap 80 [--model gpt-6.2-sol] [--dry-run]

SOURCE is a public-bench run directory holding results.jsonl (PrefEval), a search-gate run directory
(LongMemEval, rows keyed by qid), or a recall-bench implicit .jsonl. The judge prompts are the ones the published runs used, unchanged: PrefEval's four checks
(um/bench/public/prefeval.py `judge`, prompt files read from --prefeval-root) and the recall bench's implicit
judge (um/bench/recall_run.py `judge`). Writes `<name>-openai.jsonl` beside the source (one row per answer; a
rerun resumes and retries judgements that did not finish) and `<name>-openai-summary.json`: per-condition scores
under both judges, and agreement with the Haiku verdicts (count, share, Cohen's kappa).

One difference, stated in the summary: the OpenAI judge's output limit is raised to at least --min-output-tokens
(default 1,000) because its hidden reasoning tokens count against that limit; the implicit judge's 100 would end
most calls before any text. A judgement that still comes back incomplete or refused is recorded, left out of the
agreement figures, counted as `judge_not_ok`, and retried on the next run.

Answers that were empty were never judged in the original run (scored as not following); they are carried over
with the same verdict and `judge_outcome: "empty_answer"`.
"""
from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from um.bench.judge import JUDGE_MAX_TOKENS as LME_JUDGE_MAX_TOKENS, judge_prompt as lme_judge_prompt, verdict_of
from um.bench.public import prefeval as pe
from um.bench.recall_run import JUDGE, judge as implicit_judge
from um.budget import cost_usd
from um.llm import outcome_of

REFERENCE = "claude-haiku-5-5"
IMPLICIT_MAX_TOKENS = 100       # recall_run.judge
JUDGED = ("ok", "empty_answer")
PREFEVAL_CHECK_FIELDS = ("acknowledgement", "violation", "hallucination", "error_unhelpful")


# --- statistics ---------------------------------------------------------------------------------------


def kappa(a: list[bool], b: list[bool]) -> float | None:
    """Cohen's kappa for two binary raters; None when chance agreement is 1 (both raters used one class)."""
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe_ = pa * pb + (1 - pa) * (1 - pb)
    return None if pe_ >= 1 else (po - pe_) / (1 - pe_)


def _agreement(pairs: list[tuple[bool, bool]], not_ok: int = 0) -> dict:
    o, h = [p[0] for p in pairs], [p[1] for p in pairs]
    n = len(pairs)
    agree = sum(x == y for x, y in pairs)
    return {"n": n, "openai": sum(o), "haiku": sum(h), "openai_rate": sum(o) / n if n else None,
            "haiku_rate": sum(h) / n if n else None, "agree": agree, "agreement": agree / n if n else None,
            "kappa": kappa(o, h), "judge_not_ok": not_ok}


def summarize(rows: list[dict], model: str, source: Path, floor: int) -> dict:
    conds = sorted({r["condition"] for r in rows})
    good = [r for r in rows if r["judge_outcome"] in JUDGED]
    out = {"source": str(source), "judge_model": model, "reference_judge": REFERENCE,
           "min_output_tokens": floor, "n_rows": len(rows),
           "unjudged_empty_answers": sum(r["judge_outcome"] == "empty_answer" for r in rows),
           "overall": _agreement([(r["openai"], r["haiku"]) for r in good], len(rows) - len(good)),
           "conditions": {c: _agreement([(r["openai"], r["haiku"]) for r in good if r["condition"] == c],
                                        sum(1 for r in rows if r["condition"] == c and r["judge_outcome"] not in JUDGED))
                          for c in conds}}
    checked = [r for r in good if r.get("haiku_checks") and r.get("derived")]
    if checked:
        out["checks"] = {f: _agreement([(bool(r["derived"][f]), bool(r["haiku_checks"][f])) for r in checked])
                         for f in PREFEVAL_CHECK_FIELDS}
    return out


# --- shared plumbing ------------------------------------------------------------------------------------


class _Recorder:
    """Fixes the model, raises the output floor, renames labels, and keeps each reply's outcome."""

    def __init__(self, llm, model: str, floor: int):
        self.llm, self.model, self.floor = llm, model, floor
        self.outcomes: list[str] = []

    def complete(self, *, model, system, user, max_tokens, label):
        r = self.llm.complete(model=self.model, system=system, user=user, max_tokens=max(max_tokens, self.floor),
                              label="re" + label if label.startswith("judge") else "rejudge:" + label)
        self.outcomes.append(outcome_of(r))
        return r


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()] if Path(path).exists() else []


def _latest(rows: list[dict], key) -> dict:
    return {key(r): r for r in rows}


def _paths(src: Path) -> tuple[Path, Path]:
    base = src / "results" if src.is_dir() else src.with_suffix("")
    return Path(f"{base}-openai.jsonl"), Path(f"{base}-openai-summary.json")


def _execute(todo: list, one, out: Path, workers: int) -> None:
    lock = threading.Lock()

    def run(job):
        row = one(job)
        with lock, out.open("a") as f:
            f.write(json.dumps(row) + "\n")

    with ThreadPoolExecutor(max(1, workers)) as ex:
        list(ex.map(run, todo))


def _finish(src: Path, out: Path, summary_path: Path, key, model: str, floor: int) -> Path:
    rows = list(_latest(_read(out), key).values())
    summary_path.write_text(json.dumps(summarize(rows, model, src, floor), indent=1) + "\n")
    return out


# --- recall bench, implicit set -----------------------------------------------------------------------------


def _implicit_inputs(src: Path, bench: Path):
    items = {r["id"]: r for r in _read(bench)}
    rows = [r for r in _latest(_read(src), lambda r: (r["id"], r["condition"])).values() if not r.get("error")]
    return items, rows


def _implicit_todo(src: Path, bench: Path) -> tuple[dict, list[dict]]:
    items, rows = _implicit_inputs(src, bench)
    out, _ = _paths(src)
    done = {(r["id"], r["condition"]) for r in _read(out) if r["judge_outcome"] in JUDGED}
    return items, [r for r in rows if (r["id"], r["condition"]) not in done]


def run_implicit(src: Path, bench: Path, llm, model: str, workers: int = 4, min_output_tokens: int = 1000) -> Path:
    src = Path(src)
    out, summary_path = _paths(src)
    items, todo = _implicit_todo(src, bench)

    def one(r):
        rec = _Recorder(llm, model, min_output_tokens)
        verdict = implicit_judge(items[r["id"]], r.get("answer") or "", rec, model=model)
        return {"id": r["id"], "condition": r["condition"], "haiku": bool(r["hit"]), "openai": verdict,
                "judge_outcome": rec.outcomes[-1]}

    _execute(todo, one, out, workers)
    return _finish(src, out, summary_path, lambda r: (r["id"], r["condition"]), model, min_output_tokens)


def estimate_implicit(src: Path, bench: Path, model: str, est_output_tokens: int = 400,
                      min_output_tokens: int = 1000) -> dict:
    items, todo = _implicit_todo(Path(src), bench)
    tin = sum(_tokens(JUDGE, f"Question: {items[r['id']]['check']}\n\nResponse:\n{r.get('answer') or ''}")
              for r in todo)
    return _estimate(model, len(todo), len(todo), tin, est_output_tokens,
                     max(IMPLICIT_MAX_TOKENS, min_output_tokens))


# --- PrefEval -----------------------------------------------------------------------------------------------


def _prefeval_todo(src: Path, root: Path):
    items = {i.id: i for i in pe.load(root)}
    rows = list(_latest(_read(src / "results.jsonl"), lambda r: (r["item"], r["condition"])).values())
    out, _ = _paths(src)
    done = {(r["item"], r["condition"]) for r in _read(out) if r["judge_outcome"] in JUDGED}
    return items, [r for r in rows if (r["item"], r["condition"]) not in done]


def run_prefeval(src: Path, root: Path, llm, model: str, workers: int = 4, min_output_tokens: int = 1000) -> Path:
    src = Path(src)
    out, summary_path = _paths(src)
    items, todo = _prefeval_todo(src, root)

    def one(r):
        base = {"item": r["item"], "condition": r["condition"], "haiku": bool(r.get("correct"))}
        answer = r.get("answer") or ""
        if not answer.strip():  # the original run scored these without judging (um/bench/public/run.py)
            return {**base, "openai": False, "judge_outcome": "empty_answer"}
        rec = _Recorder(llm, model, min_output_tokens)
        checks = pe.judge(items[r["item"]], answer, rec, model, root)
        s = pe.score(checks)
        bad = [o for o in rec.outcomes if o != "ok"]
        return {**base, "openai": s["preference_following"], "judge_outcome": bad[0] if bad else "ok",
                "checks": {k: checks[k] for k in pe.CHECKS},
                "derived": {f: s[f] for f in PREFEVAL_CHECK_FIELDS},
                "haiku_checks": {f: r.get(f) for f in PREFEVAL_CHECK_FIELDS}}

    _execute(todo, one, out, workers)
    return _finish(src, out, summary_path, lambda r: (r["item"], r["condition"]), model, min_output_tokens)


def estimate_prefeval(src: Path, root: Path, model: str, est_output_tokens: int = 400,
                      min_output_tokens: int = 1000) -> dict:
    items, todo = _prefeval_todo(Path(src), root)
    judged = [r for r in todo if (r.get("answer") or "").strip()]
    prompts = {c: pe._prompt(root, c) for c in pe.CHECKS}
    tin = 0
    for r in judged:
        it = items[r["item"]]
        for c, text in prompts.items():  # the preference stands in for the restatement the first check extracts
            text = (text.replace("{preference}", it.preference).replace("{question}", it.question)
                    .replace("{end_generation}", r["answer"]).replace("{assistant_restatement}", it.preference))
            tin += _tokens(pe.JUDGE_SYSTEM, text)
    return _estimate(model, len(todo), 4 * len(judged), tin, est_output_tokens,
                     max(pe.JUDGE_MAX_TOKENS, min_output_tokens))


# --- LongMemEval search gate ---------------------------------------------------------------------------------


def _lme_items(path: Path) -> dict:
    from um.bench import longmemeval as lm
    return {i.qid: i for i in lm.load(path)}


def _lme_todo(src: Path, data: Path):
    rows = [r for r in _latest(_read(src / "results.jsonl"), lambda r: (r["qid"], r["condition"])).values()
            if r.get("outcome") != "judge_failed"]   # never graded by Haiku either
    out, _ = _paths(src)
    done = {(r["qid"], r["condition"]) for r in _read(out) if r["judge_outcome"] in JUDGED}
    return _lme_items(data), [r for r in rows if (r["qid"], r["condition"]) not in done]


def run_lme(src: Path, data: Path, llm, model: str, workers: int = 4, min_output_tokens: int = 1000) -> Path:
    """The gate's own judge prompt (um/bench/judge.py, as used by um/bench/public/lme.py `grade`)."""
    src = Path(src)
    out, summary_path = _paths(src)
    items, todo = _lme_todo(src, data)

    def one(r):
        base = {"qid": r["qid"], "condition": r["condition"], "haiku": bool(r.get("correct"))}
        answer = r.get("answer") or ""
        if not answer.strip():   # the gate scored these without judging
            return {**base, "openai": False, "judge_outcome": "empty_answer"}
        rec = _Recorder(llm, model, min_output_tokens)
        reply = rec.complete(model=model, system="", user=lme_judge_prompt(items[r["qid"]], answer),
                             max_tokens=LME_JUDGE_MAX_TOKENS, label="judge:longmemeval")
        return {**base, "openai": verdict_of(reply.text), "judge_outcome": rec.outcomes[-1]}

    _execute(todo, one, out, workers)
    return _finish(src, out, summary_path, lambda r: (r["qid"], r["condition"]), model, min_output_tokens)


def estimate_lme(src: Path, data: Path, model: str, est_output_tokens: int = 400, min_output_tokens: int = 1000) -> dict:
    items, todo = _lme_todo(Path(src), data)
    judged = [r for r in todo if (r.get("answer") or "").strip()]
    tin = sum(_tokens(lme_judge_prompt(items[r["qid"]], r["answer"])) for r in judged)
    return _estimate(model, len(todo), len(judged), tin, est_output_tokens,
                     max(LME_JUDGE_MAX_TOKENS, min_output_tokens))


def _kind(src: Path) -> str:
    src = Path(src)
    if not src.is_dir():
        return "implicit"
    first = next(iter(_read(src / "results.jsonl")), {})
    return "lme" if "qid" in first else "prefeval"


# --- estimates and CLI --------------------------------------------------------------------------------------


def _tokens(*parts: str) -> int:
    return sum(len(p) for p in parts) // 4 + 10   # ~4 characters per token, plus message framing


def _estimate(model: str, items: int, calls: int, tin: int, est_out: int, max_out: int) -> dict:
    return {"model": model, "items": items, "calls": calls, "input_tokens": tin,
            "assumed_output_tokens_per_call": est_out, "output_tokens": calls * est_out,
            "usd": round(cost_usd(model, tin, calls * est_out), 4),
            "worst_case_usd": round(cost_usd(model, tin, calls * max_out), 4)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sources", nargs="+", type=Path)
    ap.add_argument("--model", default=None, help="default: $OPENAI_JUDGE_MODEL, else um.llm_openai.DEFAULT_MODEL")
    ap.add_argument("--prefeval-root", type=Path, default=Path("data/public/prefeval"))
    ap.add_argument("--lme-data", type=Path, default=Path("data/public/longmemeval/longmemeval_s_cleaned.json"))
    ap.add_argument("--implicit-bench", type=Path, default=Path("bench/recall/implicit.jsonl"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-output-tokens", type=int, default=1000)
    ap.add_argument("--est-output-tokens", type=int, default=400,
                    help="dry-run assumption per call, reasoning tokens included")
    ap.add_argument("--api-cap", type=float, help="hard API cap in dollars, whole ledger (required unless --dry-run)")
    ap.add_argument("--ledger", type=Path, default=Path("results/spend.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from um.llm_openai import OpenAILLM, default_model, register_prices, _env_prices
    model = a.model or default_model()
    register_prices(_env_prices())
    if a.dry_run:
        for s in a.sources:
            k = _kind(s)
            est = (estimate_lme(s, a.lme_data, model, a.est_output_tokens, a.min_output_tokens) if k == "lme" else
                   estimate_prefeval(s, a.prefeval_root, model, a.est_output_tokens, a.min_output_tokens)
                   if k == "prefeval" else
                   estimate_implicit(s, a.implicit_bench, model, a.est_output_tokens, a.min_output_tokens))
            print(json.dumps({"source": str(s), **est}))
        return
    if a.api_cap is None:
        ap.error("--api-cap is required for a real run")
    from um.budget import Budget
    llm = OpenAILLM(Budget(a.api_cap, a.ledger))
    for s in a.sources:
        k = _kind(s)
        out = (run_lme(s, a.lme_data, llm, model, a.workers, a.min_output_tokens) if k == "lme" else
               run_prefeval(s, a.prefeval_root, llm, model, a.workers, a.min_output_tokens) if k == "prefeval" else
               run_implicit(s, a.implicit_bench, llm, model, a.workers, a.min_output_tokens))
        print(_paths(s)[1].read_text())
        print(f"rows: {out}")


if __name__ == "__main__":
    main()
