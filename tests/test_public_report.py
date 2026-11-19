import json

import pytest

from um.bench.public import report as rp


def _write(out, rows, compiles=None, setup=None):
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for key, passes in (compiles or {}).items():
        d = out / "stores" / key / "b"
        d.mkdir(parents=True)
        (d / "compile.jsonl").write_text("".join(json.dumps(p) + "\n" for p in passes))
    for key, gen in (setup or {}).items():
        (out / "stores" / key).mkdir(parents=True, exist_ok=True)
        (out / "stores" / key / "pref_generation.json").write_text(json.dumps(gen))


def row(item, cond, correct, inp=1000, outp=50, **kw):
    return {"bench": "x", "item": item, "condition": cond, "correct": correct, "outcome": "ok", "answer": "a",
            "input_tokens": inp, "output_tokens": outp, "context_chars": 10, "usd": 0.0, "backend": "api",
            "judge_input_tokens": 300, "judge_output_tokens": 10, "judge_usd": 0.0, **kw}


def p(lines_before, inp, outp=500, applied=10, outcome="ok"):
    return {"batch": 1, "outcome": outcome, "proposed": applied, "applied": applied, "decisions": {"apply": applied},
            "held_by_cap": 0, "over_deployed_cap": max(0, applied - 5), "lines_before": lines_before,
            "lines_after": lines_before + applied, "input_tokens": inp, "output_tokens": outp, "backend": "subscription"}


def test_summary_scores_each_condition_with_its_n(tmp_path):
    _write(tmp_path, [row("i1", "none", False), row("i2", "none", True), row("i1", "profile-hook", True),
                      row("i2", "profile-hook", None)],
           compiles={"i1": [p(0, 8000)], "i2": [p(0, 9000, outcome="compile_failed", applied=0)]})
    s = rp.summarize(tmp_path)
    assert s["conditions"]["none"] == {**s["conditions"]["none"], "n": 2, "correct": 1, "ungraded": 0, "accuracy": 0.5}
    assert s["conditions"]["profile-hook"]["ungraded"] == 1 and s["conditions"]["profile-hook"]["accuracy"] == 0.5
    c = s["compile"]
    assert c["profiles"] == 2 and c["passes"] == 2 and c["outcomes"] == {"ok": 1, "compile_failed": 1}
    assert c["input_tokens"] == 17000 and c["applied"] == 10 and c["over_deployed_cap"] == 5


def test_api_cost_of_a_call_uses_long_prompt_pricing():
    short = rp.call_usd("claude-haiku-5-5", 10_000, 100)
    long = rp.call_usd("claude-haiku-5-5", 120_000, 100)
    assert long > 12 * short   # past 100k tokens the whole prompt is priced higher


def test_per_item_profile_and_scaling(tmp_path):
    _write(tmp_path, [row("i1", "none", True, inp=2000), row("i2", "none", True, inp=4000)],
           compiles={"i1": [p(0, 10_000), p(10, 20_000)], "i2": [p(0, 30_000)]},
           setup={"i1": {"input_tokens": 100, "output_tokens": 200}, "i2": {"input_tokens": 100, "output_tokens": 200}})
    u = rp.unit_costs(tmp_path, "claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
    assert u["items"] == 2 and u["profiles"] == 2
    assert u["compile_tokens_per_profile"] == {"input": 30_000, "output": 750}
    assert u["answer_tokens_per_item"]["none"]["input"] == 3000
    e = rp.scale(u, n_items=100, n_profiles=100)
    assert e["compile_tokens"]["input"] == 3_000_000
    assert e["usd_api_if_compile_on_api"] == pytest.approx(e["usd_api_as_piloted"] + e["usd_compile_on_api"])
    assert e["usd_compile_on_api"] == pytest.approx(100 * rp.call_usd("claude-sonnet-5-5", 15_000, 375) * 2)


def test_chain_estimate_extrapolates_compile_input_from_store_size():
    passes = [p(0, 5000), p(50, 6000), p(100, 7000)]          # 20 tokens a line, 5000 base
    est = rp.chain_estimate(passes, n_passes=10, lines_per_pass=50)
    assert est["input"] == pytest.approx(sum(5000 + 20 * 50 * i for i in range(10)))
    assert est["max_request"] == pytest.approx(5000 + 20 * 450)
