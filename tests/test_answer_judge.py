from pathlib import Path

from um.bench.answer import answer_files_agent, answer_from_store, answer_full_context
from um.bench.judge import judge
from um.bench.longmemeval import load, materialize
from um.llm import FakeLLM, Reply

TINY = Path(__file__).parent / "data" / "lme_tiny.json"
ITEMS = {i.qid: i for i in load(TINY)}
OK = Reply("Brightline", "end_turn", 1, 1)


def test_full_context_shows_every_session_in_date_order_and_the_question_date():
    llm = FakeLLM([OK])
    assert answer_full_context(ITEMS["ku01"], llm, "m").text == "Brightline"
    call = llm.calls[0]
    text = call["system"] + call["user"]
    assert call["kind"] == "complete" and "2023/06/01" in text and "Where do I work now?" in call["user"]
    assert call["user"].index("2023/03/02") < call["user"].index("2023/04/11") < call["user"].index("2023/05/20")
    assert "Brightline" in call["user"] and "Oakfield" in call["user"]


def test_store_answerer_gets_a_read_only_toolbox_over_the_store(store):
    llm = FakeLLM([OK])
    answer_from_store(ITEMS["ku01"], store, llm, "m")
    call = llm.calls[0]
    assert call["kind"] == "run_tools" and {s["name"] for s in call["tools"].specs()} == {"view", "grep"}
    assert call["tools"].root == store.resolve() and "2023/06/01" in call["system"] + call["user"]


def test_files_agent_gets_a_read_only_toolbox_over_the_sessions(tmp_path):
    materialize(ITEMS["ku01"], tmp_path)
    llm = FakeLLM([OK])
    answer_files_agent(ITEMS["ku01"], tmp_path, llm, "m")
    assert {s["name"] for s in llm.calls[0]["tools"].specs()} == {"view", "grep"}


def test_judge_reads_yes_and_no_and_treats_anything_else_as_no():
    for text, expected in (("yes", True), ("Yes.", True), ("no", False), ("maybe", False), ("", False)):
        assert judge(ITEMS["ku01"], "Brightline", FakeLLM([Reply(text, "end_turn", 1, 1)]), "m") is expected


def test_judge_uses_the_prompt_for_the_question_type():
    def prompt_for(qid, response="some answer {with braces}"):
        llm = FakeLLM([Reply("yes", "end_turn", 1, 1)])
        judge(ITEMS[qid], response, llm, "m")
        return llm.calls[0]["user"]

    assert "updated answer" in prompt_for("ku01") and "Correct Answer: Brightline" in prompt_for("ku01")
    assert "off-by-one" in prompt_for("tr01")
    assert "unanswerable" in prompt_for("ms01_abs")
    assert "some answer {with braces}" in prompt_for("ku01")
