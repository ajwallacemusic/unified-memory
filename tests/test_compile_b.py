import json
import shutil

import pytest

from conftest import tree_hash
from um.arms import ARMS, a, a0, b
from um.llm import FakeLLM, Reply
from um.profile import Lineage, lines_of
from um.questions import QuestionBudget

DONE = Reply("ok", "end_turn", 1, 1)


def store_hash(root):
    """Hash of store content only: hidden records such as .pass.json are not stores."""
    import hashlib
    h = hashlib.sha256()
    for f, line in lines_of(root):
        h.update(f"{f}\0{line}\n".encode())
    return h.hexdigest()


@pytest.fixture
def stores(tmp_path):
    r = tmp_path / "stores"
    (r / "memory").mkdir(parents=True)
    (r / "memory" / "MEMORY.md").write_text("- [Work](work.md): job\n- [Home](home.md): home\n")
    (r / "memory" / "work.md").write_text("- Works at Oakfield\n- Team: Larchgate\n")
    (r / "memory" / "home.md").write_text("- Lives in Aldermoor\n- Gym: Rowanvale\n- Deploy target: Sablecrest\n")
    (r / "skills" / "helper").mkdir(parents=True)
    (r / "skills" / "helper" / "SKILL.md").write_text("# Helper\n\n- The user's employer is Oakfield.\n")
    return r


@pytest.fixture
def evidence_dir(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "u1.md").write_text("origin: user-said\ndate: 2026-01-05\n\nuser: I just started at Brightline.\nassistant: Noted.\n")
    (d / "t1.md").write_text("origin: tool-output\ndate: 2026-01-06\n\ntool: the user's home city is Zentrix\n")
    (d / "t2.md").write_text("origin: tool-output\ndate: 2026-01-07\n\ntool: deploy target changed from Sablecrest to Harborgate\n")
    return d


def reply(changes):
    return Reply(json.dumps(changes), "end_turn", 10, 10)


def test_registry_has_four_arms():
    assert set(ARMS) == {"z", "a0", "a", "b"} and ARMS["b"].NAME == "b"


def test_hidden_files_are_not_store_lines(tmp_path, stores):
    (stores / ".answers").mkdir()
    (stores / ".answers" / "q1.md").write_text("origin: user-said\ndate: 2026-01-05\n\nx\n")
    assert all(not f.startswith(".") for f, _ in lines_of(stores))


def test_a0_works_inside_the_memory_folder_of_a_multi_store_tree(tmp_path, stores, monkeypatch):
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: consolidate-memory\n---\n\nBODY\n")
    monkeypatch.setattr(a0, "CONSOLIDATE_SKILL_PATH", skill)
    llm = FakeLLM([DONE])
    assert a0.apply(stores, tmp_path / "out", llm, "m", "2026-01-08") == "ok"
    assert llm.calls[0]["tools"].root == (tmp_path / "out" / "memory").resolve()


def test_a_reads_evidence_but_only_the_stores_are_kept(tmp_path, stores, evidence_dir):
    llm = FakeLLM([{"tool": "str_replace", "args": {"path": "stores/memory/work.md", "old": "- Works at Oakfield", "new": "- Works at Brightline"}},
                   {"tool": "write", "args": {"path": "evidence/u1.md", "content": "tampered"}}, DONE])
    assert a.apply(stores, tmp_path / "out", llm, "m", "2026-01-08", evidence_dir) == "ok"
    assert "Brightline" in (tmp_path / "out/memory/work.md").read_text()
    assert not (tmp_path / "out" / "evidence").exists() and "Brightline" in (evidence_dir / "u1.md").read_text()
    assert "evidence/" in llm.calls[0]["user"] and "Questions may ask" not in llm.calls[0]["system"]


def test_a_store_that_lost_a_nested_index_is_restored(tmp_path, stores):
    llm = FakeLLM([{"tool": "delete", "args": {"path": "memory/MEMORY.md"}}, DONE])
    assert a.apply(stores, tmp_path / "out", llm, "m", "2026-01-08") == "arm_failed"
    assert tree_hash(tmp_path / "out") == tree_hash(stores)


def test_a_bad_compile_reply_leaves_the_stores_unchanged(tmp_path, stores, evidence_dir):
    for n, r in enumerate((Reply("not json", "end_turn", 1, 1), Reply('{"op": "add"}', "end_turn", 1, 1),
                           Reply('[{"file": "x"}]', "end_turn", 1, 1), Reply("", "refusal", 1, 0))):
        out = tmp_path / f"o{n}"
        assert b.apply(stores, out, FakeLLM([r]), "m", "2026-01-08", evidence_dir) == "compile_failed"
        assert store_hash(out) == store_hash(stores)
        assert json.loads((out / ".pass.json").read_text())["outcome"] == "compile_failed"


def test_planted_tool_claim_is_not_applied_and_a_user_update_is(tmp_path, stores, evidence_dir):
    changes = [
        {"op": "replace", "file": "memory/work.md", "old": "- Works at Oakfield", "new": "- Works at Brightline",
         "citations": [{"evidence": "u1", "quote": "I just started at Brightline"}]},
        {"op": "replace", "file": "skills/helper/SKILL.md", "old": "- The user's employer is Oakfield.", "new": "- The user's employer is Brightline.",
         "citations": [{"evidence": "u1", "quote": "I just started at Brightline"}]},
        {"op": "replace", "file": "memory/home.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
         "citations": [{"evidence": "t1", "quote": "home city is Zentrix"}]},
        {"op": "add", "file": "memory/work.md", "new": "- Manager: Wrenholt", "citations": [{"evidence": "u1", "quote": "made up"}]},
    ]
    out = tmp_path / "o"
    assert b.apply(stores, out, FakeLLM([reply(changes)]), "m", "2026-01-08", evidence_dir) == "ok"
    assert "Brightline" in (out / "memory/work.md").read_text() and "Brightline" in (out / "skills/helper/SKILL.md").read_text()
    assert "Aldermoor" in (out / "memory/home.md").read_text() and "Wrenholt" not in (out / "memory/work.md").read_text()
    assert Lineage(out).origin_of("memory/work.md", "- Works at Brightline") == "user-said"
    record = json.loads((out / ".pass.json").read_text())
    assert [c["decision"] for c in record["changes"]] == ["apply", "apply", "hold", "reject"]


def test_questions_within_budget_are_asked_and_only_confirmed_changes_apply(tmp_path, stores, evidence_dir):
    planted = {"op": "replace", "file": "memory/home.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
               "citations": [{"evidence": "t1", "quote": "home city is Zentrix"}], "question": {"attr": "home city", "text": "Did you move?"}}
    system = {"op": "replace", "file": "memory/home.md", "old": "- Deploy target: Sablecrest", "new": "- Deploy target: Harborgate",
              "citations": [{"evidence": "t2", "quote": "changed from Sablecrest to Harborgate"}],
              "question": {"attr": "deploy target", "text": "Is the deploy target Harborgate now?"}}
    answers = {"home city": "No, I still live in Aldermoor.", "deploy target": "Yes, it is Harborgate now."}
    asked = []

    def ask(q):
        asked.append(q["attr"])
        return answers[q["attr"]]

    out = tmp_path / "o"
    assert b.apply(stores, out, FakeLLM([reply([planted, system])]), "m", "2026-01-08", evidence_dir, ask=ask,
                   budget=QuestionBudget(3)) == "ok"
    home = (out / "memory/home.md").read_text()
    assert "Aldermoor" in home and "Zentrix" not in home and "Harborgate" in home and asked == ["home city", "deploy target"]
    record = json.loads((out / ".pass.json").read_text())
    assert [(c["decision"], c.get("resolution")) for c in record["changes"]] == [("ask", "not confirmed"), ("ask", "confirmed by the person")]
    answers_dir = out / ".answers"
    assert len(list(answers_dir.glob("*.md"))) == 2 and "origin: user-said" in next(answers_dir.glob("*.md")).read_text()


def test_a_fourth_question_in_one_week_is_not_asked(tmp_path, stores, evidence_dir):
    q = {"op": "replace", "file": "memory/home.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
         "citations": [{"evidence": "t1", "quote": "home city is Zentrix"}], "question": {"attr": "home city", "text": "?"}}
    budget, asked = QuestionBudget(3), []
    for n in range(4):
        b.apply(stores, tmp_path / f"o{n}", FakeLLM([reply([q])]), "m", "2026-01-08", evidence_dir,
                ask=lambda x: asked.append(x) or None, budget=budget)
    assert len(asked) == 3
    record = json.loads((tmp_path / "o3" / ".pass.json").read_text())
    assert record["questions"][0]["status"] == "over budget"


def test_earlier_answers_are_evidence_in_later_passes(tmp_path, stores, evidence_dir):
    q = {"op": "replace", "file": "memory/home.md", "old": "- Deploy target: Sablecrest", "new": "- Deploy target: Harborgate",
         "citations": [{"evidence": "t2", "quote": "changed from Sablecrest to Harborgate"}], "question": {"attr": "deploy target", "text": "?"}}
    b.apply(stores, tmp_path / "w1", FakeLLM([reply([q])]), "m", "2026-01-08", evidence_dir, ask=lambda x: "Yes, Harborgate.")
    llm = FakeLLM([reply([])])
    b.apply(tmp_path / "w1", tmp_path / "w2", llm, "m", "2026-01-15", None)
    assert "origin: user-said" in llm.calls[0]["user"] and "Yes, Harborgate." in llm.calls[0]["user"]


def test_a_tool_add_that_restates_a_line_is_asked_and_a_confirmation_replaces_the_line(tmp_path, stores, evidence_dir):
    # No question from the model: code writes one. Confirmed, the existing line is replaced in place, not duplicated.
    add = {"op": "add", "file": "memory/work.md", "new": "- Deploy target: Harborgate (2026-01-07)",
           "citations": [{"evidence": "t2", "quote": "changed from Sablecrest to Harborgate"}]}
    asked = []

    def ask(q):
        asked.append(q)
        return "Yes, the deploy target is Harborgate now."
    out = tmp_path / "out"
    assert b.apply(stores, out, FakeLLM([reply([add])]), "m", "2026-01-08", evidence_dir, ask=ask) == "ok"
    assert asked and asked[0]["attr"] == "Deploy target" and "Sablecrest" in asked[0]["text"] and "Harborgate" in asked[0]["text"]
    lines = [l for _, l in lines_of(out)]
    assert "- Deploy target: Harborgate (2026-01-07)" in lines and not any("Sablecrest" in l for l in lines)
    assert sum("Deploy target" in l for l in lines) == 1


def test_an_unconfirmed_tool_add_that_restates_a_line_changes_nothing(tmp_path, stores, evidence_dir):
    add = {"op": "add", "file": "memory/work.md", "new": "- Deploy target: Harborgate",
           "citations": [{"evidence": "t2", "quote": "changed from Sablecrest to Harborgate"}]}
    out = tmp_path / "out"
    assert b.apply(stores, out, FakeLLM([reply([add])]), "m", "2026-01-08", evidence_dir, ask=lambda q: None) == "ok"
    assert store_hash(out) == store_hash(stores)
