import pytest

from conftest import tree_hash
from um.arms import ARMS, a, a0, z
from um.llm import FakeLLM, Reply

DONE = Reply("ok", "end_turn", 1, 1)


def test_registry_names():
    assert {"z", "a0", "a"} <= set(ARMS) and ARMS["a"].NAME == "a"


def test_z_copies_the_store(tmp_path, store):
    assert z.apply(store, tmp_path / "out", FakeLLM([]), "m", "2026-01-01") == "ok"
    assert tree_hash(tmp_path / "out") == tree_hash(store)


def test_source_store_is_untouched(tmp_path, store):
    before = tree_hash(store)
    llm = FakeLLM([{"tool": "delete", "args": {"path": "topic2.md"}}, DONE])
    assert a.apply(store, tmp_path / "out", llm, "m", "2026-01-01") == "ok"
    assert tree_hash(store) == before and not (tmp_path / "out" / "topic2.md").exists()
    assert "2026-01-01" in llm.calls[0]["system"] + llm.calls[0]["user"]


def test_wrecked_output_is_restored_and_flagged(tmp_path, store):
    script = [{"tool": "delete", "args": {"path": p}} for p in ("MEMORY.md", "topic1.md", "topic2.md")] + [DONE]
    assert a.apply(store, tmp_path / "out", FakeLLM(script), "m", "2026-01-01") == "arm_failed"
    assert tree_hash(tmp_path / "out") == tree_hash(store)


def test_a_store_that_lost_more_than_half_its_bytes_is_restored(tmp_path, store):
    script = [{"tool": "write", "args": {"path": "topic1.md", "content": "x"}},
              {"tool": "write", "args": {"path": "topic2.md", "content": "x"}}, DONE]
    assert a.apply(store, tmp_path / "out", FakeLLM(script), "m", "2026-01-01") == "arm_failed"
    assert tree_hash(tmp_path / "out") == tree_hash(store)


def test_a_non_ok_reply_is_reported_and_the_store_kept(tmp_path, store):
    assert a.apply(store, tmp_path / "out", FakeLLM([Reply("", "max_turns", 1, 1)]), "m", "2026-01-01") == "max_turns"
    assert tree_hash(tmp_path / "out") == tree_hash(store)


def test_a0_uses_the_installed_skill_text_and_fails_clearly_without_it(tmp_path, store, monkeypatch):
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: consolidate-memory\ndescription: d\n---\n\n# Memory Consolidation\nSKILLBODY\n")
    monkeypatch.setattr(a0, "CONSOLIDATE_SKILL_PATH", skill)
    llm = FakeLLM([DONE])
    assert a0.apply(store, tmp_path / "out", llm, "m", "2026-01-01") == "ok"
    assert "SKILLBODY" in llm.calls[0]["system"] and "name: consolidate-memory" not in llm.calls[0]["system"]
    monkeypatch.setattr(a0, "CONSOLIDATE_SKILL_PATH", tmp_path / "missing.md")
    with pytest.raises(FileNotFoundError, match="missing.md"):
        a0.apply(store, tmp_path / "out2", FakeLLM([DONE]), "m", "2026-01-01")
