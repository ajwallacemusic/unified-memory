from um.digest import receipt

RECORD = {"as_of": "2026-11-11", "outcome": "ok", "changes": [
    {"op": "replace", "file": "profile.md", "old": "- A", "new": "- B", "decision": "apply", "reason": "supported change",
     "origin": "user-said", "applied": True, "citations": [{"evidence": "e1", "quote": "it is B now"}]},
    {"op": "replace", "file": "profile.md", "old": "- C", "new": "- D", "decision": "hold",
     "reason": "tool output cannot override an existing line", "origin": "tool-output", "applied": False, "citations": []}],
    "questions": [{"change": 1, "question": {"text": "Is it D?"}, "status": "not asked", "answer": None}]}


def test_receipt_names_applied_held_and_asked_with_reasons():
    r = receipt(RECORD)
    assert "applied" in r and "it is B now" in r and "e1" in r
    assert "held" in r and "tool output cannot override an existing line" in r
    assert "Is it D?" in r and "/unified-memory:undo" in r


def test_receipt_of_failed_compile():
    r = receipt({"as_of": "2026-11-11", "outcome": "compile_failed", "error": "reply is not JSON", "changes": [], "questions": []})
    assert "compile failed" in r and "reply is not JSON" in r
