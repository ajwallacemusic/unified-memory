import json

import pytest

from um.expand import EXPANSIONS, expand_profile, line_key, load_expansions
from um.llm import FakeLLM, Reply


@pytest.fixture
def prof(tmp_path):
    p = tmp_path / "p"
    (p / "topics").mkdir(parents=True)
    (p / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    (p / "topics" / "food.md").write_text("---\nname: food\ndescription: diet\n---\n"
                                          "- [stated] Daughter is allergic to shellfish\n- [stated] Drinks oat milk\n")
    return p


def reply_for(n_lines):
    return Reply(json.dumps({str(i): [f"word{i}a", f"word{i}b"] for i in range(1, n_lines + 1)}), "end_turn", 0, 0)


def test_every_fact_line_gets_expansion_words(prof):
    llm = FakeLLM([reply_for(1), reply_for(2)])
    assert expand_profile(prof, llm, "m") == 3
    exp = load_expansions(prof)
    assert exp[line_key("- [stated] Daughter is allergic to shellfish")] == ["word1a", "word1b"]
    assert exp[line_key("- [stated] Drinks oat milk")] == ["word2a", "word2b"]
    assert (prof / EXPANSIONS).exists()


def test_the_request_shows_lines_and_file_topic_but_asks_for_new_words(prof):
    llm = FakeLLM([reply_for(1), reply_for(2)])
    expand_profile(prof, llm, "m")
    users = [c["user"] for c in llm.calls]
    assert any("1. Daughter is allergic to shellfish" in u and "diet" in u for u in users)


def test_unchanged_lines_are_not_asked_again_and_removed_lines_are_dropped(prof):
    expand_profile(prof, FakeLLM([reply_for(1), reply_for(2)]), "m")
    (prof / "topics" / "food.md").write_text("---\nname: food\ndescription: diet\n---\n"
                                             "- [stated] Daughter is allergic to shellfish\n- [stated] Drinks soy milk\n")
    llm = FakeLLM([reply_for(1)])
    assert expand_profile(prof, llm, "m") == 1
    assert "1. Drinks soy milk" in llm.calls[0]["user"] and "shellfish" not in llm.calls[0]["user"]
    exp = load_expansions(prof)
    assert line_key("- [stated] Drinks oat milk") not in exp and line_key("- [stated] Drinks soy milk") in exp


def test_a_bad_reply_keeps_what_was_there_and_skips_that_file(prof):
    expand_profile(prof, FakeLLM([reply_for(1), reply_for(2)]), "m")
    (prof / "topics" / "food.md").write_text("---\nname: food\ndescription: diet\n---\n- [stated] Likes figs\n")
    assert expand_profile(prof, FakeLLM([Reply("not json", "end_turn", 0, 0)]), "m") == 0
    assert line_key("- [stated] Name: Sam") in load_expansions(prof)


def test_words_are_cleaned_and_capped():
    from um.expand import _clean
    assert _clean(["Seafood", "  shrimp ", "", 5, "x" * 80] + [f"w{i}" for i in range(40)]) [:2] == ["seafood", "shrimp"]
    assert len(_clean([f"w{i}" for i in range(40)])) == 24


def test_missing_or_broken_file_loads_as_empty(tmp_path):
    assert load_expansions(tmp_path) == {}
    (tmp_path / ".um").mkdir()
    (tmp_path / EXPANSIONS).write_text("{oops")
    assert load_expansions(tmp_path) == {}


def test_the_hook_and_the_writer_key_lines_the_same_way():
    from um.hooks.profile_context import _key
    for line in ("- [stated] Drinks oat milk", "  - [stated]  Spaced   out  "):
        assert _key(line) == line_key(line)
