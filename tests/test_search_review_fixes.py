"""Review findings I4, I8, I9 and I11 on conversation search (Plan 5 review). Synthetic fixtures only; every path
is under tmp_path."""
import json
from pathlib import Path

import pytest

from um.cli import main
from um.search.index import Index
from um.search.model import CHUNK_CHARS, LEAD_CHARS, Exchange, SessionDoc, chunks_of, digest

ROOT = Path(__file__).resolve().parents[1]


def mk(native_id, *pairs, at="2026-01-01T00:00:00Z", title="T", source_path=None):
    ex = tuple(Exchange(f"{native_id}-u{i}", at, u, a, ("Bash",)) for i, (u, a) in enumerate(pairs))
    return SessionDoc("code", native_id, title, "/p", None, at, at, ex, source_path)


@pytest.fixture
def ix(tmp_path):
    i = Index(tmp_path / "i.sqlite")
    yield i
    i.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("UM_PROFILE", str(tmp_path / "claude-profile"))
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path / "share" / "search.sqlite"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    (tmp_path / "projects").mkdir()
    return {"index": tmp_path / "share" / "search.sqlite", "cfg": tmp_path / "cfg" / "config.json",
            "roots": ["--projects", str(tmp_path / "projects"), "--desktop", str(tmp_path / "no-desktop")]}


def search_off(env):
    env["cfg"].parent.mkdir(parents=True, exist_ok=True)
    env["cfg"].write_text(json.dumps({"search": False}))


# --- I8: the per-session cap is applied before truncating candidates --------------------------------------------

def test_one_dominant_session_does_not_starve_the_results(ix):
    big = mk("big", *[("zebra zebra zebra", f"zebra note {i}") for i in range(40)])
    ix.upsert_session(big, chunks_of(big), replace=True)
    for j in range(6):
        s = mk(f"other{j}", ("zebra", f"filler words here {j} " * 5))
        ix.upsert_session(s, chunks_of(s), replace=True)
    hits = ix.search("zebra", limit=5, per_session=1)
    assert len(hits) == 5
    assert len({h.session_key for h in hits}) == 5
    assert hits[0].native_id == "big"


# --- I9: chunk parameters are recorded, and a change re-chunks in place -----------------------------------------

def test_new_index_records_chunk_params(ix):
    assert ix.get_meta("chunk_chars") == str(CHUNK_CHARS)
    assert ix.get_meta("lead_chars") == str(LEAD_CHARS)
    assert ix.chunk_params_mismatch() is None


def _old_index(path):
    """An index written with chunk_chars=100, lead_chars=20; one session's source is gone, one turn is tombstoned
    and an erased sequence is recorded."""
    ix = Index(path)
    ix.set_meta("chunk_chars", "100")
    ix.set_meta("lead_chars", "20")
    long_a = " ".join(f"word{i}" for i in range(80))           # ~560 chars: several 100-char pieces
    s1 = mk("s1", ("tell me about the orchard", long_a), ("short q", "short a"), source_path="/gone.jsonl")
    s2 = mk("s2", ("tombstoned turn " + "pear " * 30, "kiwi " * 40), ("kept turn", "plum " * 40))
    for s in (s1, s2):
        ix.upsert_session(s, chunks_of(s, 100, 20), replace=True)
    ix.mark_gone("code", set())
    tomb = chunks_of(s2, 100, 20)[0].chunk_key
    ix.delete_chunks([tomb], tombstone=True)
    ix.add_erased(2, digest(ix.get_meta("salt"), ["maple", "street"]))
    return ix, s1, s2, tomb


def test_chunk_param_change_rechunks_in_place_and_keeps_erase_state(tmp_path):
    ix, s1, s2, tomb = _old_index(tmp_path / "i.sqlite")
    assert ix.chunk_params_mismatch() == {"stored": (100, 20), "current": (CHUNK_CHARS, LEAD_CHARS)}
    before_s2_turn0 = sorted(k for (k,) in ix._db.execute(
        "SELECT chunk_key FROM chunks WHERE turn_id = 's2-u0'"))
    r = ix.rechunk()
    assert r["sessions"] == 2 and r["turns_skipped"] == 1
    assert ix.chunk_params_mismatch() is None
    assert ix.get_meta("chunk_chars") == str(CHUNK_CHARS)
    # the session whose source file is gone is re-chunked from the stored text, not lost
    keys = sorted(k for (k,) in ix._db.execute("SELECT chunk_key FROM chunks WHERE session_key = 'code:s1'"))
    assert keys == sorted(c.chunk_key for c in chunks_of(s1))
    assert ix.stats()["source_gone"] == 1
    hit = ix.search("orchard word79", per_session=None)[0]
    assert hit.native_id == "s1" and "word0" in hit.assistant_text and "word79" in hit.assistant_text
    # a turn with a tombstoned part keeps its remaining chunks as they were; the tombstone and erased rows stay
    after_s2_turn0 = sorted(k for (k,) in ix._db.execute("SELECT chunk_key FROM chunks WHERE turn_id = 's2-u0'"))
    assert after_s2_turn0 == before_s2_turn0 and tomb not in after_s2_turn0
    assert ix._db.execute("SELECT count(*) FROM tombstones").fetchone()[0] == 1
    assert ix._db.execute("SELECT count(*) FROM erased_text").fetchone()[0] == 1
    # the untouched turn of s2 is now one chunk under the current params
    assert [k for (k,) in ix._db.execute("SELECT chunk_key FROM chunks WHERE turn_id = 's2-u1'")] == \
        [chunks_of(s2)[-1].chunk_key]
    # postings agree with the chunks: no orphan postings
    orphans = ix._db.execute("SELECT count(*) FROM postings WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks)")
    assert orphans.fetchone()[0] == 0
    ix.close()


def test_index_without_recorded_params_counts_as_mismatch(tmp_path):
    ix = Index(tmp_path / "i.sqlite")
    ix._db.execute("DELETE FROM meta WHERE key IN ('chunk_chars', 'lead_chars')")
    ix._db.commit()
    ix.close()
    ix = Index(tmp_path / "i.sqlite")
    assert ix.chunk_params_mismatch() == {"stored": None, "current": (CHUNK_CHARS, LEAD_CHARS)}
    ix.close()


def test_newer_schema_is_refused(tmp_path):
    ix = Index(tmp_path / "i.sqlite")
    ix.set_meta("schema_version", "999")
    ix.close()
    with pytest.raises(ValueError, match="newer"):
        Index(tmp_path / "i.sqlite")


def test_status_reports_mismatch_and_rebuild_fixes_it(env, capsys):
    ix, *_ = _old_index(env["index"])
    ix.close()
    main(["search", "status"])
    out = capsys.readouterr().out
    assert "chunking 100/20" in out and "search rebuild" in out
    main(["search", "rebuild"])
    out = capsys.readouterr().out
    assert "re-chunked 2 sessions" in out
    main(["search", "status"])
    assert f"chunking {CHUNK_CHARS}/{LEAD_CHARS} (current)" in capsys.readouterr().out


def test_cli_index_rechunks_a_mismatched_index(env, capsys):
    ix, *_ = _old_index(env["index"])
    ix.close()
    main(["search", "index", *env["roots"]])
    assert "re-chunked 2 sessions" in capsys.readouterr().out
    ix = Index(env["index"])
    assert ix.chunk_params_mismatch() is None
    ix.close()


def test_mcp_call_rechunks_a_mismatched_index_on_first_open(env):
    from um.search.mcp_server import make_call
    ix, *_ = _old_index(env["index"])
    ix.close()
    call = make_call(before_query=lambda index: {})
    out = call("conversation_search", {"query": "orchard"})
    assert "orchard" in out["text"]
    ix = Index(env["index"])
    assert ix.chunk_params_mismatch() is None
    ix.close()


# --- I4: search output never becomes compile evidence -------------------------------------------------------------

def _tool_call(tid, name, ts):
    return {"type": "assistant", "sessionId": "abcdef12", "timestamp": ts, "isSidechain": False, "uuid": "y",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def _tool_result(tid, content, ts):
    return {"type": "user", "sessionId": "abcdef12", "timestamp": ts, "isSidechain": False, "uuid": "x",
            "toolUseResult": {"stdout": "..."},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": content}]}}


def test_search_output_is_dropped_whatever_the_server_name_or_route(tmp_path):
    from um.search.tools import NOTICE
    from um.evidence import load_evidence
    from um.transcripts import evidence_from_transcript
    lines = [
        _tool_call("t1", "mcp__um-search__conversation_search", "2026-11-10T10:00:00Z"),
        _tool_result("t1", [{"type": "text", "text": "Index line\nFACT ONE"}], "2026-11-10T10:00:01Z"),
        _tool_call("t2", "mcp__my-unified-memory__recent_chats", "2026-11-10T10:00:02Z"),
        _tool_result("t2", "FACT TWO", "2026-11-10T10:00:03Z"),
        _tool_call("t3", "Bash", "2026-11-10T10:00:04Z"),
        _tool_result("t3", NOTICE + "\nIndex: ...\n[1] code \"x\"\nuser: FACT THREE", "2026-11-10T10:00:05Z"),
        _tool_call("t4", "Bash", "2026-11-10T10:00:06Z"),
        _tool_result("t4", [{"type": "text", "text": "  " + NOTICE + " FACT FOUR"}], "2026-11-10T10:00:07Z"),
        _tool_call("t5", "mcp__other-server__conversation_search", "2026-11-10T10:00:08Z"),
        _tool_result("t5", "other server kept", "2026-11-10T10:00:09Z"),
        _tool_call("t6", "Bash", "2026-11-10T10:00:10Z"),
        _tool_result("t6", "shell out", "2026-11-10T10:00:11Z"),
    ]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    out = tmp_path / "ev"
    evidence_from_transcript(p, out)
    t = {e.origin: e for e in load_evidence(out).values()}["tool-output"].text
    assert "shell out" in t and "other server kept" in t
    for fact in ("FACT ONE", "FACT TWO", "FACT THREE", "FACT FOUR"):
        assert fact not in t


def test_cli_query_and_recent_output_start_with_the_notice(env, capsys):
    from um.search.tools import NOTICE
    main(["search", "query", "anything", *env["roots"]])
    assert capsys.readouterr().out.startswith(NOTICE)
    main(["search", "recent", *env["roots"]])
    assert capsys.readouterr().out.startswith(NOTICE)


# --- I11: an off switch -------------------------------------------------------------------------------------------

def test_search_switch_config(env):
    from um.config import search_enabled
    assert search_enabled() is True
    search_off(env)
    assert search_enabled() is False
    env["cfg"].write_text(json.dumps({"search": True}))
    assert search_enabled() is True


def test_cli_index_refuses_when_search_is_off(env):
    search_off(env)
    with pytest.raises(SystemExit) as e:
        main(["search", "index", *env["roots"]])
    assert "search is off" in str(e.value.code)
    assert not env["index"].exists()


def test_session_start_hook_is_a_quiet_no_op_when_off(env, capsys):
    hooks = json.loads((ROOT / "plugin_src" / "hooks" / "hooks.json").read_text())
    cmd = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "search index --if-enabled" in cmd
    search_off(env)
    main(["search", "index", "--if-enabled", *env["roots"]])   # no SystemExit
    assert capsys.readouterr().out == ""
    assert not env["index"].exists()


def test_mcp_tools_answer_that_search_is_off_without_catch_up(env):
    from um.search.mcp_server import make_call
    search_off(env)
    ran = []
    call = make_call(before_query=lambda index: ran.append(1) or {})
    for name, args in (("conversation_search", {"query": "x"}), ("recent_chats", {})):
        out = call(name, args)
        assert "search is off" in out["text"].lower()
        assert out["structured"]["search"] == "off"
    assert ran == [] and not env["index"].exists()
