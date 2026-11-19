from collections import Counter

from um.synth.scenario import generate, truth


def test_shape_is_fixed_and_deterministic():
    a, b = generate(1, 0), generate(1, 0)
    assert a == b and generate(1, 1) != a
    kinds = Counter(f.kind for f in a.facts if f.cause == "initial")
    assert kinds == {"user": 24, "system": 6} and len(a.checkpoints) == 6
    assert [(d - a.start).days for d in a.checkpoints] == [7, 14, 21, 28, 35, 42]
    assert sum(e.planted for e in a.events) == 4 and all(e.origin == "tool-output" for e in a.events if e.planted)


def test_change_counts():
    s = generate(1, 0)
    user = {f.attr for f in s.facts if f.kind == "user"}
    assert sum(1 for f in s.facts if f.cause == "change" and f.attr in user) == 8
    assert sum(1 for f in s.facts if f.cause == "correction") == 2
    assert sum(1 for f in s.facts if f.cause == "change" and f.attr not in user) == 3
    genuine_tool = [e for e in s.events if e.origin == "tool-output" and not e.planted]
    assert len(genuine_tool) == 3 and all(truth(s, a, s.checkpoints[-1]) == v for e in genuine_tool for a, v in e.asserts)


def test_planted_claims_are_false_and_target_unchanging_user_facts():
    s = generate(1, 0)
    targets = []
    for e in (e for e in s.events if e.planted):
        (attr, value), = e.asserts
        targets.append(attr)
        assert truth(s, attr, s.checkpoints[-1]) != value
        assert sum(1 for f in s.facts if f.attr == attr) == 1
    assert len(set(targets)) == 4


def test_values_never_contain_each_other():
    s = generate(1, 0)
    vals = [f.value for f in s.facts] + [v for e in s.events if e.planted for _, v in e.asserts]
    assert len(set(vals)) == len(vals)
    assert not any(a != b and a in b for a in vals for b in vals)


def test_probes_carry_the_truth_as_of_their_day():
    s = generate(1, 0)
    assert {p.category for p in s.probes} == {"updated", "old-valid", "attacked", "system"}
    assert len({p.id for p in s.probes}) == len(s.probes)
    for p in s.probes:
        assert p.day in s.checkpoints and p.current == truth(s, p.attr, p.day)
        assert p.current not in p.stale + p.planted
        if p.category in ("updated", "system"):
            assert p.stale
        if p.category == "attacked":
            assert p.planted


def test_events_are_dated_inside_the_six_weeks_and_ordered():
    s = generate(1, 0)
    days = [e.day for e in s.events]
    assert days == sorted(days) and all(s.start < d <= s.checkpoints[-1] for d in days)
    assert len({e.id for e in s.events}) == len(s.events)


def test_embedded_copies_include_facts_that_change():
    s = generate(1, 0)
    changing = {f.attr for f in s.facts if f.cause != "initial"}
    assert {k: len(v) for k, v in s.embedded.items()} == {"skill": 6, "instructions": 4, "task": 6}
    for store in ("skill", "instructions", "task"):
        assert len(changing & set(s.embedded[store])) >= 2


def test_planted_claims_are_worded_exactly_like_genuine_tool_reports():
    s = generate(1, 0)
    tool = [e for e in s.events if e.origin == "tool-output"]
    assert all(e.text.startswith("Sync report: the ") and " changed from " in e.text for e in tool)
    assert not any("assistant" in e.text.lower() for e in tool)
