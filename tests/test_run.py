import json

import pytest

from conftest import CountingFakeLLM
from um.bench.report import build_report
from um.bench.run import counts_for, run
from um.llm import FakeLLM, Reply


def rows(path):
    return [json.loads(line) for line in (path / "results.jsonl").read_text().splitlines()]


def test_counts_scale_to_the_requested_size():
    assert counts_for(100) == {"knowledge-update": 40, "temporal-reasoning": 30, "abstention": 20, "multi-session": 10}
    assert sum(counts_for(5).values()) == 5 and counts_for(1) == {"knowledge-update": 1}
    assert counts_for(3) == {"knowledge-update": 1, "temporal-reasoning": 1, "abstention": 1}


def test_rerun_skips_finished_pairs(tmp_path, tiny_data):
    llm = CountingFakeLLM()
    run(tiny_data, tmp_path, arms=["z"], n=3, llm=llm)
    first = llm.calls
    run(tiny_data, tmp_path, arms=["z"], n=3, llm=llm)
    assert llm.calls == first and len(rows(tmp_path)) == 3


def test_adding_an_arm_reuses_the_written_store(tmp_path, tiny_data):
    llm = CountingFakeLLM()
    run(tiny_data, tmp_path, arms=["z"], n=1, llm=llm)   # writer + answer + judge
    after_z = llm.calls
    run(tiny_data, tmp_path, arms=["z", "a"], n=1, llm=llm)   # arm pass + answer + judge, no second writer
    assert llm.calls - after_z == 3 and {r["arm"] for r in rows(tmp_path)} == {"z", "a"}


def test_refusal_is_counted_not_judged(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=FakeLLM([Reply("", "refusal", 5, 0)]))
    (row,) = rows(tmp_path)
    assert row["outcome"] == "refusal" and row["correct"] is None and row["arm"] == "full"


def test_rows_carry_backend_tokens_and_type(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=FakeLLM([Reply("Brightline", "end_turn", 50, 5, backend="subscription"),
                                                              Reply("yes", "end_turn", 20, 1)]))
    (row,) = rows(tmp_path)
    assert row["correct"] is True and row["backend"] == "subscription" and row["qtype"] == "knowledge-update"
    assert (row["input_tokens"], row["output_tokens"]) == (70, 6) and row["response"] == "Brightline"


def test_an_item_that_raises_is_logged_and_left_for_the_next_run(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=FakeLLM([]))   # script exhausted -> error
    assert not (tmp_path / "results.jsonl").exists() or rows(tmp_path) == []
    assert "ku01" in (tmp_path / "errors.jsonl").read_text()


def test_report_counts_outcomes_and_refuses_private_paths(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["z", "full"], n=3, llm=CountingFakeLLM())
    text = build_report(tmp_path)
    for needle in ("Sample: 3 questions", "| z |", "| full |", "claude-haiku-5-5", "Not run"):
        assert needle in text
    private = tmp_path / "data" / "private" / "x"
    private.mkdir(parents=True)
    with pytest.raises(SystemExit):
        build_report(private)


def test_limit_stops_after_that_many_questions_with_work_left(tmp_path, tiny_data):
    llm = CountingFakeLLM()
    run(tiny_data, tmp_path, arms=["full"], n=3, llm=llm, limit=2)
    assert len(rows(tmp_path)) == 2
    run(tiny_data, tmp_path, arms=["full"], n=3, llm=llm, limit=2)
    assert len(rows(tmp_path)) == 3


def test_report_includes_judge_check_and_run_notes_when_present(tmp_path, tiny_data):
    import json as _json
    run(tiny_data, tmp_path, arms=["z"], n=3, llm=CountingFakeLLM(), meta={"notes": ["Two invocations wrote into this folder."]})
    assert "Judge check" not in build_report(tmp_path)
    (tmp_path / "judge_check.json").write_text(_json.dumps(
        {"checked_by": "a reviewer", "n": 20, "agree": 18, "notes": ["Both disagreements were correct answers marked wrong."]}))
    text = build_report(tmp_path)
    assert "## Judge check" in text and "18 of 20" in text and "a reviewer" in text
    assert "Both disagreements were correct answers marked wrong." in text
    assert "Two invocations wrote into this folder." in text


def test_judge_failure_is_its_own_outcome_not_a_wrong_answer(tmp_path, tiny_data):
    for n, verdict in enumerate((Reply("", "max_tokens", 5, 0), Reply("maybe", "end_turn", 5, 1))):
        out = tmp_path / str(n)
        run(tiny_data, out, arms=["full"], n=1, llm=FakeLLM([Reply("Brightline", "end_turn", 5, 1), verdict]))
        (row,) = rows(out)
        assert row["outcome"] == "judge_failed" and row["correct"] is None
        assert "judge failed" in build_report(out)


def test_rows_record_which_backend_judged(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=FakeLLM([Reply("Brightline", "end_turn", 5, 1, backend="subscription"),
                                                              Reply("yes", "end_turn", 5, 1, backend="api")]))
    (row,) = rows(tmp_path)
    assert (row["backend"], row["judge_backend"]) == ("subscription", "api")


def test_report_refuses_duplicate_pairs(tmp_path, tiny_data):
    run(tiny_data, tmp_path, arms=["z"], n=1, llm=CountingFakeLLM())
    f = tmp_path / "results.jsonl"
    f.write_text(f.read_text() * 2)
    with pytest.raises(SystemExit, match="duplicate"):
        build_report(tmp_path)


def test_a_torn_last_line_is_dropped_on_resume(tmp_path, tiny_data):
    llm = CountingFakeLLM()
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=llm)
    f = tmp_path / "results.jsonl"
    f.write_text(f.read_text() + '{"qid": "zz", "ar')
    run(tiny_data, tmp_path, arms=["full"], n=3, llm=llm)
    assert len(rows(tmp_path)) == 3


def test_run_meta_keeps_every_invocation_and_earlier_notes(tmp_path, tiny_data):
    import json as _json
    run(tiny_data, tmp_path, arms=["z"], n=1, llm=CountingFakeLLM(), meta={"notes": ["first note"], "cap_usd": 1.0})
    run(tiny_data, tmp_path, arms=["full"], n=1, llm=CountingFakeLLM(), meta={"cap_usd": 2.0})
    meta = _json.loads((tmp_path / "run_meta.json").read_text())
    assert [i["arms"] for i in meta["invocations"]] == [["z"], ["full"]]
    assert [i["cap_usd"] for i in meta["invocations"]] == [1.0, 2.0] and meta["notes"] == ["first note"]
