import json
import shutil
import subprocess

import pytest

from um.checks import review
from um.erase import erase_values, raw_copies, remaining, purge_history
from um.evidence import load_evidence
from um.profile import Change, Lineage

V = "Brightline"


@pytest.fixture
def tree(tmp_path):
    s = tmp_path / "stores"
    (s / "memory").mkdir(parents=True)
    (s / "memory" / "work.md").write_text("# Work\n\n- Employer: Brightline (since 2026-01-05)\n- Team: Larchgate\n")
    (s / "memory" / "home.md").write_text("# Home\n\n- City: Aldermoor\n")
    (s / "skills" / "helper").mkdir(parents=True)
    (s / "skills" / "helper" / "SKILL.md").write_text("# Helper\n\n- The user's employer is brightline.\n- Keep it short.\n")
    (s / ".lineage.jsonl").write_text(
        json.dumps({"file": "memory/work.md", "line": "- Employer: Brightline (since 2026-01-05)", "origin": "user-said",
                    "asserted": "2026-01-05", "citations": [{"evidence": "u1", "quote": "I just started at Brightline."}]}) + "\n" +
        json.dumps({"file": "memory/work.md", "line": "- Team: Larchgate", "origin": "user-said", "asserted": "2026-01-05",
                    "citations": [{"evidence": "u2", "quote": "team is Larchgate"}]}) + "\n")
    (s / ".pass.json").write_text(json.dumps({"as_of": "2026-01-07", "changes": [
        {"op": "replace", "old": "- Employer: Oakfield", "new": "- Employer: Brightline", "decision": "apply"},
        {"op": "add", "new": "- Team: Larchgate", "decision": "apply"}],
        "questions": [{"change": 0, "question": {"attr": "employer"}, "status": "answered", "answer": "My employer is Brightline."}]}, indent=1))
    (s / ".answers").mkdir()
    (s / ".answers" / "a1.md").write_text("origin: user-said\ndate: 2026-01-07\n\nMy employer is Brightline.\n")
    (s / ".answers" / "a2.md").write_text("origin: user-said\ndate: 2026-01-07\n\nMy city is Aldermoor.\n")
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "u1.md").write_text("origin: user-said\ndate: 2026-01-05\n\nuser: I just started at Brightline.\n")
    (ev / "u2.md").write_text("origin: user-said\ndate: 2026-01-05\n\nuser: My team is Larchgate.\n")
    return s, ev


def test_erase_leaves_nothing_and_keeps_the_rest(tree):
    s, ev = tree
    home_before = (s / "memory" / "home.md").read_bytes()
    rep = erase_values(s, [V], [ev])
    assert remaining(s, [V]) == [] and remaining(ev, [V]) == []
    assert (s / "memory" / "home.md").read_bytes() == home_before
    assert "- Team: Larchgate" in (s / "memory" / "work.md").read_text()
    assert "- Keep it short." in (s / "skills" / "helper" / "SKILL.md").read_text()
    assert len(rep.lines_removed) == 2 and rep.lineage_rows == 1 and rep.pass_entries == 2
    assert rep.answers_deleted == [".answers/a1.md"] and rep.evidence_deleted == ["u1.md"]
    assert (s / ".answers" / "a2.md").exists() and (ev / "u2.md").exists()
    assert Lineage(s).origin_of("memory/work.md", "- Team: Larchgate") == "user-said"
    record = json.loads((s / ".pass.json").read_text())
    assert record["changes"][0] == {"erased": True} and record["changes"][1]["new"] == "- Team: Larchgate"
    assert record["questions"] == [{"erased": True}]


def test_matching_ignores_case(tree):
    s, ev = tree
    erase_values(s, ["BRIGHTLINE"], [ev])
    assert remaining(s, [V.lower()]) == []


def test_short_value_is_refused(tree):
    s, _ = tree
    with pytest.raises(ValueError):
        erase_values(s, ["Br"])


def test_remaining_sees_hidden_files_but_not_git(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x").write_text(V)
    (tmp_path / ".hidden.json").write_text(V)
    assert remaining(tmp_path, [V]) == [".hidden.json"]


def test_erased_evidence_cannot_be_cited(tree):
    s, ev = tree
    erase_values(s, [V], [ev])
    c = Change("add", "memory/work.md", None, "- Employer: Brightline",
               citations=[{"evidence": "u1", "quote": "I just started at Brightline."}])
    v = review([c], s, Lineage(s), load_evidence(ev))[0]
    assert v.decision == "reject" and v.reason.startswith("unknown evidence")


def test_raw_copies_only_reports(tmp_path):
    root = tmp_path / "chats"
    root.mkdir()
    f = root / "c1.jsonl"
    f.write_text('{"text": "I work at Brightline"}\n')
    got = raw_copies([V], [root])
    assert got == {V: [f]} and f.exists()


def _has_filter_repo():
    from um.erase import _filter_repo_available
    return _filter_repo_available() is not None


@pytest.mark.skipif(not _has_filter_repo(), reason="git filter-repo is not installed")
def test_purge_history_removes_value_from_every_commit(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (r / "a.md").write_text(f"- Employer: {V}\n")
    git("add", "-A"); git("commit", "-qm", "one")
    (r / "a.md").write_text("- Employer: (erased)\n")
    git("add", "-A"); git("commit", "-qm", "two")
    purge_history(r, [V])
    assert V not in git("log", "-p", "--all").stdout


def test_purge_history_refuses_without_filter_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    import um.erase as e
    monkeypatch.setattr(e, "_filter_repo_available", lambda: False)
    with pytest.raises(RuntimeError):
        purge_history(tmp_path, [V])
