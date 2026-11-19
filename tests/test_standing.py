import json

import pytest

from um.code_index import write_code_index
from um.expand import line_key
from um.llm import FakeLLM, Reply
from um.standing import STANDING, label_standing, standing_lines


@pytest.fixture
def prof(tmp_path):
    p = tmp_path / "p"
    (p / "topics").mkdir(parents=True)
    (p / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    (p / "topics" / "food.md").write_text("---\nname: food\ndescription: diet\n---\n"
                                          "- [stated] Allergic to shellfish\n- [stated] Tried oat milk once in 2024\n")
    return p


def r(d):
    return Reply(json.dumps(d), "end_turn", 0, 0)


def test_lines_are_labelled_once_and_standing_ones_listed(prof):
    llm = FakeLLM([r({"1": "standing", "2": "reference"})])
    assert label_standing(prof, llm, "m") == 2
    assert [x for x, _ in standing_lines(prof)] == ["- [stated] Allergic to shellfish"]
    assert label_standing(prof, FakeLLM([]), "m") == 0
    assert "1. Allergic to shellfish" in llm.calls[0]["user"]


def test_profile_md_is_never_sent_since_the_index_inlines_it(prof):
    llm = FakeLLM([r({"1": "standing", "2": "reference"})])
    label_standing(prof, llm, "m")
    assert len(llm.calls) == 1 and "Name: Sam" not in llm.calls[0]["user"]


def test_changed_lines_are_relabelled_and_removed_ones_dropped(prof):
    label_standing(prof, FakeLLM([r({"1": "standing", "2": "reference"})]), "m")
    (prof / "topics" / "food.md").write_text("---\nname: food\ndescription: diet\n---\n- [stated] Allergic to peanuts\n")
    llm = FakeLLM([r({"1": "standing"})])
    assert label_standing(prof, llm, "m") == 1
    labels = json.loads((prof / STANDING).read_text())
    assert line_key("- [stated] Allergic to shellfish") not in labels


def test_a_bad_reply_labels_nothing_for_that_file(prof):
    assert label_standing(prof, FakeLLM([Reply("nope", "end_turn", 0, 0)]), "m") == 0
    assert standing_lines(prof) == []


def test_the_index_carries_standing_lines_inline_with_their_file(prof):
    label_standing(prof, FakeLLM([r({"1": "standing", "2": "reference"})]), "m")
    text = write_code_index(prof, standing=True).read_text()
    assert "## Standing preferences" in text and "Allergic to shellfish (topics/food.md)" in text
    assert "oat milk" not in text


def test_the_index_is_unchanged_without_labels(prof):
    assert "Standing preferences" not in write_code_index(prof).read_text()


def test_the_index_leaves_standing_lines_out_unless_configured(prof, tmp_path, monkeypatch):
    from um.config import save_config
    label_standing(prof, FakeLLM([r({"1": "standing", "2": "reference"})]), "m")
    assert "Standing preferences" not in write_code_index(prof, standing=None).read_text()
    save_config(standing=True)
    assert "Standing preferences" in write_code_index(prof, standing=None).read_text()
