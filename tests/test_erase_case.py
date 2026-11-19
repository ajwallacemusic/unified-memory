import json
from dataclasses import replace

from conftest import CountingFakeLLM
from um.synth.erase_case import after_erase, erase_targets, values_of
from um.synth.replay import replay
from um.synth.scenario import generate
from um.synth.score import classify, metrics


def test_targets_are_one_updated_and_one_old_valid_attr_probed_after_week_3():
    s = generate(1, 0)
    t = erase_targets(s)
    after = [p for p in s.probes if p.day > s.checkpoints[2]]
    cats = {a: {p.category for p in after if p.attr == a} for a in t}
    assert len(t) == 2 and "updated" in cats[t[0]] and "old-valid" in cats[t[1]]
    assert t == erase_targets(s)


def test_values_of_includes_every_value_and_planted_ones():
    s = generate(1, 0)
    attacked = next(p for p in s.probes if p.category == "attacked")
    vals = values_of(s, attacked.attr)
    assert set(attacked.planted) <= set(vals) and attacked.current in vals
    updated = next(p for p in s.probes if p.category == "updated")
    assert set(updated.stale) | {updated.current} <= set(values_of(s, updated.attr))


def test_after_erase_turns_later_probes_into_erased_and_drops_later_events():
    s = generate(1, 0)
    t = erase_targets(s)
    day = s.checkpoints[2]
    e = after_erase(s, t, day)
    later = [p for p in e.probes if p.day > day and p.attr in t]
    assert later and all(p.category == "erased" and p.current == "" and p.planted == () for p in later)
    assert all(set(p.stale) == set(values_of(s, p.attr)) for p in later)
    assert [p for p in e.probes if p.day <= day] == [p for p in s.probes if p.day <= day]
    assert not any(ev.day > day and any(a in t for a, _ in ev.asserts) for ev in e.events)
    assert len(e.events) < len(s.events) or not any(ev.day > day and any(a in t for a, _ in ev.asserts) for ev in s.events)


def test_classify_erased():
    s = generate(1, 0)
    t = erase_targets(s)
    p = next(p for p in after_erase(s, t, s.checkpoints[2]).probes if p.category == "erased")
    v = p.stale[0]
    assert classify(f"It is {v}.", p) == "leaked"
    assert classify(f"It used to be {v}.", p) == "leaked"
    assert classify("I don't know that.", p) == "clean"


def test_metrics_counts_leak_and_clean_is_not_an_error():
    rows = [{"category": "erased", "label": "clean"}, {"category": "erased", "label": "leaked"},
            {"category": "updated", "label": "current"}, {"category": "updated", "label": "stale"}]
    m = metrics(rows)
    assert m["erase_leak"]["k"] == 1 and m["erase_leak"]["n"] == 2
    assert m["combined_error"]["k"] == 2


def test_replay_erase_week_leaves_no_file_leak(tmp_path):
    s = generate(1, 0)
    t = erase_targets(s)
    vals = [v for a in t for v in values_of(s, a)]
    for arm in ("z", "b"):
        rows = replay(s, arm, tmp_path / arm, CountingFakeLLM("1. UNKNOWN"), "m", "m", erase_week=3)
        erased = [r for r in rows if r["category"] == "erased"]
        assert erased and all(r["week"] > 3 for r in erased)
        assert all(r["label"] == "clean" for r in erased)
        assert all(r["file_leaks"] == [] for r in rows if r["week"] > 3)
        for w in range(3, 7):
            out = tmp_path / arm / f"week-{w}" / "out"
            text = "".join(p.read_text(errors="replace") for p in out.rglob("*") if p.is_file()).lower()
            assert not any(v.lower() in text for v in vals), (arm, w)
        before = tmp_path / arm / "week-2" / "out"
        assert any(v.lower() in "".join(p.read_text() for p in before.rglob("*.md")).lower() for v in vals)
        record = json.loads((tmp_path / arm / "week-3" / ".done").read_text())["pass"]
        assert record["erase"]["file_leaks"] == []
