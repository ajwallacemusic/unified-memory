"""Erase and forget on the conversation-search index (Plan 5, Task 8). Synthetic fixtures only."""
import pytest

from um.search.forget import erase_from_index, forget_session
from um.search.index import Index
from um.search.model import Exchange, SessionDoc, chunks_of


def mk(native_id, *pairs, surface="code", title="T", at="2026-01-01T00:00:00Z"):
    ex = tuple(Exchange(f"{native_id}-u{i}", at, u, a) for i, (u, a) in enumerate(pairs))
    return SessionDoc(surface, native_id, title, "/p", None, at, at, ex, None)


def put(ix, s):
    return ix.upsert_session(s, chunks_of(s), replace=True)


def keys(ix):
    return {k for k, _ in ix.iter_chunks()}


@pytest.fixture
def ix(tmp_path):
    i = Index(tmp_path / "i.sqlite")
    yield i
    i.close()


def test_erase_removes_whole_chunk_and_postings(ix):
    put(ix, mk("s1", ("my locker code is quokkamint", "noted the walrusberry reminder")))
    assert ix.search("walrusberry")
    out = erase_from_index(ix, ["quokkamint"])
    assert out == {"chunks": 1, "sessions": 1}
    assert ix.search("walrusberry") == []
    assert ix.search("quokkamint") == []


def test_erase_reaches_assistant_text_and_lead(ix):
    long_user = "zebrafig opening line " + "filler words here " * 300
    put(ix, mk("s1", (long_user, "the answer mentions nothing special " * 10), ("hello", "assistant says plumcrest")))
    # the long exchange is split: its assistant-only chunks carry the user lead holding "zebrafig"
    assert any("#s1-u0#" in k for k in keys(ix))
    before = dict(ix.iter_chunks())
    lead_chunks = {k for k, t in before.items() if "#s1-u0#" in k and t.split("\n")[1]}
    assert lead_chunks
    out = erase_from_index(ix, ["zebrafig"])
    after = dict(ix.iter_chunks())
    assert not lead_chunks & set(after)
    assert all("zebrafig" not in t for t in after.values())
    assert out["chunks"] == len(lead_chunks) + 1
    erase_from_index(ix, ["plumcrest"])
    assert keys(ix) == {"code:s1#s1-u0#1"}   # the second user piece: neither the value nor a lead


def test_erase_matches_case_and_escapes(ix):
    put(ix, mk("s1", ("my friend zoë is visiting", "ok")))
    put(ix, mk("s2", ("pasted json: {\"name\": \"Zo\\u00eb\"}", "ok")))
    put(ix, mk("s3", ("raw escape Zo\\u00eb here", "ok")))
    put(ix, mk("s4", ("nobody relevant", "ok")))
    out = erase_from_index(ix, ["ZOË"])
    assert out == {"chunks": 3, "sessions": 3}
    assert keys(ix) == {"code:s4#s4-u0#0"}


def test_erased_value_does_not_return_on_reingest(ix):
    s = mk("s1", ("remember quokkamint please", "sure"))
    put(ix, s)
    erase_from_index(ix, ["quokkamint"])
    put(ix, s)
    assert keys(ix) == set()
    assert ix.search("quokkamint") == []


def test_erased_value_does_not_return_on_later_ingest(ix):
    put(ix, mk("s1", ("unrelated", "fine")))
    erase_from_index(ix, ["Quokka Mint Lane"])
    put(ix, mk("w9", ("I live on quokka mint lane now", "noted"), ("other turn", "fine"), surface="web"))
    assert ix.search("quokka") == []
    assert keys(ix) == {"code:s1#s1-u0#0", "web:w9#w9-u1#0"}
    # the later-ingest guard matches as erase time does: case-folded substring, JSON escapes decoded
    erase_from_index(ix, ["Zoëlle"])
    put(ix, mk("w10", ("call zoëlle_client_api()", "ok"), ("the ZoëlleClient class", "ok"),
               ("pasted {\"n\": \"Zo\\u00eblle\"} here", "ok"), ("raw Zo\\u00eblle_x too", "ok"),
               ("plain zoelle survives", "ok"), surface="web"))
    assert keys(ix) == {"code:s1#s1-u0#0", "web:w9#w9-u1#0", "web:w10#w10-u4#0"}
    erase_from_index(ix, ["walrusberry"])
    put(ix, mk("w11", ("the WalrusBerryFactory", "ok"), ("x_walrusberry_y", "ok"), ("walrus berry", "ok"),
               surface="web"))
    assert keys(ix) - {"code:s1#s1-u0#0", "web:w9#w9-u1#0", "web:w10#w10-u4#0"} == {"web:w11#w11-u2#0"}


def test_symbol_values_do_not_drop_every_chunk_with_a_common_word(ix):
    erase_from_index(ix, ["C++"])
    erase_from_index(ix, ["$50"])
    put(ix, mk("s1", ("I wrote it in c", "ok"), ("costs 50 dollars", "ok"), ("templates in C++ are hard", "ok"),
               ("it was $50.00", "ok")))
    assert keys(ix) == {"code:s1#s1-u0#0", "code:s1#s1-u1#0"}


def test_erase_records_the_guard_before_scanning(ix, monkeypatch):
    """An ingest that lands between the scan and the record must still be dropped: the record comes first."""
    put(ix, mk("s1", ("quokkamint", "a")))
    seen = []
    real = ix.iter_chunks

    def spy():
        snapshot = list(real())
        put(ix, mk("late", ("a late quokkamint chunk", "b")))   # a concurrent ingest just after the scan
        seen.append(True)
        return iter(snapshot)
    monkeypatch.setattr(ix, "iter_chunks", spy)
    erase_from_index(ix, ["quokkamint"])
    assert seen and keys(ix) == set()


def test_guard_cost_skips_unchanged_chunks(ix, monkeypatch):
    s = mk("s1", ("hello there", "general kenobi"))
    put(ix, s)
    erase_from_index(ix, ["quokkamint"])
    import um.search.index as index_mod
    calls = []
    monkeypatch.setattr(index_mod, "erased_hit", lambda *a, **k: calls.append(1) or False)
    put(ix, s)
    assert calls == []


def test_other_chunks_survive(ix):
    put(ix, mk("s1", ("quokkamint here", "a"), ("keep this turn about gardens", "b")))
    put(ix, mk("s2", ("unrelated gardens", "c")))
    out = erase_from_index(ix, ["quokkamint"])
    assert out == {"chunks": 1, "sessions": 1}
    assert keys(ix) == {"code:s1#s1-u1#0", "code:s2#s2-u0#0"}
    assert len(ix.search("gardens")) == 2


def test_value_is_not_stored_anywhere(ix, tmp_path):
    put(ix, mk("s1", ("secret Quokkamint Value", "echo QUOKKAMINT value"), ("other", "fine")))
    put(ix, mk("s2", ("nothing", "here"), title="about quokkamint value"))
    out = erase_from_index(ix, ["quokkamint value"])
    assert "quokkamint" not in repr(out).lower()
    data = (tmp_path / "i.sqlite").read_bytes().lower()
    assert b"quokkamint" not in data
    for p in tmp_path.iterdir():
        assert b"quokkamint" not in p.read_bytes().lower()


def test_short_value_is_refused(ix):
    put(ix, mk("s1", ("ab cd", "ok")))
    with pytest.raises(ValueError):
        erase_from_index(ix, ["ab"])
    with pytest.raises(ValueError):
        erase_from_index(ix, [])
    assert keys(ix) == {"code:s1#s1-u0#0"}


def test_forget_session_tombstones(ix):
    s = mk("s1", ("first", "a"), ("second", "b"))
    put(ix, s)
    put(ix, mk("s2", ("keep", "c")))
    assert forget_session(ix, "s1") == 2
    assert keys(ix) == {"code:s2#s2-u0#0"}
    put(ix, s)
    assert keys(ix) == {"code:s2#s2-u0#0"}
    assert forget_session(ix, "code:s2") == 1
    assert keys(ix) == set()
    assert forget_session(ix, "nope") == 0
