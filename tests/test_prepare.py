import hashlib
import json

from um.bridge.policy import DEFAULT_POLICY as _DEFAULTS

DEFAULT_POLICY = {**_DEFAULTS, "training-lifts": "push"}  # these fixtures are a user who opted lifts in
from um.bridge.prepare import MAX_BYTES, build_outbox, ready_for_live

ID = "identity-work-projects-preferences"


def h(line):
    return hashlib.sha1(line.encode()).hexdigest()


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def profile(tmp_path):
    p = tmp_path / "claude-profile"
    (p / "areas").mkdir(parents=True)
    (p / "topics").mkdir()
    (p / "profile.md").write_text("# Profile\n\n- Works at Brightline\n- Weighs 190 lb\n- Card 4111 1111 1111 1111\n")
    (p / "areas" / "training.md").write_text("# Training\n\n- Squat 405 lb\n")
    (p / "notes.md").write_text("- not a mirrored path\n")
    (p / "inbox").mkdir()
    (p / "inbox" / "x.md").write_text("- inbox is never pushed\n")
    cats = {h("- Works at Brightline"): ID, h("- Weighs 190 lb"): "body-weight-nutrition", h("- Card 4111 1111 1111 1111"): ID,
            h("- Squat 405 lb"): "training-lifts"}
    return p, cats


def test_policy_filtered_lines_are_absent_and_listed_without_their_text(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only")
    pushed = (p / "outbox" / "profile.md").read_text()
    assert "Brightline" in pushed and "190" not in pushed and "4111" not in pushed and "# Profile" in pushed
    e = next(x for x in m.entries if x.path == "/profile.md")
    assert {r["state"] for r in e.removed_by_policy} == {"local", "never"}
    manifest = (p / "outbox" / "manifest.json").read_text()
    assert "190" not in manifest and "4111" not in manifest and "propose-only" in manifest
    assert {x.path for x in m.entries} == {"/profile.md", "/areas/training.md"}
    assert not (p / "outbox" / "notes.md").exists() and not (p / "outbox" / "inbox").exists()


def test_entry_carries_the_version_it_was_built_from(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {"/profile.md": {"version": 7, "pushed_sha256": "old"}}, "live")
    assert next(x for x in m.entries if x.path == "/profile.md").expected_version == 7
    assert next(x for x in m.entries if x.path == "/areas/training.md").expected_version is None


def test_unchanged_file_produces_no_entry(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live")
    e = next(x for x in m.entries if x.path == "/areas/training.md")
    state = {"/areas/training.md": {"version": 3, "pushed_sha256": e.sha256}}
    m2 = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, state, "live")
    assert "/areas/training.md" not in {x.path for x in m2.entries}
    assert e.sha256 == sha256((p / "areas" / "training.md").read_text())


def test_oversize_file_is_held(tmp_path):
    p, cats = profile(tmp_path)
    big = "# Big\n" + "".join(f"- fact number {i} about the person\n" for i in range(2000))
    (p / "topics" / "big.md").write_text(big)
    cats.update({h(line.strip()): ID for line in big.splitlines()[1:]})
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live")
    assert len(big.encode()) > MAX_BYTES == 49_152
    assert "/topics/big.md" not in {x.path for x in m.entries}
    assert {"path": "/topics/big.md", "reason": "too large"} in m.held


def test_vanished_path_is_held_as_a_removal_proposal_never_deleted(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {"/people/old.md": {"version": 2, "pushed_sha256": "x"}}, "live")
    assert {"path": "/people/old.md", "reason": "removal proposal"} in m.held
    assert "/people/old.md" not in {x.path for x in m.entries}
    assert "delete" not in (p / "outbox" / "manifest.json").read_text().lower()


def test_file_with_nothing_to_push_is_held(tmp_path):
    p, cats = profile(tmp_path)
    (p / "topics" / "body.md").write_text("# Body\n\n- Weighs 190 lb\n")
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live")
    assert {"path": "/topics/body.md", "reason": "nothing to push"} in m.held


def run(mode="propose-only", proposed=2, rejected=0, reviewed=True):
    return {"run_at": "2026-11-12T09:00:00Z", "mode": mode, "proposed": proposed, "rejected": rejected, "reviewed": reviewed}


def test_ready_for_live_needs_two_clean_reviewed_propose_only_runs():
    assert not ready_for_live([])
    assert not ready_for_live([run()])
    assert not ready_for_live([run(), run(mode="live")])
    assert not ready_for_live([run(), run(rejected=1)])
    assert not ready_for_live([run(), run(reviewed=False)])
    assert not ready_for_live([run(), run(proposed=0)])
    assert ready_for_live([run(rejected=3), run(), run()])


def test_live_stays_allowed_after_the_gate_until_a_rejection():
    from um.bridge.prepare import live_allowed
    assert not live_allowed([run()])
    assert live_allowed([run(), run()])
    assert live_allowed([run(), run(), run(mode="live", reviewed=False, rejected=0)])
    assert live_allowed([run(), run(), run(mode="live"), run(mode="live")])
    assert not live_allowed([run(), run(), run(mode="live", rejected=1)])
    assert live_allowed([run(), run(), run(mode="live", rejected=1), run(), run()])


def test_prepare_creates_an_empty_state_file(tmp_path):
    from um.bridge.prepare import main
    p, _ = profile(tmp_path)
    main(["--profile", str(p), "--mode", "propose-only"])
    assert json.loads((p / "state.json").read_text()) == {}


def test_frontmatter_is_structure_kept_verbatim_and_never_categorised(tmp_path):
    from um.bridge.prepare import fact_lines
    p = tmp_path / "claude-profile"
    (p / "areas").mkdir(parents=True)
    text = "---\nname: training\ndescription: lifts and plans\n---\n\n# Training\n\n- Squat 405 lb\n"
    (p / "areas" / "training.md").write_text(text)
    m = build_outbox(p, p / "outbox", dict(DEFAULT_POLICY), {h("- Squat 405 lb"): "training-lifts"}, {}, "propose-only")
    assert (p / "outbox" / "areas" / "training.md").read_text() == text
    assert m.entries[0].removed_by_policy == []
    assert fact_lines(text) == ["- Squat 405 lb"]


def test_categorize_profile_labels_fact_lines_and_counts_by_policy_state(tmp_path):
    from um.bridge.prepare import categorize_profile
    from um.llm import FakeLLM, Reply
    p = tmp_path / "claude-profile"
    (p / "areas").mkdir(parents=True)
    (p / "profile.md").write_text("---\nname: profile\n---\n# Me\n- Works at Brightline\n- Weighs 190 lb\n- Likes jazz\n")
    (p / "notes.md").write_text("- not mirrored\n")
    llm = FakeLLM([Reply(json.dumps({"0": ID, "1": "body-weight-nutrition", "2": "other"}), "end_turn", 1, 1)])
    counts = categorize_profile(p, llm, "m")
    assert counts == {"categories": {ID: 1, "body-weight-nutrition": 1, "other": 1},
                      "states": {"push": 1, "local": 2}}
    assert "not mirrored" not in llm.calls[0]["user"] and "name: profile" not in llm.calls[0]["user"]
    assert len(json.loads((p / ".um" / "categories.json").read_text())) == 3


def test_last_pull_in_state_is_not_a_memory_path(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", dict(DEFAULT_POLICY), cats, {"last_pull": "2026-11-11T02:34:06Z"}, "propose-only")
    assert all(h["path"] != "last_pull" for h in m.held)


def test_category_policy_never_removes_a_line_already_in_memory(tmp_path):
    p, cats = profile(tmp_path)
    memory = {"/profile.md": ["- Works at Brightline", "- Weighs 190 lb"]}
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only", in_memory=memory)
    pushed = (p / "outbox" / "profile.md").read_text()
    assert "190" in pushed
    e = next(x for x in m.entries if x.path == "/profile.md")
    assert e.kept_in_memory == 1


def test_a_revised_line_replaces_its_memory_version_instead_of_deleting_it(tmp_path):
    p, cats = profile(tmp_path)
    (p / "profile.md").write_text("# Profile\n\n- Works at Brightline\n- Weighs 190 lb as of Nov 2026, down from 200\n")
    cats[h("- Weighs 190 lb as of Nov 2026, down from 200")] = "body-weight-nutrition"
    memory = {"/profile.md": ["- Works at Brightline", "- Weighs 190 lb as of Nov 2026"]}
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only", in_memory=memory)
    assert "down from 200" in (p / "outbox" / "profile.md").read_text()


def test_a_new_sensitive_line_is_still_kept_back(tmp_path):
    p, cats = profile(tmp_path)
    memory = {"/profile.md": ["- Works at Brightline"]}
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only", in_memory=memory)
    assert "190" not in (p / "outbox" / "profile.md").read_text()


def test_a_blocked_pattern_is_removed_even_if_memory_holds_it(tmp_path):
    p, cats = profile(tmp_path)
    memory = {"/profile.md": ["- Works at Brightline", "- Card 4111 1111 1111 1111"]}
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only", in_memory=memory)
    assert "4111" not in (p / "outbox" / "profile.md").read_text()


def test_memory_lines_come_from_the_latest_pull_of_each_path(tmp_path):
    from um.bridge.prepare import memory_lines
    p = tmp_path / "claude-profile"
    (p / ".um" / "inbox-done").mkdir(parents=True)
    (p / "inbox").mkdir()
    old = {"path": "/a.md", "version": "1", "updated": "2026-11-01T00:00:00Z", "content": "---\nname: a\n---\n# A\n- old line\n"}
    new = {"path": "/a.md", "version": "2", "updated": "2026-11-10T00:00:00Z", "content": "---\nname: a\n---\n# A\n- new line\n"}
    (p / ".um" / "inbox-done" / "a.json").write_text(json.dumps(old))
    (p / "inbox" / "a.json").write_text(json.dumps(new))
    assert memory_lines(p) == {"/a.md": ["- new line"]}


def test_a_line_from_the_persons_answer_is_pushed_whatever_its_category(tmp_path):
    from um.bridge.prepare import answered_lines
    p, cats = profile(tmp_path)
    (p / "profile.md").write_text("# Profile\n\n- Works at Brightline\n- Trip happened, it was great\n- Card 4111 1111 1111 1111\n")
    (p / ".answers").mkdir()
    (p / ".answers" / "u20261111-01.md").write_text("origin: user-said\ndate: 2026-11-11\n\nQ (asked by Claude): trip?\nA (AJ): great\n")
    lineage = [{"file": "profile.md", "line": "- Trip happened, it was great", "citations": [{"evidence": "u20261111-01"}]},
               {"file": "profile.md", "line": "- Card 4111 1111 1111 1111", "citations": [{"evidence": "u20261111-01"}]},
               {"file": "areas/training.md", "line": "- Squat 405 lb", "citations": [{"evidence": "chat-7"}]}]
    (p / ".lineage.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lineage))
    answered = answered_lines(p)
    assert answered == {"/profile.md": {"- Trip happened, it was great", "- Card 4111 1111 1111 1111"}}
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "propose-only", answered=answered)
    pushed = (p / "outbox" / "profile.md").read_text()
    assert "Trip happened" in pushed and "4111" not in pushed


def _pulled(p, path, version, content="# x\n- a line\n", where=(".um", "inbox-done")):
    d = p.joinpath(*where)
    d.mkdir(parents=True, exist_ok=True)
    slug = path.strip("/").replace("/", "-").replace(".", "-")
    (d / f"{slug}.json").write_text(json.dumps({"path": path, "version": version, "updated": "2026-11-16T00:00:00Z",
                                                "content": content}))


def test_expected_version_comes_from_the_last_compiled_pull(tmp_path):
    from um.bridge.prepare import pulled_versions
    p, cats = profile(tmp_path)
    _pulled(p, "/profile.md", "abc123")
    _pulled(p, "/areas/training.md", "newer9", where=("inbox",))
    versions = pulled_versions(p)
    assert versions == {"/profile.md": "abc123"}
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled=versions)
    assert next(x for x in m.entries if x.path == "/profile.md").expected_version == "abc123"
    assert next(x for x in m.entries if x.path == "/areas/training.md").expected_version is None


def test_a_memory_file_gone_from_the_profile_is_held_until_approved_then_proposed_for_deletion(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled={"/areas/nyc.md": "v1"})
    assert {"path": "/areas/nyc.md", "reason": "removal proposal"} in m.held and m.deletions == []
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled={"/areas/nyc.md": "v1"},
                     approved_deletions={"/areas/nyc.md", "/profile.md"})
    assert m.deletions == [{"path": "/areas/nyc.md", "expected_version": "v1"}]
    assert all(h["path"] != "/areas/nyc.md" for h in m.held)
    assert "/profile.md" in {x.path for x in m.entries}


def test_approved_deletions_are_read_one_path_per_line(tmp_path):
    from um.bridge.prepare import approved_deletions
    p, _ = profile(tmp_path)
    assert approved_deletions(p) == set()
    (p / "delete-approved.txt").write_text("# paths AJ approved for deletion\n/areas/nyc.md\n\nareas/x.md\n")
    assert approved_deletions(p) == {"/areas/nyc.md"}


def test_a_file_whose_text_memory_already_holds_is_not_sent(tmp_path):
    from um.bridge.prepare import pulled_texts, pulled_versions
    p, cats = profile(tmp_path)
    text = (p / "areas" / "training.md").read_text()
    _pulled(p, "/areas/training.md", "v1", content=text)
    _pulled(p, "/profile.md", "v2", content="# Profile\n\n- Works somewhere else\n")
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled=pulled_versions(p),
                     memory_text=pulled_texts(p))
    assert {x.path for x in m.entries} == {"/profile.md"}
    assert not (p / "outbox" / "areas" / "training.md").exists()


def test_a_stale_pull_does_not_hide_a_change_after_a_later_push(tmp_path):
    from um.bridge.prepare import pulled_texts, pulled_versions
    p, cats = profile(tmp_path)
    text = (p / "areas" / "training.md").read_text()
    _pulled(p, "/areas/training.md", "v1", content=text)
    state = {"/areas/training.md": {"version": "v5", "pushed_sha256": "something-else"}}
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, state, "live", pulled=pulled_versions(p),
                     memory_text=pulled_texts(p))
    assert "/areas/training.md" in {x.path for x in m.entries}


def test_a_trailing_newline_alone_is_not_a_change(tmp_path):
    from um.bridge.prepare import pulled_texts, pulled_versions
    p, cats = profile(tmp_path)
    _pulled(p, "/areas/training.md", "v1", content=(p / "areas" / "training.md").read_text().rstrip("\n"))
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled=pulled_versions(p),
                     memory_text=pulled_texts(p))
    assert "/areas/training.md" not in {x.path for x in m.entries}


def test_a_path_already_deleted_is_not_proposed_again(tmp_path):
    from um.bridge.prepare import deleted_paths
    p, cats = profile(tmp_path)
    assert deleted_paths(p) == set()
    (p / ".um").mkdir(exist_ok=True)
    (p / ".um" / "deleted.txt").write_text("/areas/nyc.md\n")
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled={"/areas/nyc.md": "v1"},
                     approved_deletions={"/areas/nyc.md"}, deleted=deleted_paths(p))
    assert m.deletions == [] and all(h["path"] != "/areas/nyc.md" for h in m.held)


def test_each_text_sent_is_kept_as_the_next_merge_base(tmp_path):
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live")
    for e in m.entries:
        assert (p / ".um" / "pushed" / f"{e.sha256}.md").read_text() == (p / "outbox" / e.path.lstrip("/")).read_text()


def test_a_number_pattern_in_frontmatter_or_a_heading_never_reaches_the_outbox(tmp_path):
    p, cats = profile(tmp_path)
    (p / "areas" / "training.md").write_text("---\nname: t\ndescription: card 4111 1111 1111 1111\n---\n"
                                             "# SSN 123-45-6789\n- Squat 405 lb\n")
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live")
    text = (p / "outbox" / "areas" / "training.md").read_text()
    assert "4111" not in text and "6789" not in text and "Squat" in text and "name: t" in text


def test_similarity_to_a_memory_line_never_pushes_a_new_never_category_line(tmp_path):
    p, cats = profile(tmp_path)
    new = "- [stated] Takes sertraline daily (2026-11-17)"
    (p / "areas" / "training.md").write_text(f"# Training\n\n- Squat 405 lb\n{new}\n")
    cats[h(new)] = "medical"
    memory = {"/areas/training.md": ["- Squat 405 lb", "- [stated] Takes vitamin D daily (2026-10-01)"]}
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", in_memory=memory)
    assert "sertraline" not in (p / "outbox" / "areas" / "training.md").read_text()


def test_tags_and_dates_do_not_make_unrelated_lines_look_like_revisions():
    from um.bridge.prepare import _in_memory
    assert not _in_memory("- [stated] Savings are 40k (2026-11-17)", ["- [stated] Squat is 405 (2026-11-10)"], set())
    assert _in_memory("- [stated] Squat is 415 lb (2026-11-17)", ["- [stated] Squat is 405 lb (2026-11-10)"], set())


def test_a_never_category_line_memory_already_holds_exactly_is_kept(tmp_path):
    p, cats = profile(tmp_path)
    line = "- [stated] Takes vitamin D daily"
    (p / "areas" / "training.md").write_text(f"# Training\n\n- Squat 405 lb\n{line}\n")
    cats[h(line)] = "medical"
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", in_memory={"/areas/training.md": [line]})
    assert "vitamin D" in (p / "outbox" / "areas" / "training.md").read_text()


def test_lines_the_bridge_last_pushed_count_as_lines_memory_holds(tmp_path):
    from um.bridge.adopt import record_pushed
    from um.bridge.prepare import memory_lines
    p, cats = profile(tmp_path)
    line = "- [stated] Revised money line"
    (p / "areas" / "training.md").write_text(f"# Training\n\n- Squat 405 lb\n{line}\n")
    cats[h(line)] = "financial-figures"
    sha = record_pushed(p, f"# Training\n\n- Squat 405 lb\n{line}\n")
    state = {"/areas/training.md": {"version": "v2", "pushed_sha256": sha}}
    assert line in memory_lines(p, state)["/areas/training.md"]
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", in_memory=memory_lines(p, state))
    assert line in (p / "outbox" / "areas" / "training.md").read_text()


def test_a_deletion_the_last_live_run_made_is_recorded_and_not_proposed_again(tmp_path):
    from um.bridge.prepare import deleted_paths, record_done_deletions
    p, cats = profile(tmp_path)
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {"/areas/nyc.md": {"version": "v1"}}, "live",
                     approved_deletions={"/areas/nyc.md"})
    assert m.deletions
    (p / "bridge-log.jsonl").write_text(json.dumps({"run_at": "2999-01-01T00:00:00Z", "mode": "live",
                                                    "deleted": 1, "error": None}) + "\n")
    record_done_deletions(p, state={})
    assert deleted_paths(p) == {"/areas/nyc.md"}
    m = build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {}, "live", pulled={"/areas/nyc.md": "v1"},
                     approved_deletions={"/areas/nyc.md"}, deleted=deleted_paths(p))
    assert m.deletions == []


def test_a_deletion_that_conflicted_is_not_recorded(tmp_path):
    from um.bridge.prepare import deleted_paths, record_done_deletions
    p, cats = profile(tmp_path)
    build_outbox(p, p / "outbox", DEFAULT_POLICY, cats, {"/areas/nyc.md": {"version": "v1"}}, "live",
                 approved_deletions={"/areas/nyc.md"})
    (p / "bridge-log.jsonl").write_text(json.dumps({"run_at": "2999-01-01T00:00:00Z", "mode": "live",
                                                    "deleted": 0, "error": None}) + "\n")
    (p / "inbox" / "conflicts").mkdir(parents=True)
    (p / "inbox" / "conflicts" / "areas-nyc-md.json").write_text("{}")
    record_done_deletions(p, state={"/areas/nyc.md": {"version": "v1"}})
    assert deleted_paths(p) == set()
