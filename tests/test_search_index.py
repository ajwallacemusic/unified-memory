"""The conversation-search index (Plan 5, Task 2). Synthetic fixtures only."""
import json
import stat
import subprocess
from pathlib import Path

import pytest

from um.config import search_include_sdk, search_index_path
from um.search.bm25 import BM25
from um.search.index import DEFAULT_PATH, Cursor, Index, check_index_path
from um.search.model import Exchange, SessionDoc, chunks_of, digest


def mk(native_id, *pairs, surface="code", project="/p", at="2026-01-01T00:00:00Z", title="T", source_path=None):
    ex = tuple(Exchange(f"{native_id}-u{i}", at, u, a) for i, (u, a) in enumerate(pairs))
    return SessionDoc(surface, native_id, title, project, None, at, at, ex, source_path)


def put(ix, s, replace=True):
    return ix.upsert_session(s, chunks_of(s), replace=replace)


@pytest.fixture
def ix(tmp_path):
    i = Index(tmp_path / "i.sqlite")
    yield i
    i.close()


def test_file_and_dir_modes(tmp_path):
    ix = Index(tmp_path / "d" / "i.sqlite")
    assert stat.S_IMODE((tmp_path / "d").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "d" / "i.sqlite").stat().st_mode) == 0o600
    assert len(ix.get_meta("salt")) == 32 and ix.get_meta("schema_version") == "1"
    ix.close()


def test_scores_equal_in_memory_bm25(ix):
    texts = ["red guitar amp", "blue amp settings", "guitar strings and guitar picks", "tax return"]
    for i, t in enumerate(texts):
        put(ix, mk(f"s{i}", ("", t), title=""))
    want = BM25(texts).scores("guitar amp")
    got = {h.native_id: h.score for h in ix.search("guitar amp", limit=10, per_session=None)}
    assert {f"s{i}": round(w, 6) for i, w in enumerate(want) if w > 0} == {k: round(v, 6) for k, v in got.items()}


def test_upsert_is_idempotent(ix):
    s = mk("s1", ("q", "a"))
    put(ix, s)
    put(ix, s)
    assert ix.stats()["chunks"] == {"code": 1}


def test_replace_drops_missing_chunks_append_keeps_them(ix):
    put(ix, mk("s1", ("alpha question", "alpha answer"), ("beta question", "beta answer")))
    one = mk("s1", ("alpha question", "alpha answer"))
    put(ix, one, replace=False)
    assert ix.stats()["chunks"] == {"code": 2} and ix.session_meta("code:s1")["n_turns"] == 2
    assert put(ix, one, replace=True) == (0, 1)
    assert ix.stats()["chunks"] == {"code": 1} and ix.session_meta("code:s1")["n_turns"] == 1
    assert ix.search("beta") == []
    n = ix._db.execute("SELECT count(*) FROM postings WHERE term = 'beta'").fetchone()[0]
    assert n == 0


def test_per_session_cap_and_spread(ix):
    put(ix, mk("s1", *[("guitar", f"guitar note {i}") for i in range(4)]))
    put(ix, mk("s2", ("guitar", "other")))
    put(ix, mk("s3", ("guitar", "third")))
    hits = ix.search("guitar", limit=5)
    ids = [h.native_id for h in hits]
    assert ids.count("s1") <= 2 and "s2" in ids and "s3" in ids
    assert len(ix.search("guitar", limit=10, per_session=None)) == 6


def test_filters(ix):
    put(ix, mk("s1", ("amp", "one"), at="2026-01-01T10:00:00Z"))
    put(ix, mk("s2", ("amp", "two"), at="2026-02-01T10:00:00Z"))
    put(ix, mk("w1", ("amp", "web"), surface="web", project=None, at="2026-03-01T10:00:00Z"))
    ids = lambda **kw: sorted(h.native_id for h in ix.search("amp", **kw))
    assert ids(after="2026-01-15") == ["s2", "w1"]
    assert ids(before="2026-02-01") == ["s1", "s2"]          # bare date is inclusive of that day
    assert ids(before="2026-02-01T00:00:00Z") == ["s1"]
    assert ids(surfaces=("web",)) == ["w1"]
    assert ids(project="/P") == ["s1", "s2"]
    assert ids(within="s1") == ["s1"] and ids(within="code:s2") == ["s2"]
    assert ids(exclude="s1") == ["s2", "w1"] and ids(exclude="web:w1") == ["s1", "s2"]


def test_sort_newest_and_oldest(ix):
    put(ix, mk("old", ("amp amp amp", "x"), at="2025-01-01T00:00:00Z"))
    put(ix, mk("mid", ("amp", "x"), at="2025-06-01T00:00:00Z"))
    put(ix, mk("new", ("amp", "x y z"), at="2026-01-01T00:00:00Z"))
    assert [h.native_id for h in ix.search("amp", sort="newest")] == ["new", "mid", "old"]
    assert [h.native_id for h in ix.search("amp", sort="oldest")] == ["old", "mid", "new"]
    assert ix.search("amp")[0].native_id == "old"


def test_half_life_prefers_newer_of_two_equal_matches(ix):
    put(ix, mk("a", ("guitar", "x"), at="2025-01-01T00:00:00Z"))
    put(ix, mk("b", ("guitar", "x"), at="2026-01-01T00:00:00Z"))
    plain = ix.search("guitar")
    assert plain[0].score == plain[1].score
    hits = ix.search("guitar", now="2026-01-02T00:00:00Z", half_life_days=90)
    assert hits[0].native_id == "b" and hits[0].score > hits[1].score


def test_stopword_only_query_returns_nothing(ix):
    put(ix, mk("s1", ("the of and", "it is")))
    assert ix.search("the of and") == []
    assert ix.search("!!! ...") == []


def test_config_readers(tmp_path, monkeypatch):
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.delenv("UM_SEARCH_INDEX", raising=False)
    assert search_index_path() == Path(DEFAULT_PATH).expanduser()
    assert search_include_sdk() is False
    (tmp_path / "cfg.json").write_text(json.dumps({"search_index": str(tmp_path / "c.sqlite"), "search_include_sdk": True}))
    assert search_index_path() == tmp_path / "c.sqlite" and search_include_sdk() is True
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path / "e.sqlite"))
    assert search_index_path() == tmp_path / "e.sqlite"


def test_tombstoned_key_is_not_rewritten(ix):
    s = mk("s1", ("alpha", "one"), ("beta", "two"))
    put(ix, s)
    k = chunks_of(s)[0].chunk_key
    assert ix.delete_chunks([k], tombstone=True) == 1
    put(ix, s)
    assert [h.chunk_key for h in ix.search("alpha beta", per_session=None)] == [chunks_of(s)[1].chunk_key]
    assert ix.delete_session("code:s1", tombstone=True) == 1
    put(ix, s)
    assert ix.stats()["chunks"] == {} and ix.session_meta("code:s1") is None


def test_erased_value_is_not_written(ix):
    from um.search.erasematch import value_digest
    ix.add_erased(*value_digest(ix.get_meta("salt"), "maple street"))
    put(ix, mk("s1", ("I live on Maple STREET now", "ok")))
    assert ix.stats()["chunks"] == {}


def test_empty_title_keeps_old_title(ix):
    put(ix, mk("s1", ("q", "a"), title="Amp repair"))
    put(ix, mk("s1", ("q", "a"), title=""))
    assert ix.session_meta("code:s1")["title"] == "Amp repair"
    assert ix.search("repair")[0].title == "Amp repair"


def test_recent_orders_and_snippets(ix):
    put(ix, mk("a", ("first " + "x" * 300, "r"), ("last q", "r"), at="2026-01-01T00:00:00Z"))
    put(ix, mk("b", ("only", "r"), at="2026-03-01T00:00:00Z", surface="web", project=None))
    put(ix, mk("c", ("mid", "r"), at="2026-02-01T00:00:00Z"))
    rows = ix.recent()
    assert [r.native_id for r in rows] == ["b", "c", "a"]
    a = rows[2]
    assert a.first_user == ("first " + "x" * 300)[:200] and a.last_user == "last q" and a.n_turns == 2
    assert [r.native_id for r in ix.recent(order="asc", n=2)] == ["a", "c"]
    assert [r.native_id for r in ix.recent(surfaces=("code",), after="2026-01-15")] == ["c"]
    assert [r.native_id for r in ix.recent(project="/p", before="2026-01-01")] == ["a"]


def test_cursor_roundtrip_and_mark_gone(ix):
    assert ix.cursor("/x.jsonl") is None
    c = Cursor("/x.jsonl", "code", "code:s1", 10, 1.5, 7)
    ix.set_cursor(c)
    assert ix.cursor("/x.jsonl") == c
    ix.set_cursor(Cursor("/x.jsonl", "code", "code:s1", 20, 2.5, 20))
    assert ix.cursor("/x.jsonl").offset == 20
    put(ix, mk("s1", ("q", "a"), source_path="/x.jsonl"))
    put(ix, mk("s2", ("q", "a"), source_path="/y.jsonl"))
    assert ix.session_meta("code:s1")["source_path"] == "/x.jsonl"
    assert ix.mark_gone("code", {"/y.jsonl"}) == 1
    assert ix.stats()["source_gone"] == 1 and ix.session_keys("code") == {"code:s1", "code:s2"}


def test_check_index_path_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    profile = tmp_path / "profile"
    for bad in (repo / "sub" / "i.sqlite", profile / "i.sqlite", tmp_path / "home" / ".claude" / "x" / "i.sqlite"):
        with pytest.raises(ValueError):
            check_index_path(bad, profile)
    check_index_path(tmp_path / "ok" / "i.sqlite", profile)
