import json
from pathlib import Path

import pytest

from um.bench.recall_data import load_questions, validate

BENCH = Path(__file__).resolve().parents[1] / "bench" / "recall"


def write(root, questions, offtopic=({"id": "o1", "prompt": "fix the flaky test"},)):
    (root / "profile" / "topics").mkdir(parents=True, exist_ok=True)
    (root / "profile" / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n")
    (root / "profile" / "topics" / "music.md").write_text(
        "---\nname: music\ndescription: instruments\n---\n- [stated] Mandolin nicknamed Kestrel\n- [stated] Lives with Sam's cat Juniper\n")
    (root / "profile" / "topics" / "pets.md").write_text("---\nname: pets\ndescription: pets\n---\n- [stated] Cat named Juniper\n")
    (root / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in questions))
    (root / "offtopic.jsonl").write_text("".join(json.dumps(q) + "\n" for q in offtopic))
    return root


def q(id, split="dev", kind="direct", question="What is my mandolin called?", terms=("Kestrel",), file="topics/music.md"):
    return {"id": id, "split": split, "kind": kind, "question": question, "answer_terms": list(terms), "file": file}


def test_a_clean_bench_has_no_problems(tmp_path):
    assert validate(write(tmp_path, [q("a"), q("b", split="test")])) == []


def test_answer_in_the_question_is_flagged(tmp_path):
    probs = validate(write(tmp_path, [q("a", question="Is my mandolin called Kestrel?"), q("b", split="test")]))
    assert any("a:" in p and "question" in p for p in probs)


def test_answer_missing_from_its_file_is_flagged(tmp_path):
    probs = validate(write(tmp_path, [q("a", terms=("Falcon",)), q("b", split="test")]))
    assert any("a:" in p and "not in" in p for p in probs)


def test_answer_also_in_another_file_is_flagged_unless_multi(tmp_path):
    root = write(tmp_path, [q("a", terms=("Juniper",), question="What is my cat's name?"), q("b", split="test")])
    assert any("a:" in p and "pets.md" in p for p in validate(root))
    root = write(tmp_path, [q("a", kind="multi", terms=("Juniper",), question="Cat's name?",
                              file=["topics/music.md", "topics/pets.md"]), q("b", split="test")])
    assert validate(root) == []


def test_duplicate_ids_bad_fields_and_lopsided_splits_are_flagged(tmp_path):
    probs = validate(write(tmp_path, [q("a"), q("a"), q("c", kind="weird"), q("d", split="x")]))
    assert any("duplicate" in p for p in probs) and any("kind" in p for p in probs)
    assert any("split" in p for p in probs)


def test_missing_file_and_empty_offtopic_are_flagged(tmp_path):
    probs = validate(write(tmp_path, [q("a", file="topics/nope.md"), q("b", split="test")], offtopic=[{"id": "o", "prompt": ""}]))
    assert any("nope.md" in p for p in probs) and any("o:" in p for p in probs)


def test_load_questions_filters_by_split(tmp_path):
    root = write(tmp_path, [q("a"), q("b", split="test")])
    assert [x["id"] for x in load_questions(root, "test")] == ["b"]


@pytest.mark.skipif(not (BENCH / "questions.jsonl").exists(), reason="bench data not written yet")
def test_the_shipped_bench_is_valid():
    assert validate(BENCH) == []
