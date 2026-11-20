"""Claude Code and desktop readers (Plan 5 Task 3). Synthetic fixtures only."""
import builtins
import io
import json
from pathlib import Path

from um.search.sources import code, desktop


def user(uuid, text, ts, origin="human", entrypoint="cli", **kw):
    rec = {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": "sess-1", "cwd": "/work/proj",
           "entrypoint": entrypoint, "isSidechain": False, "message": {"role": "user", "content": text}}
    if origin is not None:
        rec["origin"] = {"kind": origin}
    rec.update(kw)
    return rec


def assistant(ts, *blocks, **kw):
    content = [{"type": "text", "text": b} if isinstance(b, str) else b for b in blocks]
    rec = {"type": "assistant", "uuid": f"a-{ts}", "timestamp": ts, "sessionId": "sess-1", "cwd": "/work/proj",
           "entrypoint": "cli", "isSidechain": False, "message": {"role": "assistant", "content": content}}
    rec.update(kw)
    return rec


def tool_result(ts, text="TOOLOUTPUT"):
    return {"type": "user", "uuid": f"r-{ts}", "timestamp": ts, "sessionId": "sess-1", "cwd": "/work/proj",
            "entrypoint": "cli", "toolUseResult": {"stdout": text},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": text}]}}


def thinking(text): return {"type": "thinking", "thinking": text}
def tool_use(name): return {"type": "tool_use", "id": "x", "name": name, "input": {}}
def title(t): return {"type": "ai-title", "aiTitle": t, "sessionId": "sess-1"}


def jl(tmp_path, records, name="sess-1.jsonl", tail=""):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in records) + tail)
    return p


def start_of(path, uuid):
    return path.read_bytes().index(f'{{"type": "user", "uuid": "{uuid}"'.encode())


BASIC = [
    user("u1", "first question", "2026-01-01T00:00:00Z"),
    assistant("2026-01-01T00:00:01Z", thinking("SECRETTHOUGHT"), "A1", tool_use("Bash")),
    tool_result("2026-01-01T00:00:02Z"),
    assistant("2026-01-01T00:00:03Z", "A2"),
    user("u2", "second question", "2026-01-01T00:01:00Z"),
    assistant("2026-01-01T00:01:01Z", "B"),
]


def test_exchange_pairs_typed_turn_with_following_text(tmp_path):
    p = jl(tmp_path, BASIC)
    s, off = code.read_transcript(p)
    assert len(s.exchanges) == 1
    ex = s.exchanges[0]
    assert (ex.turn_id, ex.at, ex.user_text, ex.assistant_text, ex.tools) == (
        "u1", "2026-01-01T00:00:00Z", "first question", "A1\n\nA2", ("Bash",))
    assert off == start_of(p, "u2")
    assert (s.surface, s.native_id, s.url, s.source_path) == ("code", "sess-1", None, str(p))


def test_open_exchange_is_not_returned(tmp_path):
    p = jl(tmp_path, BASIC[:2])
    s, off = code.read_transcript(p)
    assert s is not None and s.exchanges == () and off == 0


def test_idle_closes_the_last_exchange(tmp_path):
    p = jl(tmp_path, BASIC)
    s, off = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1", "u2"] and s.exchanges[1].assistant_text == "B"
    assert off == start_of(p, "u2")      # kept at the idle-closed exchange: later text must still join it


def test_resume_from_offset_reads_only_new(tmp_path):
    p = jl(tmp_path, BASIC)
    _, off = code.read_transcript(p)
    s, off2 = code.read_transcript(p, offset=off, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u2"] and off2 == off


def test_tool_results_thinking_meta_sidechain_compact_are_dropped(tmp_path):
    p = jl(tmp_path, [
        user("u1", "hello", "2026-01-01T00:00:00Z"),
        assistant("2026-01-01T00:00:01Z", thinking("SECRETTHOUGHT"), "ok"),
        tool_result("2026-01-01T00:00:02Z", "TOOLOUTPUT"),
        user("m1", "METATEXT", "2026-01-01T00:00:03Z", isMeta=True),
        user("s1", "SIDETEXT", "2026-01-01T00:00:04Z", isSidechain=True),
        assistant("2026-01-01T00:00:05Z", "SIDEREPLY", isSidechain=True),
        user("c1", "COMPACTTEXT", "2026-01-01T00:00:06Z", isCompactSummary=True),
        {"type": "attachment", "timestamp": "2026-01-01T00:00:07Z", "content": "ATTACHTEXT"},
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-01-01T00:00:08Z",
         "content": "SYSTEXT"},
        user("u2", "bye", "2026-01-01T00:01:00Z"),
    ])
    s, _ = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1", "u2"]
    blob = " ".join(e.user_text + " " + e.assistant_text for e in s.exchanges)
    for bad in ("SECRETTHOUGHT", "TOOLOUTPUT", "METATEXT", "SIDETEXT", "SIDEREPLY", "COMPACTTEXT", "ATTACHTEXT",
                "SYSTEXT"):
        assert bad not in blob
    assert s.exchanges[0].assistant_text == "ok"


def test_sdk_session_is_skipped_unless_included(tmp_path):
    recs = [user("u1", "bench prompt", "2026-01-01T00:00:00Z", origin=None, entrypoint="sdk-cli"),
            assistant("2026-01-01T00:00:01Z", "answer", entrypoint="sdk-cli")]
    p = jl(tmp_path, recs)
    assert code.read_transcript(p, idle=True) == (None, 0)
    s, _ = code.read_transcript(p, idle=True, include_sdk=True)
    assert [e.user_text for e in s.exchanges] == ["bench prompt"]


def test_sdk_check_applies_when_resuming(tmp_path):
    recs = [user("u1", "bench prompt", "2026-01-01T00:00:00Z", origin=None, entrypoint="sdk-cli"),
            assistant("2026-01-01T00:00:01Z", "answer", entrypoint="sdk-cli"),
            user("u2", "next", "2026-01-01T00:00:02Z", origin=None, entrypoint="sdk-cli")]
    p = jl(tmp_path, recs)
    off = start_of(p, "u2")
    assert code.read_transcript(p, offset=off, idle=True) == (None, off)
    s, _ = code.read_transcript(p, offset=off, idle=True, include_sdk=True)
    assert s is not None and [e.turn_id for e in s.exchanges] == ["u2"]


def test_sdk_record_later_in_the_file_is_caught(tmp_path):
    recs = [title("Bench"), user("u1", "bench prompt", "2026-01-01T00:00:00Z", origin=None, entrypoint="sdk-cli"),
            assistant("2026-01-01T00:00:01Z", "answer", entrypoint="sdk-cli")]
    p = jl(tmp_path, recs)
    off = len(json.dumps(recs[0]) + "\n")
    assert code.read_transcript(p, offset=off, idle=True) == (None, off)


def test_legacy_record_without_origin_counts_when_plain(tmp_path):
    p = jl(tmp_path, [
        user("u1", "plain legacy", "2026-01-01T00:00:00Z", origin=None, entrypoint="local-agent"),
        assistant("2026-01-01T00:00:01Z", "r1"),
        user("x1", "<command-name>/clear</command-name>", "2026-01-01T00:00:02Z", origin=None),
        assistant("2026-01-01T00:00:03Z", "r2"),
    ])
    s, _ = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1"]
    assert s.exchanges[0].assistant_text == "r1\n\nr2"


def test_task_notification_and_peer_origins_are_not_typed(tmp_path):
    p = jl(tmp_path, [
        user("u1", "hello", "2026-01-01T00:00:00Z"),
        assistant("2026-01-01T00:00:01Z", "r1"),
        user("n1", "NOTIFY", "2026-01-01T00:00:02Z", origin="task-notification"),
        user("p1", "PEER", "2026-01-01T00:00:03Z", origin="peer"),
        user("c1", "COORD", "2026-01-01T00:00:04Z", origin="coordinator"),
        assistant("2026-01-01T00:00:05Z", "r2"),
    ])
    s, _ = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1"]
    assert "NOTIFY" not in s.exchanges[0].user_text + s.exchanges[0].assistant_text


def test_half_written_last_line_stops_cleanly(tmp_path):
    p = jl(tmp_path, BASIC[:4], tail='{"type": "user", "uuid": "u2", "mess')
    s, off = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1"]
    assert off == start_of(p, "u1")      # the idle-closed exchange stays open to later text
    s, off = code.read_transcript(p)
    assert s.exchanges == () and p.read_bytes()[off:].startswith(b'{"type": "user", "uuid": "u1"')
    s, off = code.read_transcript(p, offset=len(b"".join(json.dumps(r).encode() + b"\n" for r in BASIC[:3])))
    assert p.read_bytes()[off:] == b'{"type": "user", "uuid": "u2", "mess'   # no exchange open: stops at the tail


def test_corrupt_line_mid_file_is_skipped(tmp_path):
    p = tmp_path / "sess-1.jsonl"
    lines = [json.dumps(r).encode() + b"\n" for r in BASIC]
    p.write_bytes(b"".join(lines[:2]) + b'{"broken": \n' + b"\xff\xfe not utf8\n" + b"".join(lines[2:]))
    s, off = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1", "u2"]
    assert s.exchanges[0].assistant_text == "A1\n\nA2"
    assert off == p.read_bytes().index(b'{"type": "user", "uuid": "u2"')


def test_complete_bad_last_line_is_skipped(tmp_path):
    p = jl(tmp_path, BASIC[:4], tail='{"broken\n')
    s, off = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1"]
    assert off == start_of(p, "u1")


def test_lone_surrogate_is_replaced(tmp_path):
    p = jl(tmp_path, [user("u1", "bad \ud800 text", "2026-01-01T00:00:00Z"),
                      assistant("2026-01-01T00:00:01Z", "reply \udfff here"), title("T \ud83d")])
    s, _ = code.read_transcript(p, idle=True)
    ex = s.exchanges[0]
    for t in (ex.user_text, ex.assistant_text, s.title):
        t.encode("utf-8")
    assert ex.user_text.startswith("bad ") and ex.user_text.endswith(" text")


def test_record_without_message_is_skipped(tmp_path):
    p = jl(tmp_path, [
        user("u1", "hello", "2026-01-01T00:00:00Z"),
        {"type": "user", "uuid": "bad", "timestamp": "2026-01-01T00:00:01Z", "origin": {"kind": "human"}},
        {"type": "assistant", "uuid": "bad2", "timestamp": "2026-01-01T00:00:02Z"},
        assistant("2026-01-01T00:00:03Z", "r1"),
        user("u2", None, "2026-01-01T00:00:04Z", origin=None),
    ])
    s, _ = code.read_transcript(p, idle=True)
    assert [e.turn_id for e in s.exchanges] == ["u1"] and s.exchanges[0].assistant_text == "r1"


def test_title_is_last_ai_title_and_project_is_cwd(tmp_path):
    p = jl(tmp_path, [title("Old"), *BASIC[:2], title("New"),
                      user("u2", "q", "2026-01-01T00:05:00Z", cwd="/elsewhere")])
    s, _ = code.read_transcript(p, idle=True)
    assert (s.title, s.project) == ("New", "/work/proj")
    assert (s.started_at, s.updated_at) == ("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")


def test_long_typed_turn_is_cut(tmp_path):
    p = jl(tmp_path, [user("u1", "x" * 10_000, "2026-01-01T00:00:00Z"), assistant("2026-01-01T00:00:01Z", "r")])
    s, _ = code.read_transcript(p, idle=True)
    assert len(s.exchanges[0].user_text) == 4000


def test_discover_ignores_subagent_files(tmp_path):
    projects = tmp_path / "projects"
    jl(projects / "p", BASIC, name="s1.jsonl")
    jl(projects / "p" / "s1" / "subagents", BASIC, name="agent-x.jsonl")
    jl(projects / "a", BASIC, name="s0.jsonl")
    assert code.discover(projects) == [projects / "a" / "s0.jsonl", projects / "p" / "s1.jsonl"]


def _desktop_tree(tmp_path):
    root = tmp_path / "local-agent-mode-sessions"
    org = root / "acct" / "org"
    org.mkdir(parents=True)
    (org / "local_X.json").write_text(json.dumps({
        "sessionId": "local_X", "cliSessionId": "cli-1", "title": "Desktop title",
        "createdAt": 1767225600000, "lastActivityAt": 1767229200500, "cwd": "/sessions/x",
        "userSelectedFolders": ["/Users/someone/folder"], "systemPrompt": "DONOTREAD",
        "emailAddress": "nobody@example.com", "initialMessage": "DONOTREAD"}))
    tr = jl(org / "local_X" / ".claude" / "projects" / "p",
            [user("u1", "hi", "2026-01-01T00:00:00Z", origin=None, entrypoint="local-agent"),
             assistant("2026-01-01T00:00:01Z", "yo")], name="cli-1.jsonl")
    (org / "local_X" / ".claude" / ".credentials.json").write_text("{}")
    (org / "local_X" / "audit.jsonl").write_text("{}\n")
    (org / "local_Y.json").write_text(json.dumps({"sessionId": "local_Y", "cliSessionId": "missing",
                                                  "createdAt": 0, "lastActivityAt": 0}))
    return root, org, tr


def test_desktop_discover_reads_only_allowed_files(tmp_path, monkeypatch):
    root, org, tr = _desktop_tree(tmp_path)
    opened: list[str] = []
    real_open, real_read_text, real_read_bytes = builtins.open, Path.read_text, Path.read_bytes
    real_io_open = io.open

    def rec_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    def rec_read_text(self, *a, **k):
        opened.append(str(self))
        return real_read_text(self, *a, **k)

    def rec_read_bytes(self, *a, **k):
        opened.append(str(self))
        return real_read_bytes(self, *a, **k)

    def rec_path_open(self, *a, **k):
        opened.append(str(self))
        return real_io_open(self, *a, **k)

    monkeypatch.setattr(builtins, "open", rec_open)
    monkeypatch.setattr(io, "open", rec_open)
    monkeypatch.setattr(Path, "read_text", rec_read_text)
    monkeypatch.setattr(Path, "read_bytes", rec_read_bytes)
    monkeypatch.setattr(Path, "open", rec_path_open)
    found = desktop.discover(root)
    for path, meta in found:
        code.read_transcript(path, surface="desktop", meta=meta, idle=True)
    allowed = {str(org / "local_X.json"), str(org / "local_Y.json"), str(tr)}
    assert opened and set(opened) <= allowed
    assert [p for p, _ in found] == [tr]


def test_desktop_meta_overrides(tmp_path):
    root, org, tr = _desktop_tree(tmp_path)
    [(path, meta)] = desktop.discover(root)
    assert meta == {"native_id": "local_X", "title": "Desktop title", "project": "/Users/someone/folder",
                    "started_at": "2026-01-01T00:00:00.000Z", "updated_at": "2026-01-01T01:00:00.500Z"}
    s, _ = code.read_transcript(path, surface="desktop", meta=meta, idle=True)
    assert (s.surface, s.native_id, s.title, s.project, s.session_key) == (
        "desktop", "local_X", "Desktop title", "/Users/someone/folder", "desktop:local_X")
    assert (s.started_at, s.updated_at) == ("2026-01-01T00:00:00.000Z", "2026-01-01T01:00:00.500Z")
    assert [e.user_text for e in s.exchanges] == ["hi"]


def test_desktop_project_falls_back_to_cwd(tmp_path):
    root, org, _ = _desktop_tree(tmp_path)
    d = json.loads((org / "local_X.json").read_text())
    d["userSelectedFolders"] = []
    (org / "local_X.json").write_text(json.dumps(d))
    [(_, meta)] = desktop.discover(root)
    assert meta["project"] == "/sessions/x"
