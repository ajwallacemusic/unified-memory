"""Incremental catch-up and export import (Plan 5 Task 5). Synthetic fixtures only."""
import json
import os

import pytest

from um.search.index import Index
from um.search.ingest import IDLE_S, MIN_INTERVAL_S, catch_up, import_export

T0 = 1_800_000_000.0      # a fixed "now" for the tests; file mtimes are set relative to it


def user(uuid, text, ts, sid="sess-1", entrypoint="cli"):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": entrypoint, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


def assistant(text, ts, sid="sess-1"):
    return {"type": "assistant", "uuid": f"a-{ts}", "timestamp": ts, "sessionId": sid, "cwd": "/work/proj",
            "entrypoint": "cli", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def turn(n, word, sid="sess-1", entrypoint="cli"):
    ts = f"2026-01-01T00:{n:02d}:00Z"
    return [user(f"{sid}-u{n}", f"question about {word}", ts, sid, entrypoint),
            assistant(f"answer about {word}", f"2026-01-01T00:{n:02d}:30Z", sid)]


def write(path, records, mtime=T0 - 1000, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode) as f:
        f.write("".join(json.dumps(r) + "\n" for r in records))
    os.utime(path, (mtime, mtime))
    return path


def proj(tmp_path):
    return tmp_path / "projects"


def tpath(tmp_path, sid="sess-1"):
    return proj(tmp_path) / "-work-proj" / f"{sid}.jsonl"


def idx(tmp_path, name="i.sqlite"):
    return Index(tmp_path / "idx" / name)


def cu(index, tmp_path, now, **kw):
    return catch_up(index, projects=proj(tmp_path), desktop=None, now=now, force=True, **kw)


def chunk_keys(index):
    return sorted(k for k, _ in index.iter_chunks())


def hits(index, q):
    return [h.chunk_key for h in index.search(q, limit=10, per_session=None)]


# --- catch_up ------------------------------------------------------------------------------------------------------

def test_catch_up_indexes_new_closed_turns_only(tmp_path):
    write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"), mtime=T0 - 10)   # not idle
    i = idx(tmp_path)
    r = cu(i, tmp_path, T0)
    assert r["skipped"] is False and r["files_read"] == 1 and r["chunks_written"] == 1
    assert chunk_keys(i) == ["code:sess-1#sess-1-u1#0"]
    assert hits(i, "bananas") == []
    assert r["as_of"] and i.get_meta("code_as_of") == r["as_of"]


def test_second_catch_up_reads_nothing_when_unchanged(tmp_path):
    write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"))   # idle: both turns close
    i = idx(tmp_path)
    assert cu(i, tmp_path, T0)["chunks_written"] == 2
    r = cu(i, tmp_path, T0 + 60)
    assert r["files_read"] == 0 and r["chunks_written"] == 0


def test_appended_turn_is_added_without_duplicates(tmp_path):
    p = write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"), mtime=T0 - 10)
    i = idx(tmp_path)
    cu(i, tmp_path, T0)
    write(p, turn(3, "cherries"), mtime=T0 + 5, mode="a")
    r = cu(i, tmp_path, T0 + 20)
    assert r["files_read"] == 1 and r["chunks_written"] == 1
    assert chunk_keys(i) == ["code:sess-1#sess-1-u1#0", "code:sess-1#sess-1-u2#0"]
    assert i.session_meta("code:sess-1")["n_turns"] == 2


def test_incremental_read_keeps_started_at(tmp_path):
    p = write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"), mtime=T0 - 10)
    i = idx(tmp_path)
    cu(i, tmp_path, T0)
    write(p, turn(3, "cherries"), mtime=T0 + 5, mode="a")
    cu(i, tmp_path, T0 + 20)
    [row] = i.recent(n=5)
    assert row.started_at == "2026-01-01T00:01:00Z"


def test_last_exchange_enters_once_file_is_idle(tmp_path):
    write(tpath(tmp_path), turn(1, "apples") + turn(2, "bananas"), mtime=T0 - 10)
    i = idx(tmp_path)
    cu(i, tmp_path, T0)
    assert hits(i, "bananas") == []
    r = cu(i, tmp_path, T0 - 10 + IDLE_S + 1)
    assert r["files_read"] == 1 and r["chunks_written"] == 1
    assert hits(i, "bananas") == ["code:sess-1#sess-1-u2#0"]
    r = cu(i, tmp_path, T0 + 2 * IDLE_S)            # closed now: not opened again
    assert r["files_read"] == 0


def test_shrunk_file_is_reread(tmp_path):
    p = tpath(tmp_path)
    write(p, turn(1, "apples") + turn(2, "bananas") + turn(3, "cherries"))
    i = idx(tmp_path)
    cu(i, tmp_path, T0)
    assert len(chunk_keys(i)) == 3
    short = turn(1, "apples") + [user("sess-1-u9", "question about damsons", "2026-01-01T00:09:00Z"),
                                 assistant("answer about damsons", "2026-01-01T00:09:30Z")]
    p.unlink()
    write(p, short, mtime=T0)
    assert p.stat().st_size < i.cursor(str(p)).size
    cu(i, tmp_path, T0 + IDLE_S + 1)
    fresh = idx(tmp_path, "fresh.sqlite")
    cu(fresh, tmp_path, T0 + IDLE_S + 1)
    assert chunk_keys(i) == chunk_keys(fresh) == ["code:sess-1#sess-1-u1#0", "code:sess-1#sess-1-u9#0"]
    assert dict(i.iter_chunks()) == dict(fresh.iter_chunks())
    assert hits(i, "cherries") == []


def test_deleted_transcript_keeps_chunks_and_sets_gone(tmp_path):
    p = write(tpath(tmp_path), turn(1, "apples"))
    i = idx(tmp_path)
    cu(i, tmp_path, T0)
    p.unlink()
    cu(i, tmp_path, T0 + 60)
    assert i.stats()["source_gone"] == 1
    assert hits(i, "apples") == ["code:sess-1#sess-1-u1#0"]


def test_sdk_session_gets_a_cursor_and_no_chunks(tmp_path):
    p = write(tpath(tmp_path, "sdk-1"), turn(1, "apples", "sdk-1", "sdk-cli"))
    i = idx(tmp_path)
    r = cu(i, tmp_path, T0)
    assert r["chunks_written"] == 0 and chunk_keys(i) == []
    c = i.cursor(str(p))
    assert c is not None and c.offset == c.size == p.stat().st_size
    assert cu(i, tmp_path, T0 + 60)["files_read"] == 0
    write(p, turn(2, "bananas", "sdk-1", "sdk-cli"), mtime=T0 + 70, mode="a")   # grows: still no chunks
    cu(i, tmp_path, T0 + 70 + IDLE_S + 1)
    assert chunk_keys(i) == []
    assert i.cursor(str(p)).offset == p.stat().st_size
    r = cu(i, tmp_path, T0 + 70 + IDLE_S + 2, include_sdk=True)   # opting in reads it whole
    assert len(chunk_keys(i)) == 2


def test_min_interval_skips(tmp_path):
    write(tpath(tmp_path), turn(1, "apples"))
    i = idx(tmp_path)
    first = catch_up(i, projects=proj(tmp_path), desktop=None, now=T0)
    assert first["skipped"] is False and first["chunks_written"] == 1
    write(tpath(tmp_path, "sess-2"), turn(1, "bananas", "sess-2"))
    r = catch_up(i, projects=proj(tmp_path), desktop=None, now=T0 + MIN_INTERVAL_S - 1)
    assert r["skipped"] is True and r["files_read"] == 0 and hits(i, "bananas") == []
    r = catch_up(i, projects=proj(tmp_path), desktop=None, now=T0 + MIN_INTERVAL_S - 1, force=True)
    assert r["skipped"] is False and hits(i, "bananas")
    r = catch_up(i, projects=proj(tmp_path), desktop=None, now=T0 + 2 * MIN_INTERVAL_S + 1)
    assert r["skipped"] is False


def test_desktop_sessions_are_surface_desktop(tmp_path):
    root = tmp_path / "las"
    meta = root / "acct" / "org" / "local_abc.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"sessionId": "local_abc", "cliSessionId": "cli-1", "title": "Desk chat",
                                "createdAt": 1767225600000, "lastActivityAt": 1767225660000,
                                "cwd": "/work/desk"}))
    write(root / "acct" / "org" / "local_abc" / ".claude" / "projects" / "-work-desk" / "cli-1.jsonl",
          turn(1, "apples", "cli-1"))
    i = idx(tmp_path)
    r = catch_up(i, projects=None, desktop=root, now=T0, force=True)
    assert r["files_read"] == 1
    [h] = i.search("apples")
    assert (h.surface, h.native_id, h.title) == ("desktop", "local_abc", "Desk chat")
    assert i.stats()["sessions"] == {"desktop": 1}


# --- import_export -------------------------------------------------------------------------------------------------

ROOT = "00000000-0000-4000-8000-000000000000"


def conv(uuid, word, updated="2026-01-01T11:00:00Z", extra=()):
    msgs = [{"uuid": f"{uuid}-h1", "sender": "human", "parent_message_uuid": ROOT,
             "created_at": "2026-01-01T10:00:00Z", "content": [{"type": "text", "text": f"tell me about {word}"}]},
            {"uuid": f"{uuid}-a1", "sender": "assistant", "parent_message_uuid": f"{uuid}-h1",
             "created_at": "2026-01-01T10:00:05Z", "content": [{"type": "text", "text": f"{word} facts"}]}]
    for n, w in enumerate(extra, 2):
        msgs += [{"uuid": f"{uuid}-h{n}", "sender": "human", "parent_message_uuid": f"{uuid}-a{n - 1}",
                  "created_at": f"2026-01-01T10:0{n}:00Z", "content": [{"type": "text", "text": f"and {w}"}]},
                 {"uuid": f"{uuid}-a{n}", "sender": "assistant", "parent_message_uuid": f"{uuid}-h{n}",
                  "created_at": f"2026-01-01T10:0{n}:05Z", "content": [{"type": "text", "text": f"{w} facts"}]}]
    return {"uuid": uuid, "name": f"Chat {uuid}", "created_at": "2026-01-01T10:00:00Z", "updated_at": updated,
            "chat_messages": msgs}


def export(tmp_path, name, convs):
    p = tmp_path / "exports" / name / "conversations.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(convs))
    return p


def partial_export(tmp_path, name, convs):
    """An export folder whose manifest lists a conversations part that is not there: incomplete."""
    d = tmp_path / "exports" / name
    (d / "conversations-000").mkdir(parents=True)
    (d / "conversations-000" / "conversations.json").write_text(json.dumps(convs))
    (d / "manifest-x.json").write_text(json.dumps({"data_files": [
        {"category": "conversations", "filename": "conversations-000.zip"},
        {"category": "conversations", "filename": "conversations-001.zip"}]}))
    return d


def test_import_twice_is_idempotent(tmp_path):
    p = export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas", extra=["cherries"])])
    i = idx(tmp_path)
    r1 = import_export(i, p)
    assert (r1["added"], r1["replaced"], r1["unchanged"], r1["removed"]) == (2, 0, 0, 0)
    assert r1["complete"] is True and r1["export_date"] == "2026-01-01T11:00:00Z"
    keys = chunk_keys(i)
    r2 = import_export(i, p)
    assert r2["added"] == r2["replaced"] == 0 and r2["unchanged"] == 2
    assert chunk_keys(i) == keys and len(keys) == 3
    assert i.get_meta("web_export_date") == "2026-01-01T11:00:00Z" and i.get_meta("web_export_id")


def test_updated_conversation_is_replaced(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples", extra=["cherries"]), conv("c2", "bananas")]))
    newer = [conv("c1", "apples", updated="2026-01-02T11:00:00Z", extra=["damsons"]), conv("c2", "bananas")]
    r = import_export(i, export(tmp_path, "e2", newer))
    assert (r["added"], r["replaced"], r["unchanged"]) == (0, 1, 1)
    assert hits(i, "damsons") == ["web:c1#c1-h2#0"] and hits(i, "cherries") == []
    assert i.session_meta("web:c1")["updated_at"] == "2026-01-02T11:00:00Z"


def test_deleted_conversation_is_removed_on_complete_export(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas")]))
    r = import_export(i, export(tmp_path, "e2", [conv("c1", "apples")]))
    assert r["removed"] == 1 and r["complete"] is True
    assert i.session_keys("web") == {"web:c1"} and hits(i, "bananas") == []
    import_export(i, export(tmp_path, "e3", [conv("c1", "apples"), conv("c2", "bananas")]))
    assert hits(i, "bananas") == ["web:c2#c2-h1#0"]       # no tombstone: it can come back


def test_partial_export_removes_nothing(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas")]))
    r = import_export(i, partial_export(tmp_path, "e2", [conv("c1", "apples")]))
    assert r["complete"] is False and r["removed"] == 0
    assert i.session_keys("web") == {"web:c1", "web:c2"}


def test_keep_deleted(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas")]))
    r = import_export(i, export(tmp_path, "e2", [conv("c1", "apples")]), keep_deleted=True)
    assert r["removed"] == 0 and i.session_keys("web") == {"web:c1", "web:c2"}


def test_older_export_refused(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "new", [conv("c1", "apples", updated="2026-02-01T00:00:00Z")]))
    old = export(tmp_path, "old", [conv("c2", "bananas", updated="2026-01-01T00:00:00Z")])
    with pytest.raises(ValueError, match="older"):
        import_export(i, old)
    assert i.session_keys("web") == {"web:c1"}
    r = import_export(i, old, force=True, keep_deleted=True)
    assert r["added"] == 1
    assert i.get_meta("web_export_date") == "2026-02-01T00:00:00Z"   # the high-water mark does not move back


def test_overlapping_exports_share_no_duplicate_chunks(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas")]),
                  keep_deleted=True)
    import_export(i, export(tmp_path, "e2", [conv("c2", "bananas"), conv("c3", "cherries")]), keep_deleted=True)
    keys = chunk_keys(i)
    assert keys == ["web:c1#c1-h1#0", "web:c2#c2-h1#0", "web:c3#c3-h1#0"]
    assert len(hits(i, "bananas")) == 1


def part_zip(tmp_path, name, part, convs):
    import zipfile
    d = tmp_path / "exports" / name
    d.mkdir(parents=True, exist_ok=True)
    z = d / f"conversations-{part}.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr(f"conversations-{part}/conversations.json", json.dumps(convs))
    return z


def test_importing_parts_one_at_a_time_keeps_both(tmp_path):
    i = idx(tmp_path)
    import_export(i, part_zip(tmp_path, "e", "000", [conv("c1", "apples")]))
    r = import_export(i, part_zip(tmp_path, "e", "001", [conv("c2", "bananas")]))
    assert r["removed"] == 0 and r["complete"] is False
    assert i.session_keys("web") == {"web:c1", "web:c2"}


def test_folder_without_manifest_removes_nothing(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "e1", [conv("c1", "apples"), conv("c2", "bananas")]))
    z = part_zip(tmp_path, "e2", "000", [conv("c1", "apples")])
    r = import_export(i, z.parent)
    assert r["removed"] == 0 and i.session_keys("web") == {"web:c1", "web:c2"}


def test_force_on_older_complete_export_deletes_nothing_newer(tmp_path):
    i = idx(tmp_path)
    import_export(i, export(tmp_path, "new", [conv("c1", "apples", updated="2026-02-01T00:00:00Z"),
                                              conv("c3", "cherries", updated="2026-02-01T00:00:00Z")]))
    old = export(tmp_path, "old", [conv("c2", "bananas", updated="2026-01-01T00:00:00Z")])
    r = import_export(i, old, force=True)
    assert r["added"] == 1 and r["removed"] == 0
    assert i.session_keys("web") == {"web:c1", "web:c2", "web:c3"}
