from um.search.bm25 import BM25, score, tokenize
from um.search.model import CHUNK_CHARS, LEAD_CHARS, Exchange, SessionDoc, chunks_of, digest, index_text, words


def _s(*ex): return SessionDoc("code", "s1", "T", "/p", None, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", tuple(ex))


def test_short_exchange_is_one_chunk():
    [c] = chunks_of(_s(Exchange("u1", "2026-01-01T00:00:00Z", "hello", "world")))
    assert (c.chunk_key, c.part, c.lead) == ("code:s1#u1#0", 0, "")


def test_long_answer_splits_and_carries_lead():
    cs = chunks_of(_s(Exchange("u1", "t", "q " * 200, ("para " * 300 + "\n\n") * 3)))
    assert len(cs) >= 3 and all(len(c.user_text) + len(c.assistant_text) <= CHUNK_CHARS for c in cs)
    assert [c.part for c in cs] == list(range(len(cs)))
    assert all(c.lead == ("q " * 200)[:LEAD_CHARS] for c in cs if c.assistant_text)
    assert "".join(c.assistant_text for c in cs).replace("\n", "").replace(" ", "") == (("para " * 300) * 3).replace(" ", "")


def test_empty_exchange_yields_nothing():
    assert chunks_of(_s(Exchange("u1", "t", "", ""))) == []


def test_chunk_keys_are_stable_across_calls():
    s = _s(Exchange("u1", "t", "a", "b"), Exchange("u2", "t", "c", "d"))
    assert [c.chunk_key for c in chunks_of(s)] == [c.chunk_key for c in chunks_of(s)] == ["code:s1#u1#0", "code:s1#u2#0"]


def test_words_and_digest():
    assert words("Zoë's  NEW-car") == ["zoë", "s", "new", "car"]
    assert digest("salt", ["a", "b"]) == digest("salt", ["a", "b"]) != digest("salt2", ["a", "b"])


def test_score_matches_class():
    docs = ["red guitar amp", "blue amp", "guitar guitar strings and picks"]
    bm = BM25(docs); q = "guitar"
    df = sum(1 for t in bm.toks if "guitar" in t)
    assert [round(score(bm.tf[i]["guitar"], df, bm.n, len(bm.toks[i]), bm.avgdl), 9) if "guitar" in bm.tf[i] else 0.0
            for i in range(3)] == [round(x, 9) for x in bm.scores(q)]


def test_bench_import_still_works():
    from um.bench.public.bm25 import BM25 as B2, tokenize as t2
    assert B2 is BM25 and t2 is tokenize


def test_index_text_and_session_key():
    s = _s(Exchange("u1", "t", "hello", "world"))
    assert s.session_key == "code:s1"
    [c] = chunks_of(s)
    assert index_text(c, "T") == "T\n\nhello\nworld"


def test_long_user_text_splits_with_hard_cut_and_no_lead():
    cs = chunks_of(_s(Exchange("u1", "t", "x" * 4500, "")), chunk_chars=2000)
    assert [len(c.user_text) for c in cs] == [2000, 2000, 500]
    assert all(c.lead == "" and c.assistant_text == "" for c in cs)
