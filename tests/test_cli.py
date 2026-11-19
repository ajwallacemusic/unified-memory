import json
import subprocess

import pytest

from um.cli import main
from um.erase import remaining
from um.llm import FakeLLM, Reply

SID = "feedbeef-1111"


def git(p, *a):
    return subprocess.run(["git", "-C", str(p), *a], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def prof(tmp_path):
    p = tmp_path / "claude-profile"
    (p / "areas").mkdir(parents=True)
    (p / "profile.md").write_text("# Profile\n\n- Works at Oakfield\n- Lives in Aldermoor\n")
    (p / "areas" / "training.md").write_text("# Training\n\n- Squat 405 lb\n")
    git(p, "init", "-q")
    git(p, "config", "user.email", "t@example.com")
    git(p, "config", "user.name", "t")
    git(p, "add", "-A")
    git(p, "commit", "-qm", "bootstrap")
    proj = tmp_path / "projects" / "-Users-x-repo"
    proj.mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text(json.dumps({
        "type": "user", "sessionId": SID, "timestamp": "2026-11-11T09:00:00Z", "isSidechain": False,
        "origin": {"kind": "human"}, "message": {"role": "user", "content": "I work at Brightline now."}}) + "\n")
    return p, tmp_path / "projects"


CHANGE = [{"op": "replace", "file": "profile.md", "old": "- Works at Oakfield", "new": "- Works at Brightline",
           "citations": [{"evidence": "sfeedbeef-user", "quote": "I work at Brightline now."}]},
          {"op": "replace", "file": "profile.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
           "citations": [{"evidence": "sfeedbeef-user", "quote": "Brightline"}]}]


def compile_(p, projects, reply):
    llm = FakeLLM([Reply(json.dumps(reply), "end_turn", 1, 1)])
    main(["compile", "--profile", str(p), "--projects", str(projects), "--today", "2026-11-11"], llm=llm)
    return llm


def test_compile_commits_once_with_a_receipt_quoting_each_change(prof):
    p, projects = prof
    llm = compile_(p, projects, CHANGE)
    assert "I work at Brightline now." in llm.calls[0]["user"]
    assert "- Works at Brightline" in (p / "profile.md").read_text()
    assert "- Lives in Aldermoor" in (p / "profile.md").read_text()
    receipt = (p / "digest" / "2026-11-11.md").read_text()
    assert "I work at Brightline now." in receipt and "applied" in receipt and "rejected" in receipt
    assert "/doctor prompt-audit" in receipt
    log = git(p, "log", "--format=%s")
    assert log.splitlines()[0].startswith("compile 2026-11-11") and len(log.splitlines()) == 2
    assert git(p, "status", "--porcelain").strip() == ""


def test_second_compile_with_nothing_to_do_makes_no_commit(prof):
    p, projects = prof
    compile_(p, projects, CHANGE)
    before = git(p, "rev-parse", "HEAD")
    compile_(p, projects, [])
    assert git(p, "rev-parse", "HEAD") == before


def test_undo_restores_the_previous_bytes(prof, capsys):
    p, projects = prof
    original = (p / "profile.md").read_bytes()
    compile_(p, projects, CHANGE)
    main(["undo", "--profile", str(p)])
    assert (p / "profile.md").read_bytes() == original
    assert "compile 2026-11-11" in capsys.readouterr().out


def test_undo_refuses_a_commit_that_is_not_a_compile(prof):
    p, _ = prof
    with pytest.raises(SystemExit):
        main(["undo", "--profile", str(p)])


def test_questions_go_to_pending_and_answers_become_user_said(prof):
    p, projects = prof
    ask = [{"op": "replace", "file": "profile.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
            "citations": [{"evidence": "sfeedbeef-user", "quote": "I work at Brightline now."}]}]
    (p / "inbox" / "held").mkdir(parents=True)
    (p / "inbox" / "held" / "h1.md").write_text("origin: tool-output\ndate: 2026-11-11\n\nSync: the user's home city is Zentrix\n")
    q = [{"op": "replace", "file": "profile.md", "old": "- Lives in Aldermoor", "new": "- Lives in Zentrix",
          "citations": [{"evidence": "h1", "quote": "home city is Zentrix"}], "question": {"attr": "home city", "text": "Did you move to Zentrix?"}}]
    compile_(p, projects, q)
    assert "Did you move to Zentrix?" in (p / "digest" / "pending.md").read_text()
    assert "- Lives in Aldermoor" in (p / "profile.md").read_text()
    main(["answer", "--profile", str(p), "--text", "Yes, I live in Zentrix now.", "--today", "2026-11-12"])
    a = list((p / ".answers").glob("*.md"))
    assert len(a) == 1 and a[0].read_text().startswith("origin: user-said\ndate: 2026-11-12")


def test_erase_leaves_no_value_and_reports_raw_copies_without_deleting(prof, capsys):
    p, projects = prof
    compile_(p, projects, CHANGE)
    main(["erase", "--profile", str(p), "--value", "Brightline", "--raw-root", str(projects), "--yes"])
    assert remaining(p, ["Brightline"]) == []
    out = capsys.readouterr().out
    assert f"{SID}.jsonl" in out and (projects / "-Users-x-repo" / f"{SID}.jsonl").exists()
    assert "history" in out
    assert "Brightline" not in git(p, "log", "--format=%s")


def test_erase_refuses_without_yes(prof):
    p, _ = prof
    with pytest.raises(SystemExit):
        main(["erase", "--profile", str(p), "--value", "Brightline"])


def test_status(prof, capsys):
    p, projects = prof
    compile_(p, projects, CHANGE)
    main(["status", "--profile", str(p)])
    out = capsys.readouterr().out
    assert "last build 2026-11-11" in out and "held 0" in out and "pending 0" in out


@pytest.fixture
def export(tmp_path, monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(k, v)
    e = tmp_path / "memory-export"
    (e / "areas").mkdir(parents=True)
    (e / "profile.md").write_text("---\nname: profile\n---\n\n- Works at Oakfield\n- Works at Brightline (since 2026-10)\n")
    (e / "areas" / "training.md").write_text("- Squat 405 lb\n")
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "u1.md").write_text("origin: user-said\ndate: 2026-10-02\n\nuser: I left Oakfield, I'm at Brightline now.\n")
    return e, ev


def test_bootstrap_imports_unchanged_then_commits_a_cleanup_that_undo_reverts(tmp_path, export, capsys):
    e, ev = export
    p = tmp_path / "claude-profile"
    llm = FakeLLM([{"tool": "str_replace", "args": {"path": "stores/profile.md", "old": "- Works at Oakfield\n", "new": ""}},
                   Reply("Removed the stale employer line.", "end_turn", 1, 1)])
    main(["bootstrap", "--from", str(e), "--evidence", str(ev), "--profile", str(p), "--today", "2026-11-11"], llm=llm)
    subjects = git(p, "log", "--format=%s").splitlines()
    assert subjects[-1] == "import: account memory export (unchanged)"
    assert subjects[0].startswith("compile 2026-11-11: bootstrap cleanup")
    assert git(p, "show", "HEAD~1:profile.md") == (e / "profile.md").read_text()
    assert "Oakfield" not in (p / "profile.md").read_text()
    digest = (p / "digest" / "2026-11-11-bootstrap.md").read_text()
    assert "profile.md" in digest and "- Works at Oakfield" in digest and "training.md" not in digest
    assert "evidence/" in llm.calls[0]["user"]
    main(["undo", "--profile", str(p)])
    assert (p / "profile.md").read_text() == (e / "profile.md").read_text()


def test_bootstrap_refuses_a_profile_folder_that_has_files(tmp_path, export):
    e, ev = export
    p = tmp_path / "claude-profile"
    p.mkdir()
    (p / "notes.md").write_text("x")
    with pytest.raises(SystemExit, match="not empty"):
        main(["bootstrap", "--from", str(e), "--profile", str(p)], llm=FakeLLM([]))
    assert not (p / ".git").exists()


def test_bootstrap_whose_cleanup_changes_nothing_keeps_only_the_import(tmp_path, export, capsys):
    e, ev = export
    p = tmp_path / "claude-profile"
    main(["bootstrap", "--from", str(e), "--profile", str(p), "--today", "2026-11-11"],
         llm=FakeLLM([Reply("Nothing to change.", "end_turn", 1, 1)]))
    assert git(p, "log", "--format=%s").splitlines() == ["import: account memory export (unchanged)"]
    assert "no changes" in capsys.readouterr().out


def test_compile_adopts_a_line_a_chat_added_even_when_the_writer_proposes_nothing(prof):
    from um.bridge.adopt import record_synced
    p, projects = prof
    record_synced(p, "/areas/training.md", "# Training\n\n- Squat 405 lb\n")
    (p / "inbox").mkdir()
    (p / "inbox" / "areas-training-md.json").write_text(json.dumps({
        "path": "/areas/training.md", "version": "v9", "updated": "2026-11-11T08:00:00Z",
        "content": "# Training\n\n- Squat 405 lb\n- Deadlift 500 lb\n"}))
    compile_(p, projects, [])
    assert (p / "areas" / "training.md").read_text().endswith("- Squat 405 lb\n- Deadlift 500 lb\n")
    assert "From account memory (1)" in (p / "digest" / "2026-11-11.md").read_text()
    assert "1 from memory" in git(p, "log", "-1", "--format=%s")
    assert not list((p / "inbox").glob("*.json"))


def test_compile_records_the_version_of_each_pull_it_took_in(prof):
    from um.bridge.adopt import record_synced
    p, projects = prof
    record_synced(p, "/areas/training.md", "# Training\n\n- Squat 405 lb\n")
    (p / "state.json").write_text(json.dumps({"/areas/training.md": {"version": "old1", "pushed_sha256": "x"}}))
    (p / "inbox").mkdir()
    (p / "inbox" / "areas-training-md.json").write_text(json.dumps({
        "path": "/areas/training.md", "version": "v9", "updated": "2026-11-11T08:00:00Z",
        "content": "# Training\n\n- Squat 405 lb\n- Deadlift 500 lb\n"}))
    compile_(p, projects, [])
    state = json.loads((p / "state.json").read_text())
    assert state["/areas/training.md"] == {"version": "v9"}


def test_a_pull_that_matches_the_last_push_keeps_its_pushed_hash(prof):
    import hashlib
    p, projects = prof
    content = "# Training\n\n- Squat 405 lb\n"
    sha = hashlib.sha256(content.encode()).hexdigest()
    (p / "state.json").write_text(json.dumps({"/areas/training.md": {"version": "old1", "pushed_sha256": sha}}))
    (p / "inbox").mkdir()
    (p / "inbox" / "areas-training-md.json").write_text(json.dumps({
        "path": "/areas/training.md", "version": "v9", "updated": "2026-11-11T08:00:00Z", "content": content}))
    compile_(p, projects, [])
    assert json.loads((p / "state.json").read_text())["/areas/training.md"] == {"version": "v9", "pushed_sha256": sha}


def test_a_chat_removal_is_not_reverted_by_the_next_push(prof):
    from um.bridge.adopt import record_synced
    from um.bridge.policy import DEFAULT_POLICY
    from um.bridge.prepare import build_outbox, pulled_texts, pulled_versions
    p, projects = prof
    base = "# Training\n\n- Squat 405 lb\n- Bench 300 lb\n"
    (p / "areas" / "training.md").write_text(base)
    record_synced(p, "/areas/training.md", base)
    (p / "state.json").write_text(json.dumps({"/areas/training.md": {"version": "v1"}}))
    (p / "inbox").mkdir()
    (p / "inbox" / "areas-training-md.json").write_text(json.dumps({
        "path": "/areas/training.md", "version": "v2", "updated": "2026-11-11T08:00:00Z",
        "content": "# Training\n\n- Bench 290 lb\n"}))
    compile_(p, projects, [])
    text = (p / "areas" / "training.md").read_text()
    assert "Squat" not in text and "Bench 300" not in text and "Bench 290" in text
    state = json.loads((p / "state.json").read_text())
    cats = {}
    m = build_outbox(p, p / "outbox", {**DEFAULT_POLICY, "other": "push"}, cats, state, "live",
                     pulled=pulled_versions(p), memory_text=pulled_texts(p))
    assert all(e.path != "/areas/training.md" for e in m.entries)


def test_a_pull_with_no_base_keeps_the_old_version_so_the_push_conflicts(prof):
    p, projects = prof
    (p / "state.json").write_text(json.dumps({"/areas/training.md": {"version": "v1"}}))
    (p / "inbox").mkdir()
    (p / "inbox" / "areas-training-md.json").write_text(json.dumps({
        "path": "/areas/training.md", "version": "v2", "updated": "2026-11-11T08:00:00Z",
        "content": "# Training\n\n- Bench 290 lb\n"}))
    compile_(p, projects, [])
    assert json.loads((p / "state.json").read_text())["/areas/training.md"]["version"] == "v1"
    assert "no common base" in (p / "digest" / "2026-11-11.md").read_text()


def test_a_failed_compile_consumes_nothing(prof):
    p, projects = prof
    (p / "inbox").mkdir()
    (p / "inbox" / "x.json").write_text(json.dumps({"path": "/areas/training.md", "version": "v2",
                                                    "updated": "2026-11-11T08:00:00Z", "content": "# T\n- a\n"}))
    compile_(p, projects, "not json at all")
    assert (p / "inbox" / "x.json").exists()
    assert not (p / ".um" / "build.json").exists()


def _erase(p, *values):
    args = ["erase", "--profile", str(p)]
    for v in values:
        args += ["--value", v]
    main(args + ["--raw-root", str(p / "nothing"), "--yes"])


def test_an_erased_line_is_not_brought_back_by_a_later_pull(prof):
    from um.bridge.adopt import record_synced
    p, projects = prof
    base = "# Training\n\n- Squat 405 lb\n- Coach is Zorbo\n"
    (p / "areas" / "training.md").write_text(base)
    record_synced(p, "/areas/training.md", base)
    _erase(p, "Zorbo")
    assert "Zorbo" not in (p / ".um" / "synced" / "areas-training-md.md").read_text()
    (p / "inbox").mkdir()
    (p / "inbox" / "a.json").write_text(json.dumps({"path": "/areas/training.md", "version": "v2",
                                                    "updated": "2026-11-12T08:00:00Z",
                                                    "content": base + "- Deadlift 500 lb\n"}))
    compile_(p, projects, [])
    text = (p / "areas" / "training.md").read_text()
    assert "Zorbo" not in text and "Deadlift" in text


def test_erase_that_empties_a_file_approves_its_deletion_from_memory(prof, capsys):
    from um.bridge.adopt import record_synced
    p, projects = prof
    (p / "areas" / "coach.md").write_text("---\nname: coach\n---\n- Coach is Zorbo\n")
    record_synced(p, "/areas/coach.md", "---\nname: coach\n---\n- Coach is Zorbo\n")
    _erase(p, "Zorbo")
    assert not (p / "areas" / "coach.md").exists()
    assert "/areas/coach.md" in (p / "delete-approved.txt").read_text()
    out = capsys.readouterr().out
    assert "account memory still holds it" in out and "/areas/coach.md" in out


def test_erase_marks_earlier_transcript_messages_as_read(prof):
    p, projects = prof
    _erase(p, "Brightline")
    compile_(p, projects, [])
    assert not list((p / ".um" / "evidence").rglob("*user.md"))


def test_erase_finds_values_inside_escaped_json(prof, capsys):
    p, projects = prof
    (p / ".lineage.jsonl").write_text(json.dumps({"file": "profile.md", "line": "- Coach Zoë Brontë"}) + "\n")
    (p / ".pass.json").write_text(json.dumps({"changes": [{"new": "- Coach Zoë Brontë"}], "questions": []}))
    _erase(p, "Zoë Brontë")
    assert "Bront" not in (p / ".lineage.jsonl").read_text()
    assert "Bront" not in json.dumps(json.loads((p / ".pass.json").read_text()), ensure_ascii=False)
    assert "still present in the profile: nowhere" in capsys.readouterr().out


def test_bridge_bookkeeping_is_not_tracked_so_undo_survives_a_task_run(prof):
    p, projects = prof
    (p / "state.json").write_text("{}")
    (p / "bridge-log.jsonl").write_text("")
    git(p, "add", "-A")
    git(p, "commit", "-qm", "track them")
    compile_(p, projects, CHANGE)
    tracked = git(p, "ls-files").split()
    assert "state.json" not in tracked and "bridge-log.jsonl" not in tracked
    (p / "state.json").write_text('{"last_pull": "x"}')
    main(["undo", "--profile", str(p)])
    assert "- Works at Oakfield" in (p / "profile.md").read_text()


def test_subscription_only_mode_never_builds_an_api_client(monkeypatch):
    from um.cli import _llm
    from um.llm_sub import ClaudeCodeLLM
    monkeypatch.setenv("UM_LLM", "subscription")
    assert isinstance(_llm(), ClaudeCodeLLM)


def test_conflicts_and_a_bridge_error_reach_the_digest_and_status(prof, capsys):
    p, projects = prof
    (p / "inbox" / "conflicts").mkdir(parents=True)
    (p / "inbox" / "conflicts" / "areas-training-md.json").write_text(json.dumps({"path": "/areas/training.md"}))
    (p / "bridge-log.jsonl").write_text(json.dumps({"run_at": "2026-11-11T06:46:00Z", "error": "memory tool timed out"}) + "\n")
    compile_(p, projects, [])
    text = (p / "digest" / "2026-11-11.md").read_text()
    assert "## Needs you" in text and "/areas/training.md" in text and "memory tool timed out" in text
    main(["status", "--profile", str(p)])
    out = capsys.readouterr().out
    assert "1 conflict" in out and "memory tool timed out" in out


def test_compile_writes_expansion_words_for_the_hook_and_survives_a_bad_reply(prof):
    from um.expand import line_key, load_expansions
    from um.config import save_config
    save_config(standing=True)
    p, projects = prof
    words = lambda n: Reply(json.dumps({str(i): ["employer", "job"] for i in range(1, n + 1)}), "end_turn", 1, 1)
    llm = FakeLLM([Reply(json.dumps(CHANGE), "end_turn", 1, 1), words(2), Reply("oops", "end_turn", 1, 1), Reply(json.dumps({"1": "standing"}), "end_turn", 1, 1)])
    main(["compile", "--profile", str(p), "--projects", str(projects), "--today", "2026-11-11"], llm=llm)
    exp = load_expansions(p)
    assert exp[line_key("- Works at Brightline")] == ["employer", "job"]
    assert line_key("- Squat 405 lb") not in exp
    assert "Squat 405 lb (areas/training.md)" in (p / "claude-code.md").read_text()
    assert git(p, "status", "--porcelain").strip() == ""


def test_a_new_file_the_compile_adds_lands_where_the_hook_and_index_read(prof):
    p, projects = prof
    add = [{"op": "add", "file": "memory/hobbies.md", "new": "- Plays a mandolin",
            "citations": [{"evidence": "sfeedbeef-user", "quote": "I work at Brightline now."}]}]
    (projects / "-Users-x-repo" / f"{SID}.jsonl").write_text(json.dumps({
        "type": "user", "sessionId": SID, "timestamp": "2026-11-11T09:00:00Z", "isSidechain": False,
        "origin": {"kind": "human"}, "message": {"role": "user", "content": "I play a mandolin."}}) + "\n")
    add[0]["citations"][0]["quote"] = "I play a mandolin."
    compile_(p, projects, add)
    assert not (p / "memory").exists()
    assert "- Plays a mandolin" in (p / "topics" / "hobbies.md").read_text()


def test_compile_makes_no_hook_or_standing_calls_when_both_are_off(prof):
    from um.config import save_config
    p, projects = prof
    save_config(prompt_hook=False, standing=False)
    llm = compile_(p, projects, CHANGE)
    assert [c["label"] for c in llm.calls if c["label"] in ("expand", "standing")] == []
