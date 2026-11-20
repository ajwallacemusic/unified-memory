"""The conversation-search gate harness (Plan 5, Task 12). Synthetic items only; every model is a FakeLLM."""
import json
from pathlib import Path

import pytest

from um.bench import search_gate as sg
from um.bench.longmemeval import load, sample
from um.bench.public import lme
from um.bench.public.pipeline import Session
from um.llm import FakeLLM, Reply
import um.prompts

TINY = Path(__file__).parent / "data" / "lme_tiny.json"
MARK = "Zanzibar marimba"   # a phrase that sits only in the synthetic history


def _row(qid, qtype, sessions, answer_ids, question="What instrument did I start learning?"):
    return {"question_id": qid, "question_type": qtype, "question": question, "question_date": "2023/06/01 (Thu) 09:00",
            "answer": "violin", "answer_session_ids": answer_ids,
            "haystack_session_ids": [s[0] for s in sessions], "haystack_dates": [s[1] for s in sessions],
            "haystack_sessions": [[{"role": r, "content": c} for r, c in s[2]] for s in sessions]}


def _sessions():
    return [("s_old", "2023/03/02 (Thu) 10:00", [("user", "I bought a paddleboard for the lake."), ("assistant", "Fun!")]),
            ("s_ans", "2023/05/20 (Sat) 11:00", [("user", f"I started violin lessons, and my neighbour plays the {MARK}."),
                                                 ("assistant", "Violin is a great choice.")])]


def _lme_file(tmp_path, n_per_type=None):
    rows = []
    for qtype, n in (n_per_type or {"knowledge-update": 1}).items():
        for i in range(n):
            suffix = "_abs" if qtype == "abstention" else ""
            rows.append(_row(f"{qtype[:2]}{i:02d}{suffix}", "multi-session" if suffix else qtype, _sessions(), ["s_ans"]))
    p = tmp_path / "lme.json"
    p.write_text(json.dumps(rows))
    return p


ONE = {"knowledge-update": 1}
PARAMS = {"chunk_chars": 2000, "lead_chars": 300, "per_session": 2, "half_life_days": None}


def _rows(out):
    return [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines()]


def test_item_carries_answer_session_ids():
    items = {i.qid: i for i in load(TINY)}
    assert items["ku01"].answer_session_ids == ("s_b",)
    assert items["tr01"].answer_session_ids == ("t_a", "t_b")
    assert items["ms01_abs"].answer_session_ids == ()


def test_dev_items_and_sample_are_disjoint_and_cover(tmp_path):
    path = _lme_file(tmp_path, {"knowledge-update": 4, "temporal-reasoning": 4, "abstention": 4})
    counts = {"knowledge-update": 2, "temporal-reasoning": 1, "abstention": 1}
    test = {i.qid for i in sample(load(path), counts, 7)}
    dev = {i.qid for i in sg.dev_items(path, counts=counts, seed=7)}
    assert len(test) == 4 and len(dev) == 8
    assert not (test & dev)
    assert test | dev == {i.qid for i in load(path)}


def test_build_index_and_session_recall(tmp_path):
    sessions = [Session("a", "2023-03-02", (("user", "I bought a paddleboard."), ("assistant", "Nice."))),
                Session("b", "2023-05-20", (("assistant", "Hello again."), ("user", "I started violin lessons."),
                                            ("assistant", "Great."), ("assistant", "Practise daily.")))]
    idx = sg.build_index(sessions, tmp_path / "i.sqlite")
    hits = idx.search("violin lessons", limit=5)
    assert [h.native_id for h in hits] == ["b"]
    assert hits[0].surface == "bench" and hits[0].at == "2023-05-20"
    assert hits[0].chunk_key == "bench:b#t1#0" and "Practise daily." in hits[0].assistant_text
    assert sg.session_recall(idx, "violin lessons", {"b"}, 5)
    assert not sg.session_recall(idx, "violin lessons", {"a"}, 5)
    assert not sg.session_recall(idx, "the and of", {"b"}, 5)


def test_toolbox_contract(tmp_path):
    sessions = [Session("a", "2023-03-02", (("user", "paddleboard on the lake"), ("assistant", "ok"))),
                Session("b", "2023-05-20", (("user", "violin lessons"), ("assistant", "great")))]
    box = sg.SearchToolbox(sg.build_index(sessions, tmp_path / "i.sqlite"), params=PARAMS, now="2023-06-01T09:00:00")
    specs = box.specs()
    assert specs[0]["name"] == "conversation_search" and "input_schema" in specs[0] and "inputSchema" not in specs[0]
    assert box.retrieved == set() and box.calls == 0
    text = box.call("conversation_search", {"query": "violin"})
    assert isinstance(text, str) and text.startswith("Past-conversation search results.")
    assert box.retrieved == {"b"}
    assert box.call("conversation_search", {"query": "violin", "max_results": "lots"}).startswith("ERROR:")
    assert box.call("no_such_tool", {}).startswith("ERROR:")
    assert box.calls == 3


def test_search_condition_uses_tool_loop(tmp_path):
    path, out = _lme_file(tmp_path), tmp_path / "out"
    llm = FakeLLM([{"tool": "conversation_search", "args": {"query": "violin lessons"}},
                   Reply("You started violin.", "end_turn", 900, 40, usd=0.001),
                   Reply("yes", "end_turn", 50, 1, usd=0.0001)])
    sg.run_lme(path, out, llm, conditions=("search",), n=1, params=PARAMS, counts=ONE)
    (row,) = _rows(out)
    assert row["condition"] == "search" and row["tool_calls"] == 1 and row["correct"] is True
    assert row["retrieved_answer_session"] is True and row["outcome"] == "ok"
    assert row["input_tokens"] == 900 and row["usd"] == pytest.approx(0.0011)
    call = llm.calls[0]
    assert call["kind"] == "run_tools" and call["label"] == "answer:lme-search"
    assert lme.SOURCES["search"] in call["system"]
    assert (out / "recall.jsonl").exists()


def test_profile_search_appends_profile(tmp_path, monkeypatch):
    path, out = _lme_file(tmp_path), tmp_path / "out"
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "profile.md").write_text("- Plays the violin\n")
    monkeypatch.setattr(sg.pl, "profile_from_sessions", lambda *a, **k: prof)
    llm = FakeLLM([Reply("violin", "end_turn", 10, 1), Reply("yes", "end_turn", 1, 1)])
    sg.run_lme(path, out, llm, conditions=("profile+search",), n=1, params=PARAMS, counts=ONE)
    (row,) = _rows(out)
    assert row["tool_calls"] == 0 and row["retrieved_answer_session"] is False
    assert lme.SOURCES["profile+search"] in llm.calls[0]["system"] and "Plays the violin" in llm.calls[0]["system"]


def test_rows_are_resumable_and_hold_no_history_text(tmp_path):
    path, out = _lme_file(tmp_path), tmp_path / "out"
    llm = FakeLLM([Reply("You started violin.", "end_turn", 10, 2), Reply("yes", "end_turn", 1, 1)])
    sg.run_lme(path, out, llm, conditions=("search-1shot",), n=1, params=PARAMS, counts=ONE)
    assert MARK in llm.calls[0]["system"]          # the one-shot context is the search result
    sg.run_lme(path, out, FakeLLM([]), conditions=("search-1shot",), n=1, params=PARAMS, counts=ONE)
    rows = _rows(out)
    assert len(rows) == 1 and rows[0]["retrieved_answer_session"] is True and rows[0]["tool_calls"] == 1
    for f in ("results.jsonl", "recall.jsonl"):
        text = (out / f).read_text()
        assert MARK not in text and "paddleboard" not in text and "What instrument" not in text


def test_full_rows_reused_only_when_prompt_matches(tmp_path):
    path = _lme_file(tmp_path)
    qid = load(path)[0].qid
    reuse = tmp_path / "old" / "results.jsonl"
    reuse.parent.mkdir()
    reuse.write_text(json.dumps({"qid": qid, "qtype": "knowledge-update", "arm": "full", "outcome": "ok",
                                 "correct": True, "response": "violin", "backend": "api", "input_tokens": 167000,
                                 "output_tokens": 200, "usd": 0.08}) + "\n")
    current = (Path(um.prompts.__file__).parent / "answer.md").read_bytes()
    out1 = tmp_path / "o1"
    sg.run_lme(path, out1, FakeLLM([]), conditions=("full",), n=1, params=PARAMS, counts=ONE,
               full_reuse=reuse, reuse_prompt=current)
    (row,) = _rows(out1)
    assert row["reused"] is True and row["correct"] is True and row["input_tokens"] == 167000
    out2 = tmp_path / "o2"
    llm = FakeLLM([Reply("piano", "end_turn", 100, 5), Reply("no", "end_turn", 1, 1)])
    sg.run_lme(path, out2, llm, conditions=("full",), n=1, params=PARAMS, counts=ONE,
               full_reuse=reuse, reuse_prompt=b"an older prompt")
    (row,) = _rows(out2)
    assert "reused" not in row and row["correct"] is False and llm.calls[0]["label"] == "answer:full"
    assert sg.prompt_at_commit(tmp_path / "not-tracked.jsonl") is None


def _write_rows(out, rows):
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_report_verdicts(tmp_path):
    rows = []
    for i in range(20):   # profile 2/20, profile+search 19/20
        rows.append({"qid": f"k{i}", "qtype": "knowledge-update", "condition": "profile", "correct": i < 2,
                     "outcome": "ok", "input_tokens": 1000, "output_tokens": 10, "usd": 0, "tool_calls": 0})
        rows.append({"qid": f"k{i}", "qtype": "knowledge-update", "condition": "profile+search", "correct": i < 19,
                     "outcome": "ok", "input_tokens": 9000, "output_tokens": 10, "usd": 0, "tool_calls": 2,
                     "retrieved_answer_session": True})
    for i in range(10):   # abstention: profile 5, profile+search 3
        rows.append({"qid": f"a{i}", "qtype": "abstention", "condition": "profile", "correct": i < 5,
                     "outcome": "ok", "input_tokens": 1000, "output_tokens": 10, "usd": 0, "tool_calls": 0})
        rows.append({"qid": f"a{i}", "qtype": "abstention", "condition": "profile+search", "correct": i < 3,
                     "outcome": "ok", "input_tokens": 9000, "output_tokens": 10, "usd": 0, "tool_calls": 1,
                     "retrieved_answer_session": False})
    _write_rows(tmp_path / "lme", rows)
    text = sg.report(tmp_path / "lme")
    assert "G1 PASS" in text and "G2 FAIL" in text and "G3" not in text

    pref = []
    for i in range(10):
        for c in sg.PREF_CONDITIONS:
            pref.append({"qid": f"p{i}", "qtype": "travel", "condition": c, "correct": i < 6, "outcome": "ok",
                         "input_tokens": 1, "output_tokens": 1, "usd": 0, "tool_calls": 0})
    _write_rows(tmp_path / "pref", pref)
    assert "G3 PASS" in sg.report(tmp_path / "pref")


def test_tune_writes_params_and_uses_no_model(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tune must not build a model client")
    monkeypatch.setattr("um.llm.AnthropicLLM.__init__", boom)
    monkeypatch.setattr("um.llm_sub.ClaudeCodeLLM.__init__", boom)
    path = _lme_file(tmp_path, {"knowledge-update": 3, "abstention": 2})
    grid = {"chunk_chars": [1000, 2000], "lead_chars": [300], "per_session": [1, 2], "half_life_days": [None, 90]}
    out = tmp_path / "tune"
    best = sg.tune(path, out, grid, counts={"knowledge-update": 1, "abstention": 1}, seed=7)
    rows = json.loads((out / "tune.json").read_text())["settings"]
    assert len(rows) == 8 and all({"recall@5", "recall@10", "n"} <= set(r) for r in rows)
    assert all(r["n"] == 3 for r in rows)
    params = json.loads((out / "params.json").read_text())
    assert params == best == PARAMS   # every setting ties on this data, so the defaults are kept
    assert not list(out.rglob("*.sqlite"))
