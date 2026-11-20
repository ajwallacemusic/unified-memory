import json
import os
import subprocess
import time
from dataclasses import replace

import pytest

from conftest import CountingFakeLLM
from um.cli import main
from um.erase import remaining
from um.search.index import Index
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


# --- `um.cli erase` reaches the conversation-search index (Plan 5 Task 9) -------------------------------------------

def _cli_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UM_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.setenv("UM_SEARCH_INDEX", str(tmp_path / "share" / "search.sqlite"))
    p = tmp_path / "claude-profile"
    p.mkdir()
    (p / "profile.md").write_text("# Profile\n\n- Coach is Quillon Varga\n- Lives in Aldermoor\n")
    for a in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "bootstrap"]):
        subprocess.run(["git", "-C", str(p), *a], check=True, capture_output=True)
    projects = tmp_path / "projects"
    t = projects / "-work-proj" / "s-coach.jsonl"
    t.parent.mkdir(parents=True)
    recs = [{"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:01:00Z", "sessionId": "s-coach",
             "cwd": "/work/proj", "entrypoint": "cli", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "my coach Quillon Varga says squat deeper"}},
            {"type": "assistant", "uuid": "a1", "timestamp": "2026-01-01T00:01:30Z", "sessionId": "s-coach",
             "cwd": "/work/proj", "entrypoint": "cli",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "depth cues for squat"}]}}]
    t.write_text("".join(json.dumps(r) + "\n" for r in recs))
    old = time.time() - 3600
    os.utime(t, (old, old))
    return p, projects, tmp_path / "share" / "search.sqlite"


def _cli_erase(p, projects, tmp_path, value):
    main(["erase", "--profile", str(p), "--value", value, "--raw-root", str(tmp_path / "nothing"),
          "--projects", str(projects), "--desktop", str(tmp_path / "no-desktop"), "--yes"])


def _index_cmd(projects, tmp_path):
    main(["search", "index", "--projects", str(projects), "--desktop", str(tmp_path / "no-desktop")])


def test_erase_also_erases_index(tmp_path, monkeypatch, capsys):
    p, projects, ix = _cli_profile(tmp_path, monkeypatch)
    _index_cmd(projects, tmp_path)
    i = Index(ix)
    assert i.search("Quillon", limit=5)
    i.close()
    capsys.readouterr()
    _cli_erase(p, projects, tmp_path, "Quillon Varga")
    out = capsys.readouterr().out
    assert "search index: removed 1 chunks in 1 sessions" in out
    assert remaining(p, ["Quillon Varga"]) == []
    i = Index(ix)
    assert i.search("Quillon", limit=5) == [] and i.search("squat", limit=5) == []
    i.close()
    assert b"quillon" not in ix.read_bytes().lower()


def test_erase_without_an_index_records_the_guard_for_a_later_build(tmp_path, monkeypatch, capsys):
    p, projects, ix = _cli_profile(tmp_path, monkeypatch)
    _cli_erase(p, projects, tmp_path, "Quillon Varga")
    out = capsys.readouterr().out
    assert "search index: none yet" in out
    assert remaining(p, ["Quillon Varga"]) == []
    assert ix.exists() and b"quillon" not in ix.read_bytes().lower()
    i = Index(ix)
    assert i.stats()["chunks"] == {}            # no catch-up ran: only the guard was recorded
    i.close()
    _index_cmd(projects, tmp_path)
    i = Index(ix)
    assert i.search("Quillon", limit=5) == [] and i.search("squat", limit=5) == []
    i.close()


def test_erase_index_failure_is_not_silent(tmp_path, monkeypatch, capsys):
    import um.search.forget as forget
    p, projects, ix = _cli_profile(tmp_path, monkeypatch)
    _index_cmd(projects, tmp_path)

    def boom(index, values):
        raise RuntimeError("disk")
    monkeypatch.setattr(forget, "erase_from_index", boom)
    with pytest.raises(SystemExit) as e:
        _cli_erase(p, projects, tmp_path, "Quillon Varga")
    assert "search index NOT erased: RuntimeError" in str(e.value.code)
    assert remaining(p, ["Quillon Varga"]) == []      # the profile erase was committed first
