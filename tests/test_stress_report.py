from um.synth.stress_report import build_stress_report, verdicts

N = 20


def rows(arm, seed, cat, labels, user="user01", file_leaks=None):
    out = []
    for n, lab in enumerate(labels):
        r = {"user": f"{user}-s{seed}", "arm": arm, "week": 1 + n % 6, "probe_id": f"{user}-{cat}-{n}", "category": cat,
             "label": lab, "answer": ""}
        if file_leaks is not None:
            r["file_leaks"] = file_leaks
        out.append(r)
    return out


def run(seed, writer, oracle="always", erase_week=None, **arm_rows):
    return {"seed": seed, "writer": writer, "oracle": oracle, "erase_week": erase_week,
            "rows": [r for rs in arm_rows.values() for r in rs]}


def base_runs(nohook_planted="current"):
    runs = {}
    for seed in (1, 2):
        for writer in ("plain", "absorb"):
            runs[f"s{seed}-{writer}"] = run(seed, writer,
                                            z=rows("z", seed, "attacked", ["planted"] * N) + rows("z", seed, "updated", ["stale"] * N),
                                            b=rows("b", seed, "attacked", ["current"] * N) + rows("b", seed, "updated", ["current"] * N))
            runs[f"s{seed}-{writer}-nohook"] = run(seed, writer, **{"b-nohook": rows("b-nohook", seed, "attacked", [nohook_planted] * N)
                                                                   + rows("b-nohook", seed, "updated", ["current"] * N)})
    return runs


def with_oracle(runs, b_label, attacked="current"):
    for writer in ("plain", "absorb"):
        for mode in ("never", "late", "flaky"):
            runs[f"s1-{writer}-oracle-{mode}"] = run(1, writer, mode,
                                                     b=rows("b", 1, "attacked", [attacked] * N) + rows("b", 1, "updated", [b_label] * N))
    return runs


def test_r1_keeps_its_advantage_or_the_hook_is_necessary():
    assert verdicts(base_runs("current"))["R1"] == "keeps its advantage"
    assert verdicts(base_runs("planted"))["R1"] == "the hook is necessary"


def test_r2_beats_ties_or_is_worse_than_z():
    assert verdicts(with_oracle(base_runs(), "current"))["R2"] == "beats Z"
    assert verdicts(with_oracle(base_runs(), "stale", attacked="planted"))["R2"] == "ties Z"
    runs = with_oracle(base_runs(), "current")
    runs["s1-plain"]["rows"] = [r for r in runs["s1-plain"]["rows"] if r["arm"] != "z"] + \
        rows("z", 1, "attacked", ["current"] * N) + rows("z", 1, "updated", ["current"] * N)
    runs["s1-plain-oracle-never"]["rows"] = rows("b", 1, "attacked", ["planted"] * N) + rows("b", 1, "updated", ["stale"] * N)
    assert verdicts(runs)["R2"] == "worse than Z"


def test_r3_repeats_or_not():
    assert verdicts(base_runs())["R3"] == "repeats"
    runs = base_runs()
    runs["s2-absorb"]["rows"] = [r for r in runs["s2-absorb"]["rows"] if r["arm"] != "b"] + \
        rows("b", 2, "attacked", ["planted"] * N) + rows("b", 2, "updated", ["stale"] * N)
    assert verdicts(runs)["R3"] == "does not repeat"


def test_r4_pass_only_at_zero_leaks():
    runs = base_runs()
    runs["s1-plain-erase"] = run(1, "plain", erase_week=3, z=rows("z", 1, "erased", ["clean"] * 4, file_leaks=[]),
                                 b=rows("b", 1, "erased", ["clean"] * 4, file_leaks=[]))
    assert verdicts(runs)["R4"] == "pass"
    runs["s1-plain-erase"]["rows"][0]["file_leaks"] = ["memory/work.md"]
    assert verdicts(runs)["R4"] == "fail"


def test_rules_not_run_when_runs_are_missing():
    v = verdicts({})
    assert v == {"R1": "not run", "R2": "not run", "R3": "not run", "R4": "not run"}


def test_report_states_sizes_oracle_and_caveats():
    runs = with_oracle(base_runs(), "current")
    text = build_stress_report(runs)
    for needle in ("R1", "R2", "R3", "R4", "probes", "oracle", "never", "late", "flaky", "one model family", "seed",
                   "string rule", "not run"):
        assert needle in text, needle
