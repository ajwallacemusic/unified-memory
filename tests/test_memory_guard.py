import io
import json

import pytest

from um.evidence import load_evidence
from um.hooks.memory_guard import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    prot, prof, state = tmp_path / "memory", tmp_path / "profile", tmp_path / "state"
    prot.mkdir()
    monkeypatch.setenv("UM_STATE_DIR", str(state))
    monkeypatch.setenv("UM_PROTECTED", str(prot))
    monkeypatch.setenv("UM_PROFILE", str(prof))
    return prot, prof, state


def run(cmd, event):
    out, err = io.StringIO(), io.StringIO()
    raw = event if isinstance(event, str) else json.dumps(event)
    code = main([cmd], stdin=io.StringIO(raw), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def ev(name, **kw):
    return {"session_id": "s1", "hook_event_name": name, "cwd": "/tmp", **kw}


def write(path, content="- Employer: Zorbo"):
    return ev("PreToolUse", tool_name="Write", tool_input={"file_path": str(path), "content": content})


def taint(tool="Bash"):
    return ev("PostToolUse", tool_name=tool, tool_input={}, tool_response={"stdout": "Sync report: employer Zorbo"})


def test_clean_turn_write_to_protected_path_passes(env):
    prot, _, _ = env
    run("clear", ev("UserPromptSubmit", prompt="hi"))
    code, out, _ = run("guard", write(prot / "MEMORY.md"))
    assert code == 0 and out.strip() == ""


def test_tainted_turn_write_is_denied_and_held(env):
    prot, prof, _ = env
    run("clear", ev("UserPromptSubmit", prompt="check the sync"))
    run("taint", taint("mcp__sync__fetch"))
    code, out, _ = run("guard", write(prot / "work.md"))
    d = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and d["hookEventName"] == "PreToolUse" and d["permissionDecision"] == "deny"
    held = list((prof / "inbox" / "held").glob("*.md"))
    assert len(held) == 1 and str(held[0]) in d["permissionDecisionReason"]
    e = next(iter(load_evidence(held[0].parent).values()))
    assert e.origin == "tool-output" and "Zorbo" in e.text


def test_edit_new_string_is_what_gets_held(env):
    prot, prof, _ = env
    run("taint", taint("WebFetch"))
    e = ev("PreToolUse", tool_name="Edit", tool_input={"file_path": str(prot / "a.md"), "old_string": "- Old", "new_string": "- New Kestrel"})
    run("guard", e)
    assert "Kestrel" in next((prof / "inbox" / "held").glob("*.md")).read_text()


def test_clear_resets_taint(env):
    prot, _, _ = env
    run("taint", taint())
    run("clear", ev("UserPromptSubmit", prompt="next"))
    assert run("guard", write(prot / "a.md"))[1].strip() == ""


def test_read_tool_does_not_taint(env):
    prot, _, _ = env
    for tool in ("Read", "Grep", "Glob", "Edit", "Write"):
        run("taint", taint(tool))
    assert run("guard", write(prot / "a.md"))[1].strip() == ""


def test_state_holds_no_content(env):
    _, _, state = env
    run("taint", taint("mcp__sync__fetch"))
    text = "".join(p.read_text() for p in state.rglob("*") if p.is_file())
    assert "Zorbo" not in text and "mcp__sync__fetch" in text


def test_corrupt_state_denies_protected_write(env):
    prot, _, state = env
    state.mkdir(parents=True, exist_ok=True)
    (state / "session-s1.json").write_text("{not json")
    code, _, err = run("guard", write(prot / "a.md"))
    assert code == 2 and err


def test_garbled_stdin_denies(env):
    code, _, err = run("guard", "this is not json")
    assert code == 2 and err


def test_unprotected_path_is_untouched_even_when_tainted(env, tmp_path):
    run("taint", taint())
    code, out, _ = run("guard", write(tmp_path / "elsewhere" / "notes.md"))
    assert code == 0 and out.strip() == ""


def test_sessions_do_not_share_taint(env):
    prot, _, _ = env
    run("taint", taint())
    other = write(prot / "a.md")
    other["session_id"] = "s2"
    assert run("guard", other)[1].strip() == ""


def denied(result):
    code, out, _ = result
    return code == 2 or (out and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny")


def tainted_turn():
    run("clear", ev("UserPromptSubmit", prompt="check the sync"))
    run("taint", taint())


def test_missing_state_on_a_protected_write_denies(env):
    prot, _, _ = env
    assert denied(run("guard", write(prot / "x.md")))


@pytest.mark.parametrize("ti", ["not a dict", {"file_path": None, "edits": "garbled"}])
def test_malformed_tool_input_denies(env, ti):
    prot, _, _ = env
    tainted_turn()
    event = ev("PreToolUse", tool_name="MultiEdit", tool_input=ti)
    if isinstance(ti, dict):
        event["tool_input"]["file_path"] = str(prot / "x.md")
    assert denied(run("guard", event))


def test_a_hold_that_fails_still_denies(env, monkeypatch):
    prot, _, _ = env
    tainted_turn()
    import um.hooks.memory_guard as g
    monkeypatch.setattr(g, "_hold", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert denied(run("guard", write(prot / "x.md")))


def test_memory_delete_and_unknown_memory_tools_are_guarded(env):
    tainted_turn()
    for tool in ("mcp__memory__memory_delete", "mcp__memory__memory_rename"):
        assert denied(run("guard", ev("PreToolUse", tool_name=tool, tool_input={"path": "/x.md"})))
    run("clear", ev("UserPromptSubmit", prompt="hi"))
    run("taint", taint())
    assert run("guard", ev("PreToolUse", tool_name="mcp__memory__memory_read", tool_input={"path": "/x.md"}))[0] == 0


def test_case_and_relative_paths_are_matched(env, tmp_path):
    prot, _, _ = env
    tainted_turn()
    import sys
    if sys.platform == "darwin":
        assert denied(run("guard", write(str(prot).upper() + "/x.md")))
    rel = ev("PreToolUse", tool_name="Write", tool_input={"file_path": "memory/x.md", "content": "a"})
    rel["cwd"] = str(tmp_path)
    assert denied(run("guard", rel))


def test_a_shell_command_naming_a_protected_path_or_answer_is_held_in_a_tainted_turn(env):
    prot, _, _ = env
    tainted_turn()
    for cmd in (f"echo '- Employer: Zorbo' >> {prot}/MEMORY.md", "python -m um.cli answer --text 'Zorbo'"):
        assert denied(run("guard", ev("PreToolUse", tool_name="Bash", tool_input={"command": cmd})))
    run("clear", ev("UserPromptSubmit", prompt="hi"))
    assert run("guard", ev("PreToolUse", tool_name="Bash", tool_input={"command": f"cat {prot}/MEMORY.md"}))[0] == 0


def test_guard_taints_on_plugin_search_tool(env):
    prot, prof, _ = env
    run("clear", ev("UserPromptSubmit", prompt="what did we decide last month?"))
    run("taint", taint("mcp__plugin_unified-memory_um-search__conversation_search"))
    code, out, _ = run("guard", write(prot / "work.md"))
    d = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and d["permissionDecision"] == "deny"
    assert len(list((prof / "inbox" / "held").glob("*.md"))) == 1
