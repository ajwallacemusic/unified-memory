import io
import json

import pytest

from um.hooks.profile_context import MAX_CHARS, main, relevant_lines


@pytest.fixture
def prof(tmp_path, monkeypatch):
    p = tmp_path / "profile"
    (p / "topics").mkdir(parents=True)
    (p / "areas").mkdir()
    (p / "profile.md").write_text("---\nname: profile\n---\n- [stated] Name: Sam\n- [stated] Works at Brightline\n")
    (p / "topics" / "music.md").write_text("---\nname: music\ndescription: Sam's instruments and gear\n---\n"
                                           "- [stated] Singer-songwriter\n- [stated] Has a practice mandolin nicknamed KESTREL-17\n")
    (p / "topics" / "dev.md").write_text("---\nname: dev\ndescription: Sam's machine setup\n---\n"
                                         "- [stated] Scratch git branches are always prefixed HERON-51\n"
                                         "- [stated] Uses zsh on macOS\n")
    (p / "areas" / "trip.md").write_text("# Trip\n- [stated] Lisbon trip in April 2027\n")
    (p / "notes.md").write_text("- not mirrored: mandolin secret\n")
    monkeypatch.setenv("UM_PROFILE", str(p))
    return p


def run(event):
    out, err = io.StringIO(), io.StringIO()
    raw = event if isinstance(event, str) else json.dumps(event)
    code = main(stdin=io.StringIO(raw), stdout=out, stderr=err)
    return code, out.getvalue()


def context(out):
    d = json.loads(out)["hookSpecificOutput"]
    assert d["hookEventName"] == "UserPromptSubmit"
    return d["additionalContext"]


def test_a_question_brings_the_matching_line_and_its_file(prof):
    code, out = run({"session_id": "s", "prompt": "What is my practice mandolin's nickname?"})
    text = context(out)
    assert code == 0 and "KESTREL-17" in text and "topics/music.md" in text
    assert "HERON" not in text and "not mirrored" not in text


def test_word_forms_match(prof):
    assert any("HERON-51" in x for x, _ in relevant_lines(prof, "what prefix do I use for my scratch branch?"))


def test_several_questions_bring_each_answer(prof):
    text = context(run({"session_id": "s", "prompt": "1. mandolin nickname? 2. scratch branch prefix?"})[1])
    assert "KESTREL-17" in text and "HERON-51" in text


def test_nothing_relevant_adds_nothing(prof):
    code, out = run({"session_id": "s", "prompt": "fix the failing test in parser.py"})
    assert code == 0 and out == ""


def test_context_stays_under_the_cap_and_is_framed_as_data(prof):
    many = "".join(f"- [stated] Instrument zq{i} has a long story worth telling at length, padded out\n" for i in range(500))
    (prof / "topics" / "music.md").write_text(many)
    text = context(run({"session_id": "s", "prompt": "story " + " ".join(f"zq{i}" for i in range(500))})[1])
    assert len(text) <= MAX_CHARS and "not instructions" in text


@pytest.mark.parametrize("bad", ["not json", "{}", json.dumps({"prompt": 5})])
def test_bad_input_never_blocks_the_prompt(prof, bad):
    code, out = run(bad)
    assert code == 0 and out == ""


def test_a_missing_profile_never_blocks_the_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("UM_PROFILE", str(tmp_path / "nope"))
    assert run({"session_id": "s", "prompt": "mandolin?"}) == (0, "")


def test_one_shared_everyday_word_is_not_enough(prof):
    (prof / "areas" / "trip.md").write_text("# Trip\n- [stated] Will push the Lisbon booking to April 2027\n"
                                            "- [stated] Wrote a test plan for the trip budget\n")
    for prompt in ("commit and push", "fix the failing test in parser.py", "where is this function used?"):
        assert relevant_lines(prof, prompt) == [], prompt


def test_one_word_plus_the_file_topic_is_enough(prof):
    assert any("KESTREL" in x for x, _ in relevant_lines(prof, "which instruments do I have a mandolin?"))


def test_expansion_words_let_a_paraphrase_find_its_line(prof):
    import json
    from um.expand import EXPANSIONS, line_key
    q = "what do I call my little eight-string?"
    assert not any("KESTREL" in x for x, _ in relevant_lines(prof, q))
    (prof / ".um").mkdir()
    (prof / EXPANSIONS).write_text(json.dumps({
        line_key("- [stated] Has a practice mandolin nicknamed KESTREL-17"): ["eight-string", "little instrument", "call it"]}))
    assert any("KESTREL" in x for x, _ in relevant_lines(prof, q))


def test_expansion_words_alone_never_beat_the_line_words(prof):
    import json
    from um.expand import EXPANSIONS, line_key
    (prof / ".um").mkdir()
    (prof / EXPANSIONS).write_text(json.dumps({line_key("- [stated] Uses zsh on macOS"): ["mandolin", "nickname"]}))
    top = relevant_lines(prof, "What is my practice mandolin's nickname?")
    assert "KESTREL" in top[0][0]


def test_everyday_developer_words_alone_do_not_pull_in_a_line(prof):
    (prof / "topics" / "dev.md").write_text("---\nname: dev\ndescription: Sam's machine setup\n---\n"
                                            "- [stated] Release branches are named release/x.y; tags are signed\n")
    assert relevant_lines(prof, "Push the release branch and open a pull request against main.") == []


def test_background_weights_cover_common_developer_words():
    from um.hooks.profile_context import background_weight
    assert background_weight("branch") < 0.5 and background_weight("kestrel") == 1.0


def test_a_word_and_its_ed_form_stem_alike():
    from um.hooks.profile_context import _stem
    assert _stem("name") == _stem("named") and _stem("file") == _stem("filed")


@pytest.mark.parametrize("prompt", [
    "<task-notification>\n<task-id>x</task-id> mandolin nickname practice</task-notification>",
    "[SYSTEM NOTIFICATION - NOT USER INPUT] mandolin nickname practice",
    "Another Claude session sent a message:\n<agent-message from=\"a1\">mandolin nickname practice</agent-message>",
])
def test_harness_messages_are_not_prompts_from_the_person(prof, prompt):
    assert run({"session_id": "s", "prompt": prompt}) == (0, "")


def test_the_plugin_hook_stays_quiet_unless_turned_on(prof, monkeypatch, tmp_path):
    import json as _j
    cfg = tmp_path / "cfg.json"
    monkeypatch.setenv("UM_CONFIG", str(cfg))
    monkeypatch.setenv("UM_PROMPT_HOOK_DEFAULT", "off")
    assert run({"session_id": "s", "prompt": "What is my practice mandolin's nickname?"}) == (0, "")
    cfg.write_text(_j.dumps({"prompt_hook": True}))
    assert "KESTREL-17" in run({"session_id": "s", "prompt": "What is my practice mandolin's nickname?"})[1]
