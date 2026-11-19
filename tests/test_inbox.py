import hashlib
import json

from um.bridge.inbox import ingest_inbox
from um.evidence import load_evidence


def item(inbox, name, path, version, content, updated="2026-11-12T08:30:00Z"):
    (inbox / f"{name}.json").write_text(json.dumps({"path": path, "version": version, "updated": updated, "content": content}))


def test_changed_file_becomes_assistant_evidence(tmp_path):
    inbox, ev = tmp_path / "inbox", tmp_path / "evidence"
    inbox.mkdir()
    item(inbox, "areas-work", "/areas/work.md", 4, "# Work\n\n- Works at Brightline\n")
    ids = ingest_inbox(inbox, ev, {})
    assert ids == ["mem-areas-work-md-v4"]
    e = load_evidence(ev)["mem-areas-work-md-v4"]
    assert e.origin == "assistant" and e.date == "2026-11-12" and "Works at Brightline" in e.text


def test_echo_of_our_own_push_is_skipped(tmp_path):
    inbox, ev = tmp_path / "inbox", tmp_path / "evidence"
    inbox.mkdir()
    content = "# Work\n\n- Works at Brightline\n"
    item(inbox, "w", "/areas/work.md", 5, content)
    state = {"/areas/work.md": {"version": 5, "pushed_sha256": hashlib.sha256(content.encode()).hexdigest()}}
    assert ingest_inbox(inbox, ev, state) == []


def test_two_versions_give_two_ids_and_subfolders_are_left_alone(tmp_path):
    inbox, ev = tmp_path / "inbox", tmp_path / "evidence"
    (inbox / "conflicts").mkdir(parents=True)
    (inbox / "held").mkdir()
    (inbox / "conflicts" / "c.json").write_text("{}")
    (inbox / "held" / "h.md").write_text("origin: tool-output\ndate: 2026-11-12\n\nx\n")
    item(inbox, "a", "/profile.md", 1, "- one\n")
    item(inbox, "b", "/profile.md", 2, "- two\n")
    assert sorted(ingest_inbox(inbox, ev, {})) == ["mem-profile-md-v1", "mem-profile-md-v2"]
    assert (inbox / "conflicts" / "c.json").exists() and (inbox / "held" / "h.md").exists()


def test_empty_inbox(tmp_path):
    (tmp_path / "inbox").mkdir()
    assert ingest_inbox(tmp_path / "inbox", tmp_path / "ev", {}) == []
    assert ingest_inbox(tmp_path / "missing", tmp_path / "ev", {}) == []


def test_materialize_inbox_writes_each_pulled_file_at_its_memory_path_verbatim(tmp_path):
    from um.bridge.inbox import materialize_inbox
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    body = "---\nname: x\nsources: [chat]\n---\n- [stated] Squat 405 lb"
    (inbox / "areas-x-md.json").write_text(json.dumps({"path": "/areas/x.md", "version": "v1", "updated": "u", "content": body}))
    (inbox / "bad.json").write_text(json.dumps({"path": "/../escape.md", "version": "v", "updated": "u", "content": "x"}))
    out = tmp_path / "out"
    assert materialize_inbox(inbox, out) == ["/areas/x.md"]
    assert (out / "areas" / "x.md").read_text() == body
    assert not (tmp_path / "escape.md").exists()
