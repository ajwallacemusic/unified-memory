import json
from um.bench import label_sheet as ls


def _setup(tmp_path):
    prof = tmp_path / "profile"; (prof / "areas").mkdir(parents=True)
    (prof / "areas/w.md").write_text("# W\n- [stated] Ticket prefix is DSP\n- other\n")
    q = tmp_path / "q.jsonl"
    q.write_text("\n".join(json.dumps({"id": f"q{i}", "split": "test" if i % 2 else "dev", "question": f"Q{i}?",
                                       "answer_terms": ["DSP"], "file": "areas/w.md"}) for i in range(40)))
    imp = tmp_path / "imp.jsonl"
    imp.write_text(json.dumps({"id": "i1", "prompt": "do it", "check": "test first?", "fact": "- wants tests"}))
    res = tmp_path / "res.jsonl"
    res.write_text("\n".join(json.dumps({"id": "i1", "condition": c, "answer": "x" * 2000, "hit": c == "full"})
                             for c in ["full", "none"] * 10))
    return prof, q, imp, res


def test_sheet_and_score(tmp_path):
    prof, q, imp, res = _setup(tmp_path)
    md = ls.build_sheet(q, prof, imp, res, n=15, seed=7)
    assert md == ls.build_sheet(q, prof, imp, res, n=15, seed=7)
    assert md.count("Your verdict: [ ] agree  [ ] disagree  — note:") == 30
    assert "Ticket prefix is DSP" in md and "Q0?" not in md  # dev excluded
    assert "x" * 1201 not in md and "test first?" in md and "- wants tests" in md
    filled = md.replace("[ ] agree  [ ] disagree", "[x] agree  [ ] disagree", 20)
    out = ls.score(filled)
    assert out["recall"] == {"agree": 15, "disagree": 0, "blank": 0}
    assert out["implicit"] == {"agree": 5, "disagree": 0, "blank": 10}
