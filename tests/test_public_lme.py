from pathlib import Path

from um.bench.longmemeval import load
from um.bench.public import lme
from um.llm import FakeLLM, Reply

TINY = Path(__file__).parent / "data" / "lme_tiny.json"


def test_counts_split_evenly_and_respect_what_exists():
    assert lme.counts_for(10) == {"knowledge-update": 4, "single-session-user": 3, "single-session-preference": 3}
    assert lme.counts_for(100, {"knowledge-update": 72, "single-session-user": 64, "single-session-preference": 30}) == {
        "knowledge-update": 35, "single-session-user": 35, "single-session-preference": 30}
    assert sum(lme.counts_for(500, {"knowledge-update": 72, "single-session-user": 64,
                                    "single-session-preference": 30}).values()) == 166


def test_sessions_carry_iso_dates_and_roles():
    item = load(TINY)[0]
    ss = lme.sessions(item)
    assert [s.date for s in ss] == sorted(s.date for s in ss) and all(len(s.date) == 10 for s in ss)
    assert ss[0].turns[0][0] in ("user", "assistant")


def test_instructions_name_the_source_and_the_date():
    item = load(TINY)[0]
    for c in ("none", "full-history", "raw-retrieval", "profile-full", "profile-hook"):
        text = lme.instructions(item, c)
        assert item.question_date in text and lme.SOURCES[c] in text
    assert lme.question_text(item) == f"Question (asked on {item.question_date}): {item.question}"


def test_grade_uses_the_longmemeval_judge_prompt():
    item = load(TINY)[0]
    llm = FakeLLM([Reply("yes", "end_turn", 1, 1)])
    assert lme.grade(item, "the answer", llm, "j") == {"correct": True, "judge": "yes"}
    assert item.question in llm.calls[0]["user"] and "the answer" in llm.calls[0]["user"]
    assert lme.grade(item, "x", FakeLLM([Reply("maybe", "end_turn", 1, 1)]), "j")["correct"] is None
