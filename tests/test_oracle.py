from datetime import timedelta

from um.synth.oracle import Oracle
from um.synth.replay import oracle as plan2_oracle
from um.synth.scenario import PHRASE, generate, truth


def _setup():
    s = generate(1, 0)
    attrs = sorted({f.attr for f in s.facts})
    return s, attrs


def test_never_answers_nothing():
    s, attrs = _setup()
    o = Oracle(s, "never")
    assert all(o.ask({"attr": a}, s.checkpoints[2]) is None for a in attrs)
    assert o.due(s.checkpoints[-1]) == []


def test_always_matches_plan_2_wording():
    s, attrs = _setup()
    day = s.checkpoints[3]
    o = Oracle(s, "always")
    for q in ({"attr": attrs[0]}, {"attr": PHRASE[attrs[1]]}, {"attr": "", "text": f"Is your {PHRASE[attrs[2]]} the same?"}):
        assert o.ask(q, day) == plan2_oracle(s, day)(q)
    assert o.ask({"attr": attrs[0]}, day) == f"My {PHRASE[attrs[0]]} is {truth(s, attrs[0], day)}."
    assert o.ask({"attr": "favourite colour", "text": "?"}, day) is None


def test_late_answers_a_week_later_with_that_days_value_once():
    s, attrs = _setup()
    changed = next(f.attr for f in s.facts if f.cause == "change")
    d = s.checkpoints[0]
    o = Oracle(s, "late")
    assert o.ask({"attr": changed}, d) is None
    assert o.due(d + timedelta(days=6)) == []
    got = o.due(d + timedelta(days=7))
    assert len(got) == 1
    aid, text = got[0]
    assert text == f"My {PHRASE[changed]} is {truth(s, changed, d + timedelta(days=7))}."
    assert aid.startswith("late")
    assert o.due(d + timedelta(days=14)) == []


def test_late_ignores_questions_it_cannot_place():
    s, _ = _setup()
    o = Oracle(s, "late")
    assert o.ask({"attr": "favourite colour"}, s.checkpoints[0]) is None
    assert o.due(s.checkpoints[-1]) == []


def test_flaky_is_deterministic_and_respects_p():
    s, attrs = _setup()
    days = list(s.checkpoints)
    qs = [({"attr": a}, days[n % len(days)]) for n, a in enumerate(attrs[:20])]
    assert all(Oracle(s, "flaky", p=0.0).ask(q, d) is None for q, d in qs)
    assert all(Oracle(s, "flaky", p=1.0).ask(q, d) is not None for q, d in qs)
    x, y = Oracle(s, "flaky", seed=7), Oracle(s, "flaky", seed=7)
    assert [x.ask(q, d) for q, d in qs] == [y.ask(q, d) for q, d in qs]
    answered = sum(x.ask(q, d) is not None for q, d in qs)
    assert 0 < answered < len(qs)


def test_state_and_restore_keep_the_late_queue():
    s, attrs = _setup()
    d = s.checkpoints[0]
    o = Oracle(s, "late")
    o.ask({"attr": attrs[0]}, d)
    o.ask({"attr": attrs[1]}, d)
    o.due(d)
    fresh = Oracle(s, "late")
    fresh.restore(o.state())
    later = d + timedelta(days=7)
    assert fresh.due(later) == o.due(later)


def test_unknown_mode_is_an_error():
    s, _ = _setup()
    try:
        Oracle(s, "sometimes")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
