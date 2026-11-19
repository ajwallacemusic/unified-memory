import os

from um.tools import Toolbox


def test_paths_cannot_leave_the_root(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    os.symlink(tmp_path / "secret.txt", tmp_path / "s" / "link")
    t = Toolbox(tmp_path / "s", writable=True)
    for p in ("../secret.txt", str(tmp_path / "secret.txt"), "link"):
        assert t.call("view", {"path": p}).startswith("ERROR:")
    assert t.call("write", {"path": "../x", "content": "y"}).startswith("ERROR:")
    assert not (tmp_path / "x").exists()


def test_read_only_box_has_no_write_tools(tmp_path):
    t = Toolbox(tmp_path, writable=False)
    assert {s["name"] for s in t.specs()} == {"view", "grep"}
    assert t.call("write", {"path": "a", "content": "b"}).startswith("ERROR:")
    assert not (tmp_path / "a").exists()


def test_view_lists_a_directory_and_numbers_file_lines(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("first\nsecond\n")
    t = Toolbox(tmp_path, writable=False)
    assert "sub/" in t.view("")
    assert "a.md" in t.view("sub")
    body = t.view("sub/a.md")
    assert "1" in body.splitlines()[0] and "first" in body.splitlines()[0]
    assert "second" in body.splitlines()[1]


def test_write_then_str_replace_requires_exactly_one_match(tmp_path):
    t = Toolbox(tmp_path, writable=True)
    assert not t.write("notes/a.md", "cat cat dog").startswith("ERROR:")
    assert t.str_replace("notes/a.md", "cat", "x").startswith("ERROR:")
    assert t.str_replace("notes/a.md", "bird", "x").startswith("ERROR:")
    assert not t.str_replace("notes/a.md", "dog", "bird").startswith("ERROR:")
    assert (tmp_path / "notes" / "a.md").read_text() == "cat cat bird"


def test_grep_reports_file_and_line(tmp_path):
    (tmp_path / "a.md").write_text("alpha\nbeta gamma\n")
    (tmp_path / "b.md").write_text("gamma\n")
    out = Toolbox(tmp_path, writable=False).grep("gamma")
    assert "a.md:2:" in out and "b.md:1:" in out
    assert Toolbox(tmp_path, writable=False).grep("[unclosed").startswith("ERROR:")


def test_delete_and_unknown_tool(tmp_path):
    (tmp_path / "a.md").write_text("x")
    t = Toolbox(tmp_path, writable=True)
    assert not t.call("delete", {"path": "a.md"}).startswith("ERROR:")
    assert not (tmp_path / "a.md").exists()
    assert t.call("delete", {"path": "a.md"}).startswith("ERROR:")
    assert t.call("nope", {}).startswith("ERROR:")
    assert t.call("view", {"wrong_arg": 1}).startswith("ERROR:")
