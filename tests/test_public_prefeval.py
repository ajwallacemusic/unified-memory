"""PrefEval adapter, on a fictional miniature of the dataset's layout (no PrefEval text in this repo)."""
import json

import pytest

from um.bench.public import prefeval as pe
from um.llm import FakeLLM, Reply


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "prefeval"
    ex = r / "benchmark_dataset" / "explicit_preference"
    ex.mkdir(parents=True)
    for topic in ("alpha_topic", "beta_topic", "gamma_topic"):
        (ex / f"{topic}.json").write_text(json.dumps(
            [{"preference": f"I avoid {topic} thing {i}.", "question": f"Suggest a {topic} plan {i}?", "explanation": "x"}
             for i in range(4)]))
    convs = [{"conversation": [{"role": "user", "content": f"u{c}-{k}"} if k % 2 == 0 else
                               {"role": "assistant", "content": f"a{c}-{k}"} for k in range(4)]} for c in range(3)]
    (r / "benchmark_dataset" / "filtered_inter_turns.json").write_text(json.dumps(convs))
    et = r / "error_type"
    et.mkdir()
    (et / "check_acknowledge.txt").write_text("ACK q={question} r={end_generation}")
    (et / "check_violation.txt").write_text("VIO p={preference} q={question} r={end_generation}")
    (et / "check_hallucination.txt").write_text("HAL p={preference} s={assistant_restatement}")
    (et / "check_helpful.txt").write_text("HELP q={question} r={end_generation}")
    return r


def test_load_and_stratified_sample(root):
    items = pe.load(root)
    assert len(items) == 12 and items[0].id == "alpha_topic:0"
    s = pe.sample(items, 6, seed=1)
    assert sorted(i.topic for i in s).count("beta_topic") == 2 and len(s) == 6
    assert pe.sample(items, 6, seed=1) == s          # deterministic
    with pytest.raises(ValueError):
        pe.sample(items, 5, seed=1)                   # not equal per topic


def test_inter_turns_take_the_first_n_exchanges_across_conversations(root):
    turns = pe.inter_turns(root, 3)
    assert [t for _, t in turns] == ["u0-0", "a0-1", "u0-2", "a0-3", "u1-0", "a1-1"]
    assert [r for r, _ in turns][-1] == "assistant"


def test_sessions_put_the_preference_first_then_the_reply_then_inter_turns(root):
    item = pe.load(root)[0]
    s = pe.sessions(item, "Noted, I will remember.", pe.inter_turns(root, 1))
    assert len(s) == 1 and s[0].turns == (("user", item.preference), ("assistant", "Noted, I will remember."),
                                          ("user", "u0-0"), ("assistant", "a0-1"))
    assert pe.question_text(item) == item.question + " (Please respond within 300 words.)"


def test_parse_tags_like_beautifulsoup():
    assert pe.tag("<explanation>ok</explanation>\n<answer>Yes</answer>", "answer") == "Yes"
    assert pe.tag("<preference></preference><answer> No </answer>", "preference") == ""
    assert pe.tag("<Answer>Yes", "answer") == "Yes"        # unclosed: runs to the end
    assert pe.tag("no tags", "answer") == ""


def test_judge_runs_the_four_checks_with_their_prompts_and_scores_like_prefeval(root):
    item = pe.load(root)[0]
    llm = FakeLLM([Reply("<preference>Since you avoid thing 0</preference>\n<answer>Yes</answer>", "end_turn", 1, 1),
                   Reply("<explanation>fine</explanation><answer>No</answer>", "end_turn", 1, 1),
                   Reply("<explanation>same</explanation><answer>No</answer>", "end_turn", 1, 1),
                   Reply("<explanation>useful</explanation><answer>Yes</answer>", "end_turn", 1, 1)])
    checks = pe.judge(item, "RESP", llm, "j", root)
    assert [c["user"][:3] for c in llm.calls] == ["ACK", "VIO", "HAL", "HEL"]
    assert llm.calls[2]["user"] == f"HAL p={item.preference} s=Since you avoid thing 0"
    assert llm.calls[0]["system"] == pe.JUDGE_SYSTEM
    assert checks == {"acknow": "Yes", "extract_pref": "Since you avoid thing 0", "violate": "No",
                      "hallucinate": "No", "helpful": "Yes"}
    assert pe.score(checks)["preference_following"] is True


@pytest.mark.parametrize("ack,hal,vio,helpful,expect", [
    ("Yes", "No", "No", "Yes", True),
    ("No", "No", "No", "Yes", True),        # no acknowledgement, no violation, helpful
    ("No", "No", "Yes", "Yes", False),      # preference-unaware violation
    ("Yes", "No", "Yes", "Yes", False),     # inconsistent
    ("Yes", "Yes", "Yes", "Yes", False),    # hallucinated preference, violation
    ("Yes", "No", "No", "No", False),       # unhelpful
])
def test_score_matches_analyze_errors(ack, hal, vio, helpful, expect):
    got = pe.score({"acknow": ack, "hallucinate": hal, "violate": vio, "helpful": helpful})
    assert got["preference_following"] is expect


def test_pref_generation_is_the_answer_models_reply_to_the_preference(root):
    item = pe.load(root)[0]
    llm = FakeLLM([Reply("Understood.", "end_turn", 3, 2)])
    r = pe.pref_generation(item, llm, "m")
    assert r.text == "Understood." and llm.calls[0]["user"] == item.preference
    assert llm.calls[0]["system"] == pe.SYSTEM_PROMPT


def test_answer_budget_is_one_setting_for_every_condition(root):
    from um.bench.public.run import prefeval_bench
    assert prefeval_bench(root, 3, 1, 2, "m").max_tokens == pe.ANSWER_MAX_TOKENS
    assert prefeval_bench(root, 3, 1, 2, "m", answer_max_tokens=4_000).max_tokens == 4_000
