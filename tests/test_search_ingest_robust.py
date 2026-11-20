"""Catch-up robustness (Plan 5 review I5, I6, I10): idle-closed exchanges that grow, bad records, failed files,
sdk-cli sessions found late, replaced files. Synthetic fixtures only."""
import json
import os

import pytest

from um.search import index as index_mod
from um.search.index import Index
from um.search.ingest import IDLE_S, catch_up
from um.search.model import Exchange, SessionDoc, chunks_of
from um.search.sources import code

T0 = 1_800_000_000.0


def user(uuid, text, ts, sid="sess-1", entrypoint="cli"):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": entrypoint, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


def assistant(text, ts, sid="sess-1", entrypoint="cli"):
    return {"type": "assistant", "uuid": f"a-{ts}", "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": entrypoint, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def turn(n, word, sid="sess-1", entrypoint="cli"):
    ts = f"2026-01-01T00:{n:02d}:00Z"
    return [user(f"{sid}-u{n}", f"question about {word}", ts, sid, entrypoint),
            assistant(f"answer about {word}", f"2026-01-01T00:{n:02d}:30Z", sid, entrypoint)]


def write(path, records, mtime=T0 - 1000, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode) as f:
        f.write("".join(json.dumps(r) + "\n" for r in records))
    os.utime(path, (mtime, mtime))
    return path


def tpath(tmp_path, sid="sess-1"):
    return tmp_path / "projects" / "-work-proj" / f"{sid}.jsonl"


def cu(index, tmp_path, now, **kw):
    return catch_up(index, projects=tmp_path / "projects", desktop=None, now=now, force=True, **kw)


def chunk_keys(index):
    return sorted(k for k, _ in index.iter_chunks())


def hits(index, q):
    return [h.chunk_key for h in index.search(q, limit=10, per_session=None)]


@pytest.fixture
def ix(tmp_path):
    i = Index(tmp_path / "idx" / "i.sqlite")
    yield i
    i.close()


# --- I5: text written after an idle close joins its exchange --------------------------------------------------------

def test_text_after_idle_close_joins_the_exchange(tmp_path, ix):
    p = write(tpath(tmp_path), [user("u1", "question about apples", "2026-01-01T00:00:00Z"),
                                assistant("first part", "2026-01-01T00:00:10Z")])
    cu(ix, tmp_path, T0)                                   # idle: the open exchange is closed and indexed
    assert hits(ix, "first") == ["code:sess-1#u1#0"]
    write(p, [assistant("second part kiwis", "2026-01-01T00:09:00Z")], mtime=T0 + 5, mode="a")
    cu(ix, tmp_path, T0 + 10)                              # not idle yet: nothing new closes
    r = cu(ix, tmp_path, T0 + 5 + IDLE_S + 1)
    assert r["chunks_written"] == 1
    assert chunk_keys(ix) == ["code:sess-1#u1#0"]
    assert hits(ix, "kiwis") == ["code:sess-1#u1#0"]
    assert "first part" in dict(ix.iter_chunks())["code:sess-1#u1#0"]


def test_idle_closed_file_is_not_reopened_until_it_changes(tmp_path, ix):
    write(tpath(tmp_path), turn(1, "apples"))
    assert cu(ix, tmp_path, T0)["files_read"] == 1
    assert cu(ix, tmp_path, T0 + 60)["files_read"] == 0


def test_text_after_idle_close_then_new_turn(tmp_path, ix):
    p = write(tpath(tmp_path), turn(1, "apples"))
    cu(ix, tmp_path, T0)
    write(p, [assistant("late kiwis", "2026-01-01T00:05:00Z")] + turn(6, "bananas"), mtime=T0 + 5, mode="a")
    cu(ix, tmp_path, T0 + 20)
    assert hits(ix, "kiwis") == ["code:sess-1#sess-1-u1#0"]
    assert chunk_keys(ix) == ["code:sess-1#sess-1-u1#0"]


# --- I6: bad records and failed files ------------------------------------------------------------------------------

def test_corrupt_line_mid_file_does_not_stick(tmp_path, ix):
    p = tpath(tmp_path)
    write(p, turn(1, "apples"))
    with open(p, "ab") as f:
        f.write(b"\xff\xfe not json\n")
    write(p, turn(2, "bananas") + turn(3, "cherries"), mode="a")
    cu(ix, tmp_path, T0)
    assert len(chunk_keys(ix)) == 3


def test_lone_surrogate_is_indexed(tmp_path, ix):
    write(tpath(tmp_path), [user("u1", "bad \ud800 apples", "2026-01-01T00:00:00Z"),
                            assistant("ok \udfff", "2026-01-01T00:00:01Z")] + turn(2, "bananas"))
    r = cu(ix, tmp_path, T0)
    assert r["files_failed"] == 0 and len(chunk_keys(ix)) == 2
    assert hits(ix, "apples") == ["code:sess-1#u1#0"]


def test_one_failing_file_does_not_stop_the_rest(tmp_path, ix, monkeypatch):
    bad = write(tpath(tmp_path, "sess-0"), turn(1, "apples", "sess-0"))
    write(tpath(tmp_path, "sess-1"), turn(1, "bananas"))
    real = code.read_transcript

    def flaky(path, **kw):
        if str(path) == str(bad):
            raise RuntimeError("boom")
        return real(path, **kw)

    monkeypatch.setattr(code, "read_transcript", flaky)
    r = cu(ix, tmp_path, T0)
    assert r["files_failed"] == 1 and r["files_read"] == 1
    assert hits(ix, "bananas") == ["code:sess-1#sess-1-u1#0"]
    assert ix.get_meta("catch_up_files_failed") == "1"
    assert not ix._db.in_transaction
    monkeypatch.setattr(code, "read_transcript", real)
    r = cu(ix, tmp_path, T0 + 60)                          # the failed file is tried again
    assert r["files_failed"] == 0 and hits(ix, "apples") == ["code:sess-0#sess-0-u1#0"]
    assert ix.get_meta("catch_up_files_failed") == "0"


def test_failed_upsert_rolls_back(tmp_path, ix, monkeypatch):
    s = SessionDoc("code", "s1", "T", "/p", None, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                   (Exchange("u1", "2026-01-01T00:00:00Z", "apples", "pears"),))

    def boom(text):
        raise RuntimeError("tokenize failed")

    monkeypatch.setattr(index_mod, "tokenize", boom)
    with pytest.raises(RuntimeError):
        ix.upsert_session(s, chunks_of(s), replace=True)
    assert not ix._db.in_transaction
    assert ix.session_meta("code:s1") is None


def test_cli_reports_failed_files(tmp_path, monkeypatch, capsys):
    from um.cli import main
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("UM_PROFILE", str(tmp_path / "claude-profile"))
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path / "share" / "search.sqlite"))
    write(tpath(tmp_path), turn(1, "apples"))

    def boom(path, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(code, "read_transcript", boom)
    roots = ["--projects", str(tmp_path / "projects"), "--desktop", str(tmp_path / "no-desktop")]
    main(["search", "index", *roots])
    assert "1 file failed" in capsys.readouterr().out
    main(["search", "status"])
    assert "files failed at the last catch-up: 1" in capsys.readouterr().out


# --- I10: an sdk-cli record found after the first read --------------------------------------------------------------

def test_sdk_session_found_after_bookkeeping_is_skipped(tmp_path, ix):
    p = write(tpath(tmp_path, "sdk-1"), [{"type": "ai-title", "aiTitle": "Bench", "sessionId": "sdk-1"},
                                        {"type": "summary", "summary": "x"}])
    cu(ix, tmp_path, T0)
    write(p, turn(1, "apples", "sdk-1", "sdk-cli"), mtime=T0 - 900, mode="a")
    cu(ix, tmp_path, T0 + 60)
    assert chunk_keys(ix) == [] and ix.stats()["sessions"] == {}


def test_sdk_record_in_indexed_session_drops_it(tmp_path, ix):
    p = write(tpath(tmp_path, "sdk-1"), turn(1, "apples", "sdk-1", "sdk-cli"))
    cu(ix, tmp_path, T0, include_sdk=True)
    assert len(chunk_keys(ix)) == 1
    write(p, turn(2, "bananas", "sdk-1", "sdk-cli"), mtime=T0 + 5, mode="a")
    cu(ix, tmp_path, T0 + 5 + IDLE_S + 1)
    assert chunk_keys(ix) == [] and ix.stats()["sessions"] == {}


# --- minor: a file replaced by a longer one is read whole ----------------------------------------------------------

def test_replaced_longer_file_is_reread_whole(tmp_path, ix):
    p = write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"))
    cu(ix, tmp_path, T0)
    assert ix.cursor(str(p)).offset > 0
    p.unlink()
    write(p, turn(1, "damsons", "sess-1") + turn(2, "elderberries") + turn(3, "figs"), mtime=T0 + 5)
    assert p.stat().st_size > ix.cursor(str(p)).size
    cu(ix, tmp_path, T0 + 5 + IDLE_S + 1)
    fresh = Index(tmp_path / "idx" / "fresh.sqlite")
    cu(fresh, tmp_path, T0 + 5 + IDLE_S + 1)
    assert dict(ix.iter_chunks()) == dict(fresh.iter_chunks())
    assert hits(ix, "apples") == [] and len(hits(ix, "damsons")) == 1
    fresh.close()


def test_forget_all_then_catch_up_rebuilds_idle_closed_files(tmp_path, ix):
    write(tpath(tmp_path), turn(1, "apples"))
    cu(ix, tmp_path, T0)
    ix.forget_all()
    assert hits(ix, "apples") == []
    cu(ix, tmp_path, T0 + 60)
    assert hits(ix, "apples") == ["code:sess-1#sess-1-u1#0"]
