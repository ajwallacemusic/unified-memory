"""`um.cli search` subcommands and the status line (Plan 5 Task 9). Synthetic fixtures only; every path is under
tmp_path (HOME too, so no default can reach ~/.claude or ~/Library)."""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

import pytest

from um.cli import main


def user(uuid, text, ts, sid):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": "cli", "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


def assistant(text, ts, sid):
    return {"type": "assistant", "uuid": f"a-{sid}-{ts}", "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": "cli", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def transcript(projects, sid, user_text, answer):
    path = projects / "-work-proj" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [user(f"{sid}-u1", user_text, "2026-01-01T00:01:00Z", sid),
            assistant(answer, "2026-01-01T00:01:30Z", sid)]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    old = time.time() - 3600          # idle: the last exchange is closed
    os.utime(path, (old, old))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("UM_PROFILE", str(tmp_path / "claude-profile"))
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path / "share" / "search.sqlite"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    projects = tmp_path / "projects"
    projects.mkdir()
    return {"projects": projects, "desktop": tmp_path / "no-desktop", "index": tmp_path / "share" / "search.sqlite"}


def roots(env):
    return ["--projects", str(env["projects"]), "--desktop", str(env["desktop"])]


def test_index_then_query_finds_a_turn(env, capsys):
    transcript(env["projects"], "s-banjo", "how do I tune a banjo", "use open G tuning for the banjo")
    main(["search", "index", *roots(env)])
    capsys.readouterr()
    main(["search", "query", "banjo", "tuning", *roots(env)])
    out = capsys.readouterr().out
    assert out.startswith("Past-conversation search results.")
    assert "open G tuning" in out and "s-banjo" in out
    main(["search", "recent", "--n", "3", "--order", "asc", *roots(env)])
    assert "s-banjo" in capsys.readouterr().out


def test_query_rejects_a_bad_argument(env):
    main(["search", "index", *roots(env)])
    with pytest.raises(SystemExit) as e:
        main(["search", "query", "banjo", "--surface", "fax", *roots(env)])
    assert "surface" in str(e.value.code)


def test_import_export_then_status(env, tmp_path, capsys):
    day = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()   # ages are UTC days
    conv = {"uuid": "c1", "name": "Sourdough", "created_at": f"{day}T10:00:00Z", "updated_at": f"{day}T11:00:00Z",
            "chat_messages": [
                {"uuid": "h1", "sender": "human", "parent_message_uuid": None, "created_at": f"{day}T10:00:00Z",
                 "content": [{"type": "text", "text": "how do i bake sourdough"}]},
                {"uuid": "a1", "sender": "assistant", "parent_message_uuid": "h1", "created_at": f"{day}T10:00:05Z",
                 "content": [{"type": "text", "text": "feed the starter first"}]}]}
    p = tmp_path / "export" / "conversations.json"
    p.parent.mkdir()
    p.write_text(json.dumps([conv]))
    main(["search", "import-export", str(p)])
    assert "1 added" in capsys.readouterr().out
    main(["search", "status"])
    out = capsys.readouterr().out
    assert "web" in out and day in out and "3 days old" in out
    assert "source gone: 0" in out


def test_index_path_inside_profile_is_refused(env, tmp_path, monkeypatch):
    inside = tmp_path / "claude-profile" / "search.sqlite"
    monkeypatch.setenv("UM_SEARCH_INDEX", str(inside))
    with pytest.raises(SystemExit) as e:
        main(["search", "status"])
    assert "profile" in str(e.value.code)
    assert not inside.exists()


def test_index_path_inside_git_tree_is_refused(env, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    inside = repo / "data" / "search.sqlite"
    monkeypatch.setenv("UM_SEARCH_INDEX", str(inside))
    with pytest.raises(SystemExit) as e:
        main(["search", "index", *roots(env)])
    assert "git work tree" in str(e.value.code)
    assert not inside.exists()


def test_forget_all_empties_content_but_keeps_erase_state(env, capsys):
    transcript(env["projects"], "s-1", "remember the kiln", "the kiln fires at cone 6")
    transcript(env["projects"], "s-2", "my quokkamint locker", "noted")
    main(["search", "index", *roots(env)])
    from um.search.forget import erase_from_index
    from um.search.index import Index
    ix = Index(env["index"])
    erase_from_index(ix, ["QuokkaMint"])
    server = Index(env["index"])                       # a running MCP server holds its own connection
    assert server.search("kiln")
    with pytest.raises(SystemExit):
        main(["search", "forget", "--all"])            # no --yes
    assert server.search("kiln")
    main(["search", "forget", "--all", "--yes"])
    assert "search index emptied" in capsys.readouterr().out
    assert server.search("kiln") == [] and list(server.iter_chunks()) == []
    assert server.recent() == []
    assert env["index"].exists()
    data = env["index"].read_bytes()
    assert b"kiln" not in data and b"cone 6" not in data   # vacuumed: no text left in free pages
    assert not env["index"].with_name(env["index"].name + "-journal").exists()
    # the next catch-up rebuilds from transcripts, and the erased value still does not come back
    main(["search", "index", *roots(env)])
    assert server.search("kiln")
    assert server.search("quokkamint") == [] and server.search("locker") == []
    server.close()
    ix.close()


def test_erase_without_an_index_still_guards_a_later_build(env, capsys, tmp_path):
    import subprocess
    p = tmp_path / "claude-profile"
    p.mkdir()
    (p / "profile.md").write_text("# Profile\n\n- Likes kilns\n")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(p), *args], check=True, capture_output=True)
    transcript(env["projects"], "s-2", "my quokkamint locker", "noted")
    transcript(env["projects"], "s-1", "remember the kiln", "the kiln fires at cone 6")
    assert not env["index"].exists()
    main(["erase", "--profile", str(p), "--value", "quokkamint", "--raw-root", str(tmp_path / "none"), "--yes",
          *roots(env)])
    assert env["index"].exists()
    assert b"quokkamint" not in env["index"].read_bytes().lower()
    main(["search", "index", *roots(env)])
    capsys.readouterr()
    main(["search", "query", "locker", *roots(env)])
    assert "quokkamint" not in capsys.readouterr().out
    main(["search", "query", "kiln", *roots(env)])
    assert "cone 6" in capsys.readouterr().out


def test_forget_session(env, capsys):
    transcript(env["projects"], "s-1", "remember the kiln", "the kiln fires at cone 6")
    transcript(env["projects"], "s-2", "remember the lathe", "the lathe needs oil")
    main(["search", "index", *roots(env)])
    main(["search", "forget", "--session", "s-1", "--yes"])
    capsys.readouterr()
    main(["search", "query", "kiln", *roots(env)])
    out = capsys.readouterr().out
    assert "cone 6" not in out


def test_status_line_in_um_status(env, tmp_path, capsys):
    p = tmp_path / "claude-profile"
    p.mkdir()
    main(["status", "--profile", str(p)])
    assert "search: no index" in capsys.readouterr().out
    assert not env["index"].exists()
    transcript(env["projects"], "s-1", "remember the kiln", "the kiln fires at cone 6")
    main(["search", "index", *roots(env)])
    capsys.readouterr()
    main(["status", "--profile", str(p)])
    assert "search: 1 sessions, no web export" in capsys.readouterr().out


def test_import_export_bad_inputs_give_one_line_errors(env, tmp_path):
    bad = tmp_path / "conversations-000.zip"
    bad.write_text("not a zip")
    missing = tmp_path / "nope.zip"
    for src in (bad, missing):
        with pytest.raises(SystemExit) as e:
            main(["search", "import-export", str(src)])
        msg = str(e.value.code)
        assert msg.startswith(f"{src}: ") and "\n" not in msg
