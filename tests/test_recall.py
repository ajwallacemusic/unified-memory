import re

import pytest

from um.recall import CANARIES, SURFACES, miss_rate


def test_canary_set_shape():
    assert len(CANARIES) == 10 and len({c.id for c in CANARIES}) == 10 and len({c.token for c in CANARIES}) == 10
    by_surface = {s: sum(1 for c in CANARIES if c.stated_on == s) for s in SURFACES}
    assert by_surface == {"chat": 3, "task": 2, "code:unified-memory": 3, "code:home": 2}
    for c in CANARIES:
        assert re.fullmatch(r"[A-Z]+-\d\d", c.token) and c.token in c.statement and c.token not in c.question
        assert "test fact" in c.statement


def test_miss_rate_overall_and_per_pair():
    rows = [
        {"canary_id": "c1", "stated_on": "chat", "probed_on": "task", "hit": True},
        {"canary_id": "c1", "stated_on": "chat", "probed_on": "code:home", "hit": False},
        {"canary_id": "c2", "stated_on": "task", "probed_on": "chat", "hit": False},
        {"canary_id": "c2", "stated_on": "task", "probed_on": "code:home", "hit": False},
    ]
    r = miss_rate(rows)
    assert r["overall"] == 0.75 and r["probes"] == 4
    assert r["pairs"][("chat", "task")] == 0.0 and r["pairs"][("chat", "code:home")] == 1.0
    assert r["pairs"][("task", "chat")] == 1.0


def test_a_probe_on_the_stating_surface_is_rejected():
    with pytest.raises(ValueError):
        miss_rate([{"canary_id": "c1", "stated_on": "chat", "probed_on": "chat", "hit": True}])


def test_no_rows_is_an_error_not_a_zero():
    with pytest.raises(ValueError):
        miss_rate([])


def test_a_failed_probe_call_is_an_error_not_a_miss(tmp_path):
    import json
    from types import SimpleNamespace as NS

    from um.recall.code_surface import ProbeError, ask

    def fake(result):
        return lambda cmd, **kw: result

    with pytest.raises(ProbeError):
        ask("q", tmp_path, [], runner=fake(NS(returncode=1, stdout="", stderr="limit reached")))
    with pytest.raises(ProbeError):
        ask("q", tmp_path, [], runner=fake(NS(returncode=0, stdout=json.dumps({"is_error": True, "result": "usage limit"}), stderr="")))
    ok = NS(returncode=0, stdout=json.dumps({"is_error": False, "result": "1. UNKNOWN"}), stderr="")
    assert ask("q", tmp_path, [], runner=fake(ok)) == "1. UNKNOWN"
