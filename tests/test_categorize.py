import hashlib
import json

from um.bridge.categorize import categorize
from um.llm import FakeLLM, Reply


def h(line):
    return hashlib.sha1(line.encode()).hexdigest()


LINES = ["- Works at Brightline", "- Squat 405 lb", "- Uses BudgetBee with LedgerLink"]


def test_labels_lines_and_caches(tmp_path):
    cache = tmp_path / "categories.json"
    llm = FakeLLM([Reply(json.dumps({"0": "identity-work-projects-preferences", "1": "training-lifts", "2": "budgeting-setup"}),
                         "end_turn", 1, 1)])
    got = categorize(LINES, llm, "m", cache)
    assert got == {h(LINES[0]): "identity-work-projects-preferences", h(LINES[1]): "training-lifts", h(LINES[2]): "budgeting-setup"}
    assert len(llm.calls) == 1 and "training-lifts" in llm.calls[0]["system"]
    again = FakeLLM([])
    assert categorize(LINES, again, "m", cache) == got and again.calls == []


def test_malformed_reply_or_unknown_category_maps_to_other(tmp_path):
    llm = FakeLLM([Reply("not json", "end_turn", 1, 1)])
    got = categorize(LINES, llm, "m", tmp_path / "c.json")
    assert set(got.values()) == {"other"}
    llm = FakeLLM([Reply(json.dumps({"0": "astrology", "1": "training-lifts"}), "end_turn", 1, 1)])
    got = categorize(LINES, llm, "m", tmp_path / "d.json")
    assert got[h(LINES[0])] == "other" and got[h(LINES[1])] == "training-lifts" and got[h(LINES[2])] == "other"


def test_batches_of_at_most_60(tmp_path):
    lines = [f"- fact {i}" for i in range(130)]
    script = [Reply(json.dumps({str(i): "identity-work-projects-preferences" for i in range(n)}), "end_turn", 1, 1) for n in (60, 60, 10)]
    llm = FakeLLM(script)
    got = categorize(lines, llm, "m", tmp_path / "c.json")
    assert len(llm.calls) == 3 and len(got) == 130
    assert all(c["user"].count("\n") < 70 for c in llm.calls)
