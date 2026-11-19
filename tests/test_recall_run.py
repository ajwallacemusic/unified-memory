import json

from um.bench.recall_run import hit, run, summarize


def test_hit_is_any_answer_term_case_insensitive():
    assert hit("Her name is kestrel-17.", ["KESTREL-17"]) and not hit("UNKNOWN", ["Kestrel"]) and not hit(None, ["x"])


def test_run_writes_one_row_per_item_and_condition_and_resumes(tmp_path):
    items = [{"id": "q1", "kind": "direct", "question": "a?", "answer_terms": ["yes"]},
             {"id": "q2", "kind": "paraphrase", "question": "b?", "answer_terms": ["no"]}]
    calls = []

    def probe(cond, prompt):
        calls.append((cond, prompt))
        return {"answer": "yes" if cond == "full" else "UNKNOWN", "input_tokens": 10, "output_tokens": 2,
                "ms": 5, "error": None}

    out = tmp_path / "rows.jsonl"
    run(items, ["none", "full"], probe, out, workers=2)
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(rows) == 4 and {(r["id"], r["condition"]) for r in rows} == {
        ("q1", "none"), ("q1", "full"), ("q2", "none"), ("q2", "full")}
    assert [r["hit"] for r in rows if r["id"] == "q1" and r["condition"] == "full"] == [True]
    assert all(c[1].endswith("answer UNKNOWN. Keep it to one or two sentences.") for c in calls)
    run(items, ["none", "full"], probe, out, workers=2)
    assert len(calls) == 4 and len(out.read_text().splitlines()) == 4


def test_errors_are_retried_on_the_next_run(tmp_path):
    items = [{"id": "q1", "kind": "direct", "question": "a?", "answer_terms": ["yes"]}]
    out = tmp_path / "rows.jsonl"
    run(items, ["none"], lambda c, p: {"answer": None, "input_tokens": None, "output_tokens": None, "ms": 1,
                                         "error": "boom"}, out)
    run(items, ["none"], lambda c, p: {"answer": "yes", "input_tokens": 1, "output_tokens": 1, "ms": 1,
                                         "error": None}, out)
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert [r["hit"] for r in rows if not r["error"]] == [True]


def test_summary_has_rates_intervals_and_paired_differences():
    rows = [{"id": f"q{i}", "kind": "direct", "condition": c, "hit": (c == "hook") or i % 2 == 0,
             "input_tokens": 100 if c == "full" else 10, "error": None}
            for i in range(10) for c in ("index", "hook", "full")]
    s = summarize(rows, ref="hook")
    assert s["conditions"]["hook"]["rate"] == 1.0 and s["conditions"]["index"]["rate"] == 0.5
    lo, hi = s["conditions"]["index"]["ci"]
    assert lo < 0.5 < hi
    d = s["vs_ref"]["index"]
    assert d["diff"] == -0.5 and d["lo"] <= -0.5 <= d["hi"]
    assert s["conditions"]["full"]["mean_input_tokens"] == 100
    assert s["conditions"]["index"]["by_kind"]["direct"] == 0.5


def test_a_custom_scorer_replaces_term_matching(tmp_path):
    items = [{"id": "i1", "kind": "implicit", "prompt": "plan dinner", "check": "avoids shellfish?"}]
    out = tmp_path / "rows.jsonl"
    run(items, ["hook"], lambda c, p: {"answer": "pasta", "input_tokens": 1, "output_tokens": 1, "ms": 1, "error": None},
        out, suffix="", score=lambda item, answer: item["check"] == "avoids shellfish?" and answer == "pasta")
    assert json.loads(out.read_text())["hit"] is True


def test_judge_reads_yes_or_no_from_the_first_word():
    from um.bench.recall_run import judge
    from um.llm import FakeLLM, Reply
    llm = FakeLLM([Reply("YES - it avoids it", "end_turn", 1, 1), Reply("No.", "end_turn", 1, 1)])
    item = {"check": "Does it avoid shellfish?"}
    assert judge(item, "pasta", llm) is True and judge(item, "shrimp", llm) is False
    assert "Does it avoid shellfish?" in llm.calls[0]["user"] and "pasta" in llm.calls[0]["user"]


def test_a_failing_scorer_records_an_error_to_retry(tmp_path):
    items = [{"id": "i1", "kind": "implicit", "prompt": "p", "check": "c"}]
    out = tmp_path / "rows.jsonl"

    def boom(item, answer):
        raise RuntimeError("judge down")
    run(items, ["hook"], lambda c, p: {"answer": "a", "input_tokens": 1, "output_tokens": 1, "ms": 1, "error": None},
        out, suffix="", score=boom)
    row = json.loads(out.read_text())
    assert row["hit"] is None and "judge down" in row["error"]


def test_batched_run_asks_several_questions_in_one_session_and_scores_each(tmp_path):
    from um.bench.recall_run import run_batched
    items = [{"id": f"q{i}", "kind": "direct", "question": f"Q{i}?", "answer_terms": [f"ans{i}"]} for i in range(5)]
    prompts = []

    def probe(c, prompt):
        prompts.append(prompt)
        return {"answer": "1. ans0 2. ans1 3. UNKNOWN", "input_tokens": 9, "output_tokens": 1, "ms": 1, "error": None}

    out = tmp_path / "rows.jsonl"
    run_batched(items, ["index"], probe, out, size=3)
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(prompts) == 2 and "1. Q0?" in prompts[0] and "3. Q2?" in prompts[0]
    assert {r["id"]: r["hit"] for r in rows} == {"q0": True, "q1": True, "q2": False, "q3": False, "q4": False}
    run_batched(items, ["index"], probe, out, size=3)
    assert len(prompts) == 2


def test_a_closed_usage_gate_records_errors_instead_of_running(tmp_path):
    items = [{"id": "q1", "kind": "direct", "question": "a?", "answer_terms": ["yes"]}]
    out = tmp_path / "rows.jsonl"
    calls = []
    run(items, ["none"], lambda c, p: calls.append(1) or {"answer": "yes", "input_tokens": 1, "output_tokens": 1,
                                                         "ms": 1, "error": None}, out, gate=lambda: False)
    assert calls == [] and "usage" in json.loads(out.read_text())["error"]


def test_the_usage_gate_applies_only_when_a_usage_file_exists(tmp_path):
    from um.bench.recall_run import usage_gate
    assert usage_gate(tmp_path / "missing.json") is None
    f = tmp_path / "u.json"
    f.write_text("{}")
    assert callable(usage_gate(f))
