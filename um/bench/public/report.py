"""Summaries of a public-benchmark run folder, and cost estimates for larger runs from what a pilot used.

    python -m um.bench.public.report DIR          # DIR holds prefeval/, longmemeval/, mab/ run folders

Writes DIR/summary.json and DIR/estimate.json. Dollar figures are API list prices from um/budget.py (Haiku 5.5's
higher rate for prompts over 100k tokens included); a subscription call costs $0 of API but uses plan usage,
which is given here as tokens only.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from um.budget import cost_usd

PREFEVAL_FLAGS = ("acknowledgement", "violation", "error_unhelpful", "error_inconsistent",
                  "hallucination_of_preference_violation", "preference_unaware_violation")


def call_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    return cost_usd(model, int(input_tokens), int(output_tokens))


def _rows(out: Path) -> list[dict]:
    f = Path(out) / "results.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []


def _compiles(out: Path) -> dict[str, list[dict]]:
    found = {}
    for f in sorted((Path(out) / "stores").glob("*/b/compile.jsonl")):
        found[f.parent.parent.name] = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    return found


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def summarize(out: Path) -> dict:
    rows = _rows(out)
    by = defaultdict(list)
    for r in rows:
        by[r["condition"]].append(r)
    conds = {}
    for c, rs in by.items():
        correct = sum(1 for r in rs if r.get("correct") is True)
        conds[c] = {"n": len(rs), "correct": correct, "ungraded": sum(1 for r in rs if r.get("correct") is None),
                    "accuracy": correct / len(rs), "mean_input_tokens": round(_mean(r["input_tokens"] for r in rs)),
                    "mean_context_chars": round(_mean(r["context_chars"] for r in rs)),
                    "outcomes": dict(Counter(r["outcome"] for r in rs))}
        if any("acknowledgement" in r for r in rs):
            conds[c]["prefeval"] = {k: sum(1 for r in rs if r.get(k)) for k in PREFEVAL_FLAGS}
    passes = [p for ps in _compiles(out).values() for p in ps]
    decisions: Counter = Counter()
    for p in passes:
        decisions.update(p.get("decisions") or {})
    profiles = _compiles(out)
    compile_ = {"profiles": len(profiles), "passes": len(passes),
                "outcomes": dict(Counter(p["outcome"] for p in passes)),
                "input_tokens": sum(p["input_tokens"] for p in passes),
                "output_tokens": sum(p["output_tokens"] for p in passes),
                "proposed": sum(p.get("proposed", 0) for p in passes), "applied": sum(p.get("applied", 0) for p in passes),
                "decisions": dict(decisions), "held_by_cap": sum(p.get("held_by_cap", 0) for p in passes),
                "over_deployed_cap": sum(p.get("over_deployed_cap", 0) for p in passes),
                "profile_lines": [ps[-1].get("lines_after", 0) for ps in profiles.values() if ps]}
    errors = Path(out) / "errors.jsonl"
    return {"items": len({r["item"] for r in rows}), "conditions": dict(sorted(conds.items())), "compile": compile_,
            "errors": len(errors.read_text().splitlines()) if errors.exists() else 0}


def unit_costs(out: Path, answer_model: str, compile_model: str, judge_model: str) -> dict:
    """What one item, one profile and one answer used in the pilot, in tokens and API dollars."""
    rows, profiles = _rows(out), _compiles(out)
    items = len({r["item"] for r in rows})
    by = defaultdict(list)
    for r in rows:
        by[r["condition"]].append(r)
    passes = [p for ps in profiles.values() for p in ps]
    setup = [json.loads(f.read_text()) for f in sorted((Path(out) / "stores").glob("*/pref_generation.json"))]
    n_prof = max(len(profiles), 1)
    return {
        "items": items, "profiles": len(profiles),
        "answer_tokens_per_item": {c: {"input": _mean(r["input_tokens"] for r in rs),
                                       "output": _mean(r["output_tokens"] for r in rs)} for c, rs in by.items()},
        "answer_usd_per_item": {c: _mean(call_usd(answer_model, r["input_tokens"], r["output_tokens"]) for r in rs)
                                for c, rs in by.items()},
        "judge_tokens_per_answer": {"input": _mean(r.get("judge_input_tokens", 0) for r in rows),
                                    "output": _mean(r.get("judge_output_tokens", 0) for r in rows)},
        "judge_usd_per_answer": _mean(call_usd(judge_model, r.get("judge_input_tokens", 0), r.get("judge_output_tokens", 0))
                                      for r in rows),
        "compile_tokens_per_profile": {"input": sum(p["input_tokens"] for p in passes) / n_prof,
                                       "output": sum(p["output_tokens"] for p in passes) / n_prof},
        "compile_usd_per_profile": sum(call_usd(compile_model, p["input_tokens"], p["output_tokens"]) for p in passes) / n_prof,
        "setup_tokens_per_item": {"input": _mean(s.get("input_tokens", 0) for s in setup),
                                  "output": _mean(s.get("output_tokens", 0) for s in setup)},
        "setup_usd_per_item": _mean(call_usd(answer_model, s.get("input_tokens", 0), s.get("output_tokens", 0)) for s in setup),
    }


def scale(u: dict, n_items: int, n_profiles: int, conditions: list[str] | None = None) -> dict:
    conds = conditions or list(u["answer_tokens_per_item"])
    k = len(conds)
    ans_in = sum(u["answer_tokens_per_item"][c]["input"] for c in conds) * n_items
    ans_out = sum(u["answer_tokens_per_item"][c]["output"] for c in conds) * n_items
    j_in, j_out = u["judge_tokens_per_answer"]["input"] * k * n_items, u["judge_tokens_per_answer"]["output"] * k * n_items
    s_in, s_out = u["setup_tokens_per_item"]["input"] * n_items, u["setup_tokens_per_item"]["output"] * n_items
    c_in, c_out = u["compile_tokens_per_profile"]["input"] * n_profiles, u["compile_tokens_per_profile"]["output"] * n_profiles
    api = (sum(u["answer_usd_per_item"][c] for c in conds) + u["judge_usd_per_answer"] * k + u["setup_usd_per_item"]) * n_items
    comp = u["compile_usd_per_profile"] * n_profiles
    return {"items": n_items, "profiles": n_profiles,
            "answer_tokens": {"input": round(ans_in), "output": round(ans_out)},
            "judge_tokens": {"input": round(j_in), "output": round(j_out)},
            "setup_tokens": {"input": round(s_in), "output": round(s_out)},
            "compile_tokens": {"input": round(c_in), "output": round(c_out)},
            "usd_api_as_piloted": api, "usd_compile_on_api": comp, "usd_api_if_compile_on_api": api + comp,
            "tokens_if_all_subscription": round(ans_in + ans_out + j_in + j_out + s_in + s_out + c_in + c_out)}


def chain_estimate(passes: list[dict], n_passes: int, lines_per_pass: float) -> dict:
    """Compile tokens for a longer chain: each request is a fixed part plus the store so far, fitted from the
    pilot's passes as input = a + b * lines_before (b = 0 when the pilot's store never grew)."""
    xs = [p["lines_before"] for p in passes]
    ys = [p["input_tokens"] for p in passes]
    mx, my = _mean(xs), _mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0
    a = my - b * mx
    sizes = [a + b * lines_per_pass * i for i in range(n_passes)]
    return {"input": sum(sizes), "output": _mean(p["output_tokens"] for p in passes) * n_passes,
            "max_request": sizes[-1] if sizes else 0.0, "a": a, "b": b, "passes": n_passes}


# ---------------------------------------------------------------- the pilot's estimate table

def estimate(pilot: Path, answer_model: str = "claude-haiku-5-5", compile_model: str = "claude-sonnet-5-5",
             judge_model: str = "claude-haiku-5-5", facts: dict | None = None, prefeval_hist: dict | None = None) -> dict:
    """Full-run estimates for each benchmark folder under `pilot`. `facts` maps MemoryAgentBench sources to their
    fact counts; `prefeval_hist` gives PrefEval's history tokens at 10 and 300 inter-turns."""
    pilot = Path(pilot)
    out: dict = {}
    if (pilot / "prefeval").exists():
        u = unit_costs(pilot / "prefeval", answer_model, compile_model, judge_model)
        out["prefeval"] = {"unit": u, "n100": scale(u, 100, 100), "n1000": scale(u, 1000, 1000)}
        if prefeval_hist and (pilot / "longmemeval").exists():
            out["prefeval"]["n1000_300_inter_turns"] = _prefeval_300(u, pilot, compile_model, answer_model, prefeval_hist)
    if (pilot / "longmemeval").exists():
        u = unit_costs(pilot / "longmemeval", answer_model, compile_model, judge_model)
        out["longmemeval"] = {"unit": u, "n100": scale(u, 100, 100), "n166": scale(u, 166, 166)}
    if (pilot / "mab").exists():
        u = unit_costs(pilot / "mab", answer_model, compile_model, judge_model)
        passes = [p for ps in _compiles(pilot / "mab").values() for p in ps]
        lines_per_pass = _mean(p["lines_after"] - p["lines_before"] for p in passes)
        chains = {}
        for src, n_facts in (facts or {}).items():
            ch = chain_estimate(passes, math.ceil(n_facts / 50), lines_per_pass)
            ch["usd_on_api"] = call_usd(compile_model, ch["input"], ch["output"])
            chains[src] = ch
        out["mab"] = {"unit": u, "n100_sh6k": scale(u, 100, 1), "chains": chains, "lines_per_pass": lines_per_pass}
    return out


def _prefeval_300(u: dict, pilot: Path, compile_model: str, answer_model: str, hist: dict) -> dict:
    """PrefEval at 300 inter-turns, by extrapolation: compile tokens per history token taken from LongMemEval's
    pilot (histories of similar length), the full-history answer priced at the history's length, other
    conditions as at 10 inter-turns."""
    lme_passes = [p for ps in _compiles(pilot / "longmemeval").values() for p in ps]
    ratio_in = sum(p["input_tokens"] for p in lme_passes) / max(sum(p["evidence_tokens_est"] for p in lme_passes), 1)
    ratio_out = sum(p["output_tokens"] for p in lme_passes) / max(sum(p["evidence_tokens_est"] for p in lme_passes), 1)
    v = json.loads(json.dumps(u))
    v["compile_tokens_per_profile"] = {"input": hist["300"] * ratio_in, "output": hist["300"] * ratio_out}
    v["compile_usd_per_profile"] = call_usd(compile_model, hist["300"] * ratio_in, hist["300"] * ratio_out)
    if "full-history" in v["answer_tokens_per_item"]:
        grow = hist["300"] - hist["10"]
        fh = v["answer_tokens_per_item"]["full-history"]
        fh["input"] += grow
        v["answer_usd_per_item"]["full-history"] = call_usd(answer_model, fh["input"], fh["output"])
    return scale(v, 1000, 1000)


def main(argv: list[str] | None = None) -> None:
    pilot = Path((argv or sys.argv[1:])[0])
    summary = {b: summarize(pilot / b) for b in ("prefeval", "longmemeval", "mab") if (pilot / b).exists()}
    (pilot / "summary.json").write_text(json.dumps(summary, indent=1))
    facts = hist = None
    meta = pilot / "estimate_inputs.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        facts, hist = m.get("mab_facts"), m.get("prefeval_history_tokens")
    (pilot / "estimate.json").write_text(json.dumps(estimate(pilot, facts=facts, prefeval_hist=hist), indent=1))
    print(json.dumps({b: {c: (v["correct"], v["n"]) for c, v in s["conditions"].items()} for b, s in summary.items()}))


if __name__ == "__main__":
    main()
