import json

from um.llm import FakeLLM, Reply
from um.review import review_store, write_review

TRIP = "- [stated] Planning a Lisbon trip in late September 2026"
PETS = "- [stated] Has no pets"
DOG = "- [stated] Walks her dog Rex every morning"


def store(tmp_path):
    p = tmp_path / "profile"
    (p / "areas").mkdir(parents=True)
    (p / "topics").mkdir()
    (p / "profile.md").write_text(f"---\nname: profile\n---\n# Me\n{PETS}\n")
    (p / "areas" / "lisbon.md").write_text(f"# Lisbon\n{TRIP}\n")
    (p / "topics" / "dog.md").write_text(f"# Dog\n{DOG}\n")
    (p / "notes.md").write_text("- not mirrored, never shown\n")
    return p


def reply(items, fenced=False):
    text = json.dumps(items)
    return Reply(f"```json\n{text}\n```" if fenced else text, "end_turn", 1, 1)


def finding(**kw):
    base = {"file": "/areas/lisbon.md", "line": TRIP, "kind": "elapsed", "other_file": None, "other_line": None,
            "question": "Did the Lisbon trip happen?"}
    return {**base, **kw}


def test_the_model_sees_every_mirrored_file_and_today(tmp_path):
    p = store(tmp_path)
    llm = FakeLLM([reply([])])
    review_store(p, llm, "m", "2026-11-11")
    call = llm.calls[0]
    assert "## /areas/lisbon.md" in call["user"] and "## /profile.md" in call["user"] and DOG in call["user"]
    assert "not mirrored" not in call["user"] and "name: profile" not in call["user"]
    assert "2026-11-11" in call["system"] and "{as_of}" not in call["system"]


def test_valid_findings_are_kept_and_unverifiable_ones_dropped(tmp_path):
    p = store(tmp_path)
    good = finding()
    contra = finding(file="/profile.md", line=PETS, kind="contradiction", other_file="/topics/dog.md",
                     other_line=DOG, question="Do you have a dog now?")
    paraphrased = finding(line="- [stated] Planning a trip to Lisbon in September")
    no_other = finding(file="/profile.md", line=PETS, kind="contradiction", other_line="- [stated] Owns a cat")
    bad_kind = finding(kind="sensitive")
    no_question = finding(question=" ")
    wrong_file = finding(file="/topics/dog.md")
    llm = FakeLLM([reply([good, contra, paraphrased, no_other, bad_kind, no_question, wrong_file, good], fenced=True)])
    found, dropped = review_store(p, llm, "m", "2026-11-11")
    assert [f["kind"] for f in found] == ["elapsed", "contradiction"]
    assert dropped == 5


def test_review_never_changes_the_store(tmp_path):
    p = store(tmp_path)
    before = {f: f.read_text() for f in p.rglob("*.md")}
    review_store(p, FakeLLM([reply([finding()])]), "m", "2026-11-11")
    assert {f: f.read_text() for f in p.rglob("*.md")} == before


def test_unparseable_reply_gives_no_findings(tmp_path):
    p = store(tmp_path)
    found, dropped = review_store(p, FakeLLM([Reply("I could not do this.", "end_turn", 1, 1)]), "m", "2026-11-11")
    assert found == [] and dropped == 0


def test_write_review_lists_each_question_with_its_line(tmp_path):
    out = tmp_path / "digest" / "2026-11-11-review.md"
    write_review([finding()], out, "2026-11-11", dropped=2)
    text = out.read_text()
    assert "Did the Lisbon trip happen?" in text and TRIP in text and "/areas/lisbon.md" in text
    assert "2 dropped" in text


def test_cli_review_writes_a_digest_and_commits_nothing(tmp_path):
    import subprocess
    from um.cli import main
    p = store(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    main(["review", "--profile", str(p), "--today", "2026-11-11"], llm=FakeLLM([reply([finding()])]))
    assert "Lisbon" in (p / "digest" / "2026-11-11-review.md").read_text()
    log = subprocess.run(["git", "log", "--oneline"], cwd=p, capture_output=True, text=True)
    assert log.stdout.strip() == ""
