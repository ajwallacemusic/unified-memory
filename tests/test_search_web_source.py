"""claude.ai export reader (Plan 5, Task 4). Synthetic fixtures only."""
import io
import json
import zipfile

from um.search.model import MAX_USER_CHARS
from um.search.sources import web
from um.search.sources.web import load_export, session_of


def msg(uuid, sender, parent, blocks, created, text=None):
    m = {"uuid": uuid, "sender": sender, "parent_message_uuid": parent, "created_at": created,
         "updated_at": created, "content": blocks, "attachments": [], "files": []}
    if text is not None:
        m["text"] = text
    return m


def conv(uuid, name, msgs, created="2026-01-01T10:00:00Z", updated="2026-01-01T11:00:00Z"):
    return {"uuid": uuid, "name": name, "summary": "", "created_at": created, "updated_at": updated,
            "account": {"uuid": "acct"}, "chat_messages": msgs}


def t(text):
    return {"type": "text", "text": text}


def tool_use(name):
    return {"type": "tool_use", "name": name, "input": {}}


ROOT = "00000000-0000-4000-8000-000000000000"


def simple(uuid="c1", updated="2026-01-01T11:00:00Z"):
    return conv(uuid, f"Chat {uuid}", [
        msg(f"{uuid}-h1", "human", ROOT, [t("how do i bake sourdough")], "2026-01-01T10:00:00Z"),
        msg(f"{uuid}-a1", "assistant", f"{uuid}-h1", [t("feed the starter first")], "2026-01-01T10:00:05Z"),
    ], updated=updated)


def test_session_fields_and_url():
    s = session_of(simple())
    assert s.surface == "web"
    assert s.native_id == "c1"
    assert s.title == "Chat c1"
    assert s.project is None
    assert s.url == "https://claude.ai/chat/c1"
    assert s.started_at == "2026-01-01T10:00:00Z"
    assert s.updated_at == "2026-01-01T11:00:00Z"
    assert s.session_key == "web:c1"
    [ex] = s.exchanges
    assert ex.turn_id == "c1-h1"
    assert ex.at == "2026-01-01T10:00:00Z"
    assert ex.user_text == "how do i bake sourdough"
    assert ex.assistant_text == "feed the starter first"
    assert ex.tools == ()


def test_exchange_pairs_by_parent_and_indexes_every_branch():
    c = conv("c2", "Branchy", [
        msg("h1", "human", ROOT, [t("first question")], "2026-01-01T10:00:00Z"),
        msg("a1b", "assistant", "h1", [t("retry answer")], "2026-01-01T10:02:00Z"),
        msg("a1a", "assistant", "h1", [t("original answer")], "2026-01-01T10:01:00Z"),
        msg("h2", "human", "a1a", [t("follow up")], "2026-01-01T10:03:00Z"),
        msg("h2b", "human", "a1a", [t("edited follow up")], "2026-01-01T10:04:00Z"),
        msg("a2", "assistant", "h2b", [t("answer to edit")], "2026-01-01T10:05:00Z"),
        msg("orphan", "assistant", "nobody", [t("orphan text")], "2026-01-01T10:06:00Z"),
    ])
    s = session_of(c)
    assert [e.turn_id for e in s.exchanges] == ["h1", "h2", "h2b"]
    assert s.exchanges[0].assistant_text == "original answer\n\nretry answer"
    assert s.exchanges[1].assistant_text == ""
    assert s.exchanges[2].assistant_text == "answer to edit"
    assert all("orphan" not in e.assistant_text for e in s.exchanges)


def test_non_text_blocks_and_attachments_are_dropped():
    h = msg("h1", "human", ROOT, [
        t("visible question"),
        {"type": "injected_prompt_block", "text": "INJECTEDSECRET"},
        {"type": "document", "text": "DOCSECRET"},
        {"type": "image", "text": "IMGSECRET"},
        {"type": "flag", "text": "FLAGSECRET"},
    ], "2026-01-01T10:00:00Z")
    h["attachments"] = [{"file_name": "a.txt", "extracted_content": "ATTACHSECRET"}]
    a = msg("a1", "assistant", "h1", [
        {"type": "thinking", "thinking": "THINKSECRET", "text": "THINKSECRET"},
        tool_use("web_search"),
        {"type": "tool_result", "content": [t("TOOLRESULTSECRET")], "text": "TOOLRESULTSECRET"},
        {"type": "token_budget", "text": "BUDGETSECRET"},
        t("visible answer"),
    ], "2026-01-01T10:00:05Z")
    s = session_of(conv("c3", "n", [h, a]))
    [ex] = s.exchanges
    blob = ex.user_text + ex.assistant_text
    assert ex.user_text == "visible question"
    assert ex.assistant_text == "visible answer"
    for secret in ("INJECTED", "DOC", "IMG", "FLAG", "ATTACH", "THINK", "TOOLRESULT", "BUDGET"):
        assert secret + "SECRET" not in blob


def test_tool_names_are_kept():
    s = session_of(conv("c4", "n", [
        msg("h1", "human", ROOT, [t("q")], "2026-01-01T10:00:00Z"),
        msg("a1", "assistant", "h1", [tool_use("web_search"), t("x"), tool_use("web_fetch")],
            "2026-01-01T10:00:01Z"),
        msg("a2", "assistant", "h1", [tool_use("web_search"), tool_use("repl")], "2026-01-01T10:00:02Z"),
    ]))
    assert s.exchanges[0].tools == ("web_search", "web_fetch", "repl")


def test_null_content_falls_back_to_text():
    long = "y" * 10_000
    s = session_of(conv("c5", "n", [
        msg("h1", "human", ROOT, None, "2026-01-01T10:00:00Z", text="plain old text"),
        msg("a1", "assistant", "h1", None, "2026-01-01T10:00:01Z", text="assistant fallback"),
        msg("h2", "human", "a1", [t(long)], "2026-01-01T10:00:02Z"),
        msg("h3", "human", "a1", None, "2026-01-01T10:00:03Z"),
    ]))
    assert s.exchanges[0].user_text == "plain old text"
    assert s.exchanges[0].assistant_text == "assistant fallback"
    assert len(s.exchanges[1].user_text) == MAX_USER_CHARS
    assert s.exchanges[2].user_text == ""


def test_empty_conversation_has_no_exchanges():
    assert session_of(conv("c6", "", [])).exchanges == ()
    c = conv("c7", None, None)
    s = session_of(c)
    assert s.exchanges == () and s.title == ""


# ---- export forms -------------------------------------------------------------------------------------------

def _zip(path, members: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data if isinstance(data, str) else json.dumps(data))
    return path


def _manifest(parts, category="conversations"):
    return {"data_files": [{"category": category, "filename": p} for p in parts]}


def test_load_from_json_zip_folder(tmp_path):
    convs = [simple("c1"), simple("c2", updated="2026-02-01T00:00:00Z")]
    lone = tmp_path / "conversations.json"
    lone.write_text(json.dumps(convs))
    z = _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": convs})

    unpacked = tmp_path / "unpacked"
    (unpacked / "conversations-000").mkdir(parents=True)
    (unpacked / "conversations-000" / "conversations.json").write_text(json.dumps(convs))
    (unpacked / "manifest-20260201.json").write_text(json.dumps(_manifest(["conversations-000.zip"])))

    zips = tmp_path / "zips"
    zips.mkdir()
    _zip(zips / "conversations-000.zip", {"conversations-000/conversations.json": convs})
    (zips / "manifest-20260201.json").write_text(json.dumps(_manifest(["conversations-000.zip"])))

    results = [load_export(p) for p in (lone, z, unpacked, zips)]
    for r in results:
        assert sorted(s.native_id for s in r.sessions) == ["c1", "c2"]
        assert r.sessions == results[0].sessions
    assert [r.complete for r in results] == [True, False, True, True]   # a lone zip may be one part of many
    assert results[2].export_id == results[3].export_id == "manifest-20260201"
    assert results[0].export_id == results[1].export_id
    assert len(results[0].export_id) == 16 and int(results[0].export_id, 16) >= 0


def test_duplicate_conversation_across_parts_kept_once(tmp_path):
    _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": [simple("c1")]})
    _zip(tmp_path / "conversations-001.zip",
         {"conversations-001/conversations.json": [simple("c1", updated="2026-03-01T00:00:00Z")]})
    e = load_export(tmp_path)
    [s] = e.sessions
    assert s.updated_at == "2026-03-01T00:00:00Z"


def test_only_conversations_and_manifest_are_opened(tmp_path, monkeypatch):
    _zip(tmp_path / "conversations-000.zip", {
        "conversations-000/conversations.json": [simple()],
        "conversations-000/users.json": [{"email": "x"}],
    })
    _zip(tmp_path / "memories-000.zip", {"memories-000/memories.json": [{"m": 1}]})
    (tmp_path / "users.json").write_text("[]")
    (tmp_path / "manifest-1.json").write_text(json.dumps(_manifest(["conversations-000.zip"])))

    opened = []
    real_open = zipfile.ZipFile.open

    def spy_open(self, name, *a, **k):
        opened.append(name if isinstance(name, str) else name.filename)
        return real_open(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy_open)
    real_read_bytes, real_read_text = web.Path.read_bytes, web.Path.read_text

    def spy_rb(self):
        opened.append(str(self))
        return real_read_bytes(self)

    def spy_rt(self, *a, **k):
        opened.append(str(self))
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(web.Path, "read_bytes", spy_rb)
    monkeypatch.setattr(web.Path, "read_text", spy_rt)
    e = load_export(tmp_path)
    assert [s.native_id for s in e.sessions] == ["c1"]
    assert opened, "spy saw nothing"
    for name in opened:
        base = name.rsplit("/", 1)[-1]
        assert base == "conversations.json" or (base.startswith("manifest-") and base.endswith(".json")), name


def test_complete_false_when_manifest_lists_a_missing_part(tmp_path):
    _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": [simple("c1")]})
    (tmp_path / "manifest-1.json").write_text(json.dumps({"data_files": [
        {"category": "conversations", "filename": "conversations-000.zip"},
        {"category": "conversations", "filename": "conversations-001.zip"},
        {"category": "projects", "filename": "projects-000.zip"},
    ]}))
    e = load_export(tmp_path)
    assert not e.complete
    assert [s.native_id for s in e.sessions] == ["c1"]


def test_complete_uses_newest_manifest(tmp_path):
    _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": [simple("c1")]})
    (tmp_path / "manifest-20260101.json").write_text(json.dumps(_manifest(["conversations-009.zip"])))
    (tmp_path / "manifest-20260201.json").write_text(json.dumps(_manifest(["conversations-000.zip"])))
    e = load_export(tmp_path)
    assert e.complete and e.export_id == "manifest-20260201"


def test_export_date_is_max_updated_at(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps([simple("c1", updated="2026-03-05T08:00:00Z"),
                             simple("c2", updated="2026-04-01T09:30:00Z"),
                             simple("c3", updated="2026-02-01T00:00:00Z")]))
    assert load_export(p).export_date == "2026-04-01T09:30:00Z"


# ---- I7: completeness is proven, never assumed ------------------------------------------------------------------

def test_lone_zip_without_manifest_is_incomplete(tmp_path):
    z = _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": [simple("c1")]})
    assert not load_export(z).complete


def test_folder_without_manifest_is_incomplete(tmp_path):
    _zip(tmp_path / "conversations-001.zip", {"conversations-001/conversations.json": [simple("c1")]})
    assert not load_export(tmp_path).complete
    d = tmp_path / "unpacked"
    (d / "conversations-000").mkdir(parents=True)
    (d / "conversations-000" / "conversations.json").write_text(json.dumps([simple("c2")]))
    assert not load_export(d).complete


def test_conversations_json_with_part_marker_is_incomplete(tmp_path):
    part = tmp_path / "conversations-000"
    part.mkdir()
    (part / "conversations.json").write_text(json.dumps([simple("c1")]))
    assert not load_export(part / "conversations.json").complete


def test_conversations_json_beside_a_manifest_is_incomplete(tmp_path):
    (tmp_path / "conversations.json").write_text(json.dumps([simple("c1")]))
    (tmp_path / "manifest-1.json").write_text(json.dumps(_manifest(["conversations-000.zip",
                                                                     "conversations-001.zip"])))
    assert not load_export(tmp_path / "conversations.json").complete


def test_manifest_listing_no_conversations_is_incomplete(tmp_path):
    _zip(tmp_path / "conversations-000.zip", {"conversations-000/conversations.json": [simple("c1")]})
    (tmp_path / "manifest-1.json").write_text(json.dumps(_manifest(["projects-000.zip"], category="projects")))
    assert not load_export(tmp_path).complete


def test_bare_conversations_json_is_complete(tmp_path):
    p = tmp_path / "e1" / "conversations.json"
    p.parent.mkdir()
    p.write_text(json.dumps([simple("c1")]))
    assert load_export(p).complete


def test_empty_content_list_falls_back_to_text():
    s = session_of(conv("c8", "n", [
        msg("h1", "human", ROOT, [], "2026-01-01T10:00:00Z", text="question in text"),
        msg("a1", "assistant", "h1", [], "2026-01-01T10:00:01Z", text="answer in text"),
    ]))
    assert s.exchanges[0].user_text == "question in text"
    assert s.exchanges[0].assistant_text == "answer in text"


def test_export_date_prefers_manifest_created_at(tmp_path):
    _zip(tmp_path / "conversations-000.zip",
         {"conversations-000/conversations.json": [simple("c1", updated="2026-01-01T11:00:00Z")]})
    m = _manifest(["conversations-000.zip"])
    m["created_at"] = "2026-03-01T00:00:00Z"
    (tmp_path / "manifest-1.json").write_text(json.dumps(m))
    assert load_export(tmp_path).export_date == "2026-03-01T00:00:00Z"
