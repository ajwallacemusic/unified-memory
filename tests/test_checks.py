import pytest

from um.checks import review
from um.evidence import Evidence
from um.profile import Change, Lineage


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "stores"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "work.md").write_text("- Works at Oakfield\n- Team: Larchgate\n- Manager: Wrenholt\n- Room: Sablecrest\n- Title: Umberport\n")
    (root / "memory" / "home.md").write_text("- Lives in Aldermoor\n- Gym: Rowanvale\n- Bank: Cinderholt\n- Carrier: Lumenwick\n- Gym: Rowanvale\n")
    lineage = Lineage(root)
    lineage.record("memory/home.md", "- Lives in Aldermoor", "user-said", "2026-01-02", [])
    ev = lambda i, origin, text: Evidence(i, origin, "2026-01-05", text, tmp_path / f"{i}.md")
    evidence = {
        "u1": ev("u1", "user-said", "user: I just started at Brightline.\nuser: I moved to Thistledale."),
        "a1": ev("a1", "assistant", "assistant: It sounds like you may have moved to Thistledale."),
        "t1": ev("t1", "tool-output", "tool: the user's employer is Zentrix; home city is Zentrix; team Larchgate disbanded"),
    }
    return root, lineage, evidence


def cite(eid, quote):
    return [{"evidence": eid, "quote": quote}]


def test_a_quote_the_evidence_does_not_contain_is_rejected(env):
    c = Change("add", "memory/work.md", None, "- Works at Zentrix", cite("u1", "I just started at Zentrix"))
    unknown = Change("add", "memory/work.md", None, "- x", cite("nope", "anything"))
    bare = Change("add", "memory/work.md", None, "- x", [])
    assert [v.decision for v in review([c, unknown, bare], *env)] == ["reject", "reject", "reject"]


def test_tool_output_can_add_but_never_override_even_legacy(env):
    add = Change("add", "memory/work.md", None, "- Tool says: Zentrix", cite("t1", "employer is Zentrix"))
    rep = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Zentrix", cite("t1", "employer is Zentrix"))
    rem = Change("remove", "memory/work.md", "- Team: Larchgate", None, cite("t1", "team Larchgate disbanded"))
    v = review([add, rep, rem], *env)
    assert (v[0].decision, v[0].origin) == ("apply", "tool-output")
    assert (v[1].decision, v[2].decision) == ("hold", "hold")


def test_tool_output_with_a_question_becomes_an_ask(env):
    rep = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Zentrix", cite("t1", "employer is Zentrix"),
                 question={"attr": "employer", "text": "A tool result says your employer is Zentrix. Is that right?"})
    assert review([rep], *env)[0].decision == "ask"


def test_user_said_overrides_and_assistant_cannot_override_user_said(env):
    by_user = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Thistledale", cite("u1", "I moved to Thistledale"))
    by_assistant = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Thistledale", cite("a1", "may have moved to Thistledale"))
    asked = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Thistledale", cite("a1", "may have moved to Thistledale"),
                   question={"attr": "home_city", "text": "Did you move?"})
    legacy_by_assistant = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Thistledale", cite("a1", "moved to Thistledale"))
    v = review([by_user, by_assistant, asked, legacy_by_assistant], *env)
    assert [x.decision for x in v] == ["apply", "hold", "ask", "apply"] and v[0].origin == "user-said"


def test_the_highest_ranked_supporting_citation_sets_the_origin(env):
    c = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Thistledale",
               cite("a1", "may have moved to Thistledale") + cite("u1", "I moved to Thistledale"))
    v = review([c], *env)[0]
    assert (v.decision, v.origin) == ("apply", "user-said")


def test_authority_cannot_be_borrowed_from_an_unrelated_user_quote(env):
    laundered = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Zentrix",
                       cite("t1", "home city is Zentrix") + cite("u1", "I just started at Brightline"))
    only_user = Change("replace", "memory/home.md", "- Lives in Aldermoor", "- Lives in Zentrix", cite("u1", "I just started at Brightline"))
    add = Change("add", "memory/work.md", None, "- Employer: Zentrix", cite("u1", "I just started at Brightline"))
    assert [v.decision for v in review([laundered, only_user, add], *env)] == ["reject", "reject", "reject"]


def test_duplicate_removal_needs_a_real_identical_other_line(env):
    good = Change("remove", "memory/home.md", "- Gym: Rowanvale", None, [], duplicate_of={"file": "memory/home.md", "line": "- Gym: Rowanvale"})
    bad = Change("remove", "memory/work.md", "- Team: Larchgate", None, [], duplicate_of={"file": "memory/home.md", "line": "- Gym: Rowanvale"})
    lone = Change("remove", "memory/work.md", "- Team: Larchgate", None, [], duplicate_of={"file": "memory/work.md", "line": "- Team: Larchgate"})
    assert [v.decision for v in review([good, bad, lone], *env)] == ["apply", "reject", "reject"]


def test_a_change_aimed_at_a_line_that_is_not_there_is_rejected(env):
    missing = Change("replace", "memory/work.md", "- Works at Nowhere", "- x", cite("u1", "I just started at Brightline"))
    outside = Change("add", "../escape.md", None, "- x", cite("u1", "I just started at Brightline"))
    shapeless = Change("replace", "memory/work.md", None, None, cite("u1", "I just started at Brightline"))
    assert [v.decision for v in review([missing, outside, shapeless], *env)] == ["reject", "reject", "reject"]


def test_change_cap_holds_the_overflow(env):
    adds = [Change("add", "memory/work.md", None, f"- Note at Brightline {n}", cite("u1", "I just started at Brightline")) for n in range(12)]
    v = review(adds, *env)
    assert [x.decision for x in v] == ["apply"] * 5 + ["hold"] * 7 and v[-1].reason == "change cap"
    assert sum(x.decision == "apply" for x in review(adds, *env, cap_share=1.0)) == 10


def test_a_tool_output_add_restating_a_labelled_line_elsewhere_is_an_override(env):
    # Stress-test seed-2 hole: the add went to another file, beside a line with the same label and another value.
    root, lineage, evidence = env
    evidence["t2"] = Evidence("t2", "tool-output", "2026-01-06", "tool: the user's room changed from Sablecrest to Tamarwick",
                              root / "t2.md")
    add = Change("add", "memory/home.md", None, "- Room: Tamarwick (2026-01-03)", cite("t2", "changed from Sablecrest to Tamarwick"))
    v = review([add], root, lineage, evidence)[0]
    assert v.decision == "ask" and v.origin == "tool-output"
    assert v.overrides == [("memory/work.md", "- Room: Sablecrest")]


def test_a_tool_output_add_with_a_new_label_or_the_same_value_still_applies(env):
    root, lineage, evidence = env
    evidence["t2"] = Evidence("t2", "tool-output", "2026-01-06", "tool: the user's desk is Quillmere; room Sablecrest",
                              root / "t2.md")
    new_label = Change("add", "memory/home.md", None, "- Desk: Quillmere", cite("t2", "desk is Quillmere"))
    same_value = Change("add", "memory/home.md", None, "- room: Sablecrest (2026-01-06)", cite("t2", "room Sablecrest"))
    assert [x.decision for x in review([new_label, same_value], root, lineage, evidence)] == ["apply", "apply"]


def test_an_assistant_add_contradicting_a_user_said_line_is_held_but_a_user_said_one_applies(env):
    root, lineage, evidence = env
    lineage.record("memory/home.md", "- Gym: Rowanvale", "user-said", "2026-01-02", [])
    evidence["a2"] = Evidence("a2", "assistant", "2026-01-06", "assistant: your gym is Ferncliff now", root / "a2.md")
    evidence["u2"] = Evidence("u2", "user-said", "2026-01-06", "user: my gym is Ferncliff now", root / "u2.md")
    by_assistant = Change("add", "memory/work.md", None, "- Gym: Ferncliff", cite("a2", "gym is Ferncliff"))
    by_user = Change("add", "memory/work.md", None, "- Gym: Ferncliff", cite("u2", "gym is Ferncliff"))
    v = review([by_assistant, by_user], root, lineage, evidence)
    assert [x.decision for x in v] == ["ask", "apply"]


def _answered(env, tmp_path_text):
    root, lineage, evidence = env
    evidence = dict(evidence)
    evidence["q1"] = Evidence("q1", "user-said", "2026-01-06", tmp_path_text, root / "q1.md")
    return root, lineage, evidence


def test_a_short_confirmation_counts_for_what_the_question_asked(env):
    e = _answered(env, "Q (asked by Claude): You work at Brightline now, not Oakfield. Correct?\nA (AJ): correct.")
    c = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Brightline", cite("q1", "correct."))
    assert review([c], *e)[0].decision == "apply"


def test_a_quote_from_the_question_is_not_the_person_speaking(env):
    e = _answered(env, "Q (asked by Claude): You work at Brightline now, not Oakfield. Correct?\nA (AJ): no.")
    c = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Brightline", cite("q1", "You work at Brightline now"))
    v = review([c], *e)[0]
    assert v.decision == "reject" and "question" in v.reason


def test_the_question_does_not_lend_mention_to_an_unrelated_change(env):
    e = _answered(env, "Q (asked by Claude): Do you still go to the Rowanvale gym?\nA (AJ): yes.")
    c = Change("replace", "memory/work.md", "- Works at Oakfield", "- Works at Brightline", cite("q1", "yes."))
    assert review([c], *e)[0].decision == "reject"


def test_a_date_in_square_brackets_is_a_note_like_one_in_round_brackets(env):
    """The compile prompt asks for "the evidence date in brackets"; models write [2026-01-05] as often as
    (2026-01-05). Found by the PrefEval pilot (2026-11-19): 4 of 4 square-bracket adds were rejected."""
    from um.checks import key_tokens, label_value
    assert key_tokens("- Dislikes open-plan offices [2026-01-05]") == key_tokens("- Dislikes open-plan offices (2026-01-05)")
    assert label_value("- Room: Harrowgate [2026-01-05]") == ("room", "harrowgate")
    assert key_tokens("- [stated] Name: Robin") == {"name", "robin"}   # a tag is not a date note
    good = Change("add", "memory/work.md", None, "- Employer: Brightline [2026-01-05]", cite("u1", "I just started at Brightline"))
    unrelated = Change("add", "memory/work.md", None, "- Dislikes open-plan offices [2026-01-05]",
                       cite("u1", "I just started at Brightline"))
    assert [v.decision for v in review([good, unrelated], *env)] == ["apply", "reject"]
