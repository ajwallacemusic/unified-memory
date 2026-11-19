import hashlib
import json

from um.bridge.adopt import adopt_memory, erased_hashes, record_erased, record_pushed, record_synced


def pull(d, path, version, content, updated="2026-11-17T21:00:00Z"):
    d.mkdir(parents=True, exist_ok=True)
    slug = path.strip("/").replace("/", "-").replace(".", "-")
    (d / f"{slug}-{version}.json").write_text(json.dumps({"path": path, "version": version, "updated": updated,
                                                          "content": content}))


BASE = "---\nname: music\n---\n- [stated] Singer\n- [stated] Plays guitar\n"


def store(tmp_path, base=BASE):
    p = tmp_path / "profile"
    (p / "topics").mkdir(parents=True)
    (p / "topics" / "music.md").write_text(BASE)
    if base is not None:
        record_synced(p, "/topics/music.md", base)
    return p


def lineage(p):
    f = p / ".lineage.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_a_line_a_chat_added_is_appended_with_its_lineage(tmp_path):
    p = store(tmp_path)
    pull(p / "inbox", "/topics/music.md", "v2", BASE + "- [stated] Mandolin is KESTREL-17\n")
    done, merged = adopt_memory(p, p / "inbox", {}, set())
    assert (p / "topics" / "music.md").read_text().endswith("- [stated] Plays guitar\n- [stated] Mandolin is KESTREL-17\n")
    assert done == ["add `- [stated] Mandolin is KESTREL-17` to topics/music.md"] and merged == {"/topics/music.md"}
    row = lineage(p)[-1]
    assert row["file"] == "topics/music.md" and row["origin"] == "assistant"
    assert row["citations"][0]["evidence"] == "mem-topics-music-md-vv2"


def test_a_line_a_chat_removed_or_rewrote_is_removed_from_the_profile(tmp_path):
    p = store(tmp_path)
    pull(p / "inbox", "/topics/music.md", "v2", "---\nname: music\n---\n- [stated] Plays guitar badly\n")
    done, merged = adopt_memory(p, p / "inbox", {}, set())
    text = (p / "topics" / "music.md").read_text()
    assert "Singer" not in text and "- [stated] Plays guitar\n" not in text and "Plays guitar badly" in text
    assert "remove `- [stated] Singer` from topics/music.md" in done and merged == {"/topics/music.md"}


def test_a_line_the_profile_changed_since_the_base_is_not_brought_back(tmp_path):
    p = store(tmp_path)
    (p / "topics" / "music.md").write_text("---\nname: music\n---\n- [stated] Singer\n- [stated] Plays banjo\n")
    pull(p / "inbox", "/topics/music.md", "v2", BASE)
    done, merged = adopt_memory(p, p / "inbox", {}, set())
    assert done == [] and "Plays guitar" not in (p / "topics" / "music.md").read_text()


def test_the_last_push_is_the_base_when_there_is_one(tmp_path):
    p = store(tmp_path, base=None)
    pushed = BASE + "- [stated] Owns a cello\n"
    sha = record_pushed(p, pushed)
    pull(p / "inbox", "/topics/music.md", "v4", BASE + "- [stated] Owns a cello\n- [stated] Sings bass\n")
    done, _ = adopt_memory(p, p / "inbox", {"/topics/music.md": {"pushed_sha256": sha}}, set())
    assert done == ["add `- [stated] Sings bass` to topics/music.md"]


def test_without_a_base_nothing_is_merged_and_the_path_is_not_marked_merged(tmp_path):
    p = store(tmp_path, base=None)
    pull(p / "inbox", "/topics/music.md", "v2", "---\nname: music\n---\n- [stated] Singer\n")
    done, merged = adopt_memory(p, p / "inbox", {}, set())
    assert merged == set() and (p / "topics" / "music.md").read_text() == BASE
    assert done == ["no common base for topics/music.md; memory's edits left for review (the next push conflicts)"]


def test_a_new_memory_file_is_copied_verbatim(tmp_path):
    p = store(tmp_path)
    text = "---\nname: garden\ndescription: garden log\n---\n\n- [stated] Garden log is JUNIPER-42\n"
    pull(p / "inbox", "/topics/garden.md", "g1", text)
    _, merged = adopt_memory(p, p / "inbox", {}, set())
    assert (p / "topics" / "garden.md").read_text() == text and "/topics/garden.md" in merged
    assert lineage(p)[-1]["line"] == "- [stated] Garden log is JUNIPER-42"


def test_an_erased_line_is_never_adopted_again(tmp_path):
    p = store(tmp_path)
    record_erased(p, ["- [stated] Mandolin is KESTREL-17"])
    assert hashlib.sha256(b"- [stated] mandolin is kestrel-17").hexdigest() in erased_hashes(p)
    pull(p / "inbox", "/topics/music.md", "v2", BASE + "- [stated] Mandolin is KESTREL-17\n")
    pull(p / "inbox", "/topics/new.md", "n1", "- [stated] Mandolin is KESTREL-17\n- [stated] Other\n")
    adopt_memory(p, p / "inbox", {}, set())
    assert "KESTREL" not in (p / "topics" / "music.md").read_text()
    assert (p / "topics" / "new.md").read_text() == "- [stated] Other\n"
    assert "kestrel" not in (p / ".um" / "erased.txt").read_text().lower()


def test_echoes_deleted_paths_and_unmirrored_paths_are_skipped(tmp_path):
    p = store(tmp_path)
    echo = BASE + "- [stated] New line\n"
    pull(p / "inbox", "/topics/music.md", "v3", echo)
    pull(p / "inbox", "/areas/nyc.md", "n1", "- [stated] NYC trip\n")
    pull(p / "inbox", "/../escape.md", "e1", "- [stated] x\n")
    state = {"/topics/music.md": {"pushed_sha256": hashlib.sha256(echo.encode()).hexdigest()}}
    done, merged = adopt_memory(p, p / "inbox", state, {"/areas/nyc.md"})
    assert done == [] and merged == {"/topics/music.md"}
    assert not (p / "areas" / "nyc.md").exists() and not (tmp_path / "escape.md").exists()
