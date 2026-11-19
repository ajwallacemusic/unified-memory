import json
import time

from um.gate import UsageGate


def sample(tmp_path, fh, sd, age_s):
    p = tmp_path / "u.json"
    t = int((time.time() - age_s) * 1000)
    p.write_text(json.dumps({"version": 2, "samples": [
        {"t": t - 5_000_000, "org": "x", "u": {"fh": 1, "sd": 1, "xu": 0}},
        {"t": t, "org": "x", "u": {"fh": fh, "sd": sd, "xu": 0}},
    ]}))
    return p


def test_gate_opens_only_when_fresh_and_under_ceiling(tmp_path):
    assert UsageGate(70, 900, sample(tmp_path, 49, 16, 60)).is_open()
    assert not UsageGate(70, 900, sample(tmp_path, 70, 16, 60)).is_open()
    assert not UsageGate(70, 900, sample(tmp_path, 10, 71, 60)).is_open()
    assert not UsageGate(70, 900, sample(tmp_path, 10, 10, 3600)).is_open()
    assert not UsageGate(70, 900, tmp_path / "missing.json").is_open()


def test_gate_is_closed_when_the_file_is_unreadable(tmp_path):
    p = tmp_path / "u.json"
    p.write_text("{not json")
    assert not UsageGate(70, 900, p).is_open()
    p.write_text(json.dumps({"samples": []}))
    assert not UsageGate(70, 900, p).is_open()


def test_latest_reports_the_newest_sample(tmp_path):
    latest = UsageGate(70, 900, sample(tmp_path, 49, 16, 60)).latest()
    assert (latest["fh"], latest["sd"]) == (49, 16) and latest["age_s"] < 120
