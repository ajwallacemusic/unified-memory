import pytest

from um.compile import parse_changes
from um.questions import QuestionBudget


def test_parse_accepts_a_bare_array_or_one_fenced_block():
    body = '[{"op": "add", "file": "memory/work.md", "new": "- x", "citations": [{"evidence": "e1", "quote": "q"}]}]'
    for text in (body, f"```json\n{body}\n```", f"Here you go:\n```\n{body}\n```\n"):
        (c,) = parse_changes(text)
        assert (c.op, c.file, c.new, c.old) == ("add", "memory/work.md", "- x", None)
        assert c.citations == [{"evidence": "e1", "quote": "q"}]
    assert parse_changes("[]") == []


def test_parse_keeps_questions_and_duplicates():
    text = ('[{"op": "remove", "file": "m.md", "old": "- a", "duplicate_of": {"file": "n.md", "line": "- a"}},'
            ' {"op": "replace", "file": "m.md", "old": "- b", "new": "- c", "citations": [],'
            ' "question": {"attr": "employer", "text": "Is it c?"}}]')
    a, b = parse_changes(text)
    assert a.duplicate_of == {"file": "n.md", "line": "- a"} and b.question["attr"] == "employer"


@pytest.mark.parametrize("text", ["not json", '{"op": "add"}', '[{"file": "x"}]', '["add"]',
                                  "```json\n[]\n```\n```json\n[]\n```", '[{"op": "add", "citations": "e1"}]',
                                  '[{"op": "add", "file": "m.md", "new": 5, "citations": []}]',
                                  '[{"op": "replace", "file": "m.md", "old": ["x"], "new": "- y", "citations": []}]',
                                  '[{"op": "add", "file": 3, "new": "- y", "citations": []}]',
                                  '[{"op": "add", "file": "m.md", "new": "- y", "citations": [{"evidence": "e1", "quote": 7}]}]',
                                  '[{"op": "remove", "file": "m.md", "old": "- y", "duplicate_of": "m.md"}]',
                                  '[{"op": "add", "file": "m.md", "new": "- y", "citations": [], "question": "why"}]'])
def test_parse_rejects_anything_else(text):
    with pytest.raises(ValueError):
        parse_changes(text)


def test_question_budget_counts_per_iso_week():
    b = QuestionBudget(per_week=3)
    assert [b.allow("2026-01-05") for _ in range(4)] == [True, True, True, False]   # Monday of ISO week 2
    assert b.allow("2026-01-11") is False                                            # Sunday, same week
    assert b.allow("2026-01-12") is True                                             # next Monday
