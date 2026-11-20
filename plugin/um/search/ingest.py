"""Keeping the index fresh (spec, "Freshness").

`catch_up` reads Claude Code and desktop transcripts incrementally from a stored byte offset; only closed
exchanges enter the index. `import_export` brings in a claude.ai export: unchanged conversations are skipped,
changed ones replaced, and (on a complete export) conversations deleted on claude.ai are removed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from um.search.index import Cursor, Index
from um.search.model import SessionDoc, chunks_of
from um.search.sources import code, desktop as desktop_src
from um.search.sources import web

IDLE_S, MIN_INTERVAL_S = 300, 10

# Cursor session_key for an `sdk-cli` transcript that was skipped: it stays skipped as it grows, and is read
# whole once `include_sdk` is turned on.
SDK_SKIPPED = "sdk-cli:skipped"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _started_at(index: Index, session_key: str) -> str | None:
    r = index._db.execute("SELECT started_at FROM sessions WHERE session_key = ?", (session_key,)).fetchone()
    return r[0] if r and r[0] else None


HEAD_BYTES = 4096   # a transcript whose first bytes change was replaced, not appended to: it is read whole

# Per-file state beside the index's cursors, owned by catch-up: the digest of the file's first bytes (to tell a
# replaced file from a grown one) and the (size, mtime) at which the last exchange was closed by the idle rule
# (so an idle file is not read again until it changes, while the cursor stays at that exchange's start).
_STATE = ("CREATE TABLE IF NOT EXISTS cursor_state(source_path TEXT PRIMARY KEY, head_len INTEGER, head_sha TEXT,"
          " closed_size INTEGER, closed_mtime REAL)")


def _head(path: Path, n: int) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read(n)).hexdigest()


def _state(index: Index, path: str) -> tuple:
    r = index._db.execute("SELECT head_len, head_sha, closed_size, closed_mtime FROM cursor_state"
                          " WHERE source_path = ?", (path,)).fetchone()
    return r or (None, None, None, None)


def _set_state(index: Index, path: Path, size: int, closed: tuple | None) -> None:
    n = min(size, HEAD_BYTES)
    index._db.execute("INSERT OR REPLACE INTO cursor_state(source_path, head_len, head_sha, closed_size, closed_mtime)"
                      " VALUES (?,?,?,?,?)", (str(path), n, _head(path, n), *(closed or (None, None))))
    index._db.commit()


def _catch_up_file(index: Index, path: Path, surface: str, meta: dict | None, now: float,
                   include_sdk: bool) -> tuple[bool, int]:
    """Bring one transcript up to date. Returns (opened, chunks_written)."""
    try:
        st = path.stat()
    except OSError:
        return False, 0
    size, mtime = st.st_size, st.st_mtime
    idle = now - mtime > IDLE_S
    cur = index.cursor(str(path))
    head_len, head_sha, closed_size, closed_mtime = _state(index, str(path))
    replace = False
    if cur is None:
        offset = 0
    elif cur.session_key == SDK_SKIPPED:
        if include_sdk:
            offset, replace = 0, True
        else:
            if (cur.size, cur.mtime) != (size, mtime):
                index.set_cursor(Cursor(str(path), surface, SDK_SKIPPED, size, mtime, size))
            return False, 0
    elif size < cur.size:
        offset, replace = 0, True
    elif (cur.size, cur.mtime) == (size, mtime):
        if not (cur.offset < size and idle) or (closed_size, closed_mtime) == (size, mtime):
            return False, 0
        offset = cur.offset
    elif head_len and head_len <= size and _head(path, head_len) != head_sha:
        offset, replace = 0, True       # replaced by a different (longer) file
    else:
        offset = cur.offset

    read_meta = dict(meta or {})
    if offset > 0 and cur is not None and read_meta.get("started_at") is None:
        old = _started_at(index, cur.session_key)
        if old:
            read_meta["started_at"] = old
    doc, end = code.read_transcript(path, surface=surface, offset=offset, idle=idle, include_sdk=include_sdk,
                                    meta=read_meta or None)
    if doc is None:
        if cur is not None and cur.session_key != SDK_SKIPPED:
            index.delete_session(cur.session_key)    # an sdk-cli session found late: it never belonged here
        index.set_cursor(Cursor(str(path), surface, SDK_SKIPPED, size, mtime, size))
        _set_state(index, path, size, None)
        return True, 0
    written = 0
    if doc.exchanges or replace:
        written, _ = index.upsert_session(doc, chunks_of(doc), replace=replace)
    key = doc.session_key if (doc.exchanges or cur is None) else cur.session_key
    index.set_cursor(Cursor(str(path), surface, key, size, mtime, end))
    _set_state(index, path, size, (size, mtime) if idle else None)
    return True, written


def catch_up(index: Index, *, projects: Path | None, desktop: Path | None, now: float,
             include_sdk: bool = False, force: bool = False) -> dict:
    """Read what changed in every Claude Code and desktop transcript since the last catch-up.
    Returns {"skipped", "files_read", "chunks_written", "files_failed", "as_of"}. A file that raises is rolled
    back, counted in `files_failed` (also kept as meta `catch_up_files_failed`) and retried next time."""
    as_of = _iso(now)
    last = index.get_meta("catch_up_at")
    if not force and last is not None:
        try:
            if 0 <= now - float(last) < MIN_INTERVAL_S:
                return {"skipped": True, "files_read": 0, "chunks_written": 0, "files_failed": 0,
                        "as_of": index.get_meta("code_as_of") or as_of}
        except ValueError:
            pass
    index._db.execute(_STATE)
    files_read = chunks_written = files_failed = 0
    sources: list[tuple[str, list[tuple[Path, dict | None]]]] = []
    if projects is not None:
        sources.append(("code", [(p, None) for p in code.discover(Path(projects).expanduser())]))
    if desktop is not None:
        sources.append(("desktop", desktop_src.discover(Path(desktop).expanduser())))
    for surface, files in sources:
        for path, meta in files:
            try:
                opened, n = _catch_up_file(index, path, surface, meta, now, include_sdk)
            except Exception:       # one bad file must not stop the rest; its cursor is unchanged, so it is retried
                index._db.rollback()
                files_failed += 1
                continue
            files_read += opened
            chunks_written += n
        index.mark_gone(surface, {str(p) for p, _ in files})
    index.set_meta("catch_up_at", repr(now))
    index.set_meta("code_as_of", as_of)
    index.set_meta("catch_up_files_failed", str(files_failed))
    return {"skipped": False, "files_read": files_read, "chunks_written": chunks_written,
            "files_failed": files_failed, "as_of": as_of}


def _n_text_turns(s: SessionDoc) -> int:
    return sum(1 for e in s.exchanges if e.user_text or e.assistant_text)


def import_export(index: Index, path: Path, *, keep_deleted: bool = False, force: bool = False) -> dict:
    """Import a claude.ai export. Returns {"added", "replaced", "unchanged", "removed", "export_date",
    "complete"}. Raises ValueError for an export older than the last one imported, unless `force`; even then an
    older export never deletes anything, since what it lacks may simply be newer than it."""
    export = web.load_export(Path(path).expanduser())
    last = index.get_meta("web_export_date")
    older = bool(last) and export.export_date < last
    if older and not force:
        raise ValueError(f"export dated {export.export_date or 'unknown'} is older than the last one imported "
                         f"({last}); pass force to import it anyway")
    added = replaced = unchanged = removed = 0
    seen = set()
    for s in export.sessions:
        seen.add(s.session_key)
        old = index.session_meta(s.session_key)
        n = _n_text_turns(s)
        if old is None and n == 0:
            unchanged += 1          # nothing indexable, nothing stored
            continue
        if old is not None and old["updated_at"] == s.updated_at and old["n_turns"] == n:
            unchanged += 1
            continue
        index.upsert_session(s, chunks_of(s), replace=True)
        if old is None:
            added += 1
        else:
            replaced += 1
    if export.complete and not keep_deleted and not older:
        for key in sorted(index.session_keys("web") - seen):
            index.delete_session(key, tombstone=False)
            removed += 1
    index.set_meta("web_export_date", max(last or "", export.export_date))
    index.set_meta("web_export_id", export.export_id)
    return {"added": added, "replaced": replaced, "unchanged": unchanged, "removed": removed,
            "export_date": export.export_date, "complete": export.complete}
