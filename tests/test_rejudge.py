import json

import pytest

from um.bench import rejudge as rj
from um.bench.public import prefeval as pe
from um.bench.recall_run import JUDGE
from um.llm import FakeLLM, Reply


def ok(text):
    return Reply(text, "end_turn", 100, 20, backend="openai")


# --- statistics ---------------------------------------------------------------------------------------


def test_kappa_perfect_chance_and_degenerate():
    assert rj.kappa([True, False, True, False], [True, False, True, False]) == pytest.approx(1.0)
    assert rj.kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)
    # 3 of 4 agree, marginals 0.5/0.5 and 0.75/0.25: po=.75, pe=.5 -> .5
    assert rj.kappa([True, True, False, False], [True, True, True, False]) == pytest.approx(0.5)
    assert rj.kappa([True, True], [True, True]) is None  # one class only: kappa undefined


# --- recall implicit --------------------------------------------------------------------------------


def implicit_fixture(tmp_path):
    src = tmp_path / "x-implicit.jsonl"
    rows = [{"id": "i1", "kind": "implicit", "condition": "none", "answer": "plain", "error": None, "hit": False},
            {"id": "i1", "kind": "implicit", "condition": "hook", "answer": "with test", "error": None, "hit": True},
            {"id": "i2", "kind": "implicit", "condition": "hook", "answer": None, "error": "boom", "hit": None}]
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    bench = tmp_path / "implicit.jsonl"
    bench.write_text(json.dumps({"id": "i1", "check": "Does it write a test?"}) + "\n"
                     + json.dumps({"id": "i2", "check": "Other?"}) + "\n")
    return src, bench


def test_implicit_rejudge_uses_the_same_prompt_and_writes_rows_and_summary(tmp_path):
    src, bench = implicit_fixture(tmp_path)
    llm = FakeLLM([ok("NO. none"), ok("NO. it does not")])
    out = rj.run_implicit(src, bench, llm, "gpt-x", workers=1)
    assert out == tmp_path / "x-implicit-openai.jsonl"
    calls = sorted(llm.calls, key=lambda c: c["user"])
    assert calls[0]["system"] == JUDGE and calls[0]["model"] == "gpt-x"
    assert calls[0]["user"] == "Question: Does it write a test?\n\nResponse:\nplain"
    rows = {(r["id"], r["condition"]): r for r in map(json.loads, out.read_text().splitlines())}
    assert set(rows) == {("i1", "none"), ("i1", "hook")}          # error rows are not rejudged
    assert rows[("i1", "hook")]["haiku"] is True and rows[("i1", "hook")]["openai"] is False
    s = json.loads((tmp_path / "x-implicit-openai-summary.json").read_text())
    assert s["judge_model"] == "gpt-x" and s["reference_judge"] == "claude-haiku-5-5"
    assert s["conditions"]["hook"] == {"n": 1, "openai": 0, "haiku": 1, "openai_rate": 0.0, "haiku_rate": 1.0,
                                       "agree": 0, "agreement": 0.0, "kappa": 0.0, "judge_not_ok": 0}
    assert s["overall"]["n"] == 2 and s["overall"]["agree"] == 1 and s["overall"]["agreement"] == 0.5


def test_implicit_raises_the_output_floor_for_reasoning_tokens(tmp_path):
    src, bench = implicit_fixture(tmp_path)
    seen = []

    class Spy(FakeLLM):
        def complete(self, **kw):
            seen.append(kw["max_tokens"])
            return super().complete(**kw)

    rj.run_implicit(src, bench, Spy([ok("YES"), ok("YES")]), "gpt-x", workers=1, min_output_tokens=1000)
    assert seen == [1000, 1000]


def test_rerun_resumes_and_incomplete_judgements_are_kept_out_of_agreement(tmp_path):
    src, bench = implicit_fixture(tmp_path)
    rj.run_implicit(src, bench, FakeLLM([ok("YES"), Reply("", "max_tokens", 100, 1000)]), "gpt-x", workers=1)
    rows = [json.loads(x) for x in (tmp_path / "x-implicit-openai.jsonl").read_text().splitlines()]
    assert sorted(r["judge_outcome"] for r in rows) == ["max_tokens", "ok"]
    s = json.loads((tmp_path / "x-implicit-openai-summary.json").read_text())
    assert s["overall"]["n"] == 1 and s["overall"]["judge_not_ok"] == 1
    # a second run retries only the incomplete one
    llm = FakeLLM([ok("YES")])
    rj.run_implicit(src, bench, llm, "gpt-x", workers=1)
    assert len(llm.calls) == 1
    s = json.loads((tmp_path / "x-implicit-openai-summary.json").read_text())
    assert s["overall"]["n"] == 2 and s["overall"]["judge_not_ok"] == 0


# --- PrefEval -------------------------------------------------------------------------------------------


def prefeval_root(tmp_path):
    root = tmp_path / "prefeval"
    d = root / "benchmark_dataset" / "explicit_preference"
    d.mkdir(parents=True)
    (d / "topic.json").write_text(json.dumps([{"preference": "I hate cilantro", "question": "Taco recipe?"}]))
    et = root / "error_type"
    et.mkdir()
    for check, f in pe.CHECKS.items():
        (et / f).write_text(f"{check}: {{preference}} | {{question}} | {{end_generation}} | {{assistant_restatement}}")
    return root


def test_prefeval_rejudge_runs_the_four_checks_and_scores_like_the_original(tmp_path):
    root = prefeval_root(tmp_path)
    src = tmp_path / "run"
    src.mkdir()
    base = {"bench": "prefeval", "item": "topic:0", "acknow": "Yes", "violate": "No", "hallucinate": "No",
            "helpful": "Yes"}
    (src / "results.jsonl").write_text(
        json.dumps({**base, "condition": "none", "answer": "Use cilantro", "correct": False}) + "\n"
        + json.dumps({**base, "condition": "hook", "answer": "", "correct": False}) + "\n")
    llm = FakeLLM([ok("<answer>Yes</answer><preference>no cilantro</preference>"), ok("<answer>No</answer>"),
                   ok("<answer>No</answer>"), ok("<answer>Yes</answer>")])
    out = rj.run_prefeval(src, root, llm, "gpt-x", workers=1)
    assert out == src / "results-openai.jsonl"
    assert [c["label"] for c in llm.calls] == [f"rejudge:prefeval:{c}" for c in pe.CHECKS]
    assert all(c["system"] == pe.JUDGE_SYSTEM and c["model"] == "gpt-x" for c in llm.calls)
    assert llm.calls[0]["user"] == "acknow: {preference} | Taco recipe? | Use cilantro | {assistant_restatement}"
    assert llm.calls[2]["user"] == "hallucinate: I hate cilantro | {question} | {end_generation} | no cilantro"
    rows = {r["condition"]: r for r in map(json.loads, out.read_text().splitlines())}
    assert rows["none"]["openai"] is True and rows["none"]["haiku"] is False
    assert rows["none"]["checks"]["violate"] == "No"
    assert rows["hook"]["openai"] is False and rows["hook"]["judge_outcome"] == "empty_answer"  # not judged
    s = json.loads((src / "results-openai-summary.json").read_text())
    assert s["conditions"]["none"]["openai_rate"] == 1.0 and s["overall"]["n"] == 2
    assert s["checks"]["violation"]["n"] == 1 and s["checks"]["violation"]["agree"] == 1


def test_dry_run_counts_and_costs_without_calling(tmp_path, capsys):
    src, bench = implicit_fixture(tmp_path)

    class Boom:
        def complete(self, **kw):
            raise AssertionError("dry run must not call")

    est = rj.estimate_implicit(src, bench, "gpt-6.2-sol", est_output_tokens=400)
    assert est["items"] == 2 and est["calls"] == 2
    assert est["usd"] > 0 and est["worst_case_usd"] >= est["usd"]
    assert not (tmp_path / "x-implicit-openai.jsonl").exists()
