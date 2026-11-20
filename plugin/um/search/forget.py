"""Erase and forget on the conversation-search index (spec, "Privacy": "Erase reaches the index").

`erase_from_index` deletes, with tombstones, every chunk whose text (title, lead, user text, assistant text)
contains a value, using the matching of `um/erase.py` (see `erasematch.py`). Before the scan it records a keyed
hash of each value, so a later ingest drops any chunk containing it under the same matching, and it vacuums.
The value is never written to the index, a log or the return value. The caller runs the catch-up first.
"""
from __future__ import annotations

from um.erase import _check
from um.search.erasematch import matches, value_digest
from um.search.index import Index


def _session_of(chunk_key: str) -> str:
    return chunk_key.rsplit("#", 2)[0]


def erase_from_index(index: Index, values: list[str]) -> dict:
    low = _check(values)
    salt = index.get_meta("salt") or ""
    for v in low:                      # record the guard first, so an ingest racing the scan is dropped too
        index.add_erased(*value_digest(salt, v))
    doomed = [k for k, text in index.iter_chunks() if matches(text, low)]
    removed = index.delete_chunks(doomed, tombstone=True)
    index.vacuum()
    return {"chunks": removed, "sessions": len({_session_of(k) for k in doomed})}


def forget_session(index: Index, session: str) -> int:
    """Remove one session, given its native id or its session key, and tombstone its chunks."""
    keys = [k for (k,) in index._db.execute(
        "SELECT session_key FROM sessions WHERE session_key = ? OR native_id = ?", (session, session))]
    return sum(index.delete_session(k, tombstone=True) for k in keys)
