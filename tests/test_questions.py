from um.questions import QuestionBudget


def test_budget_total_counts_every_allowed_question():
    b = QuestionBudget(2)
    assert b.allow("2026-01-05") and b.allow("2026-01-06")
    assert not b.allow("2026-01-07")          # same ISO week, over budget: not counted
    assert b.allow("2026-01-12")
    assert b.total() == 3
