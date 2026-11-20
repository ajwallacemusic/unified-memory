from um.bench.meta import PRIVATE_FIELDS, public_invocation


def test_public_invocation_drops_plan_usage_and_ledger_and_keeps_run_cost():
    inv = {"model": "m", "seed": 1, "cap_usd": 5.0, "sub_ceiling_pct": 70.0, "usage_before": {"fh": 1},
           "usage_after": {"fh": 2}, "gate_open_at_start": True, "api_usd_total": 9.0,
           "api_usd_ledger_before": 8.0, "argv": ["--n", "3", "--api-cap", "35", "--workers", "2"]}
    out = public_invocation(inv, spent_before=8.0, spent_after=9.25)
    assert not PRIVATE_FIELDS & out.keys()
    assert out["api_usd_this_run"] == 1.25 and out["model"] == "m" and out["seed"] == 1
    assert out["argv"] == ["--n", "3", "--workers", "2"]


def test_absolute_paths_in_argv_are_recorded_relative_to_the_repo_or_dropped_to_their_name():
    from pathlib import Path
    from um.bench.meta import REPO, public_invocation
    home = str(Path.home())
    inv = public_invocation({"argv": ["--prefeval-root", str(REPO / "data/public/prefeval"),
                                      f"--out={home}/elsewhere/runs", "--n", "100"]})
    assert inv["argv"] == ["--prefeval-root", "data/public/prefeval", "--out=<home>/elsewhere/runs", "--n", "100"]
