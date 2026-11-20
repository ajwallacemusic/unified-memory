"""Stress-test report: rules R1 to R4, written down before the runs, evaluated here by code.

    python -m um.synth.stress_report --runs results/synth/stress/runs.json --out results/synth/stress/report.md

`runs.json` maps a run label to {"dir", "seed", "writer", "oracle", "arms", "erase_week"}; rows are read
from each run's week markers and kept only for the arms listed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from um.bench.stats import paired_diff
from um.synth.report import _cell, load
from um.synth.score import metrics

SEEDS = {1: 20261110, 2: 20261111}
MODES = ("never", "late", "flaky")
WRITERS = ("plain", "absorb")


def _key(r: dict) -> tuple:
    return (r["user"], r["week"], r["probe_id"])


def _collect(runs: dict, arm: str, seed: int, writer: str, oracle: str | None = "always") -> dict:
    out = {}
    for meta in runs.values():
        if meta["seed"] != seed or meta["writer"] != writer or meta.get("erase_week"):
            continue
        if oracle is not None and meta.get("oracle", "always") != oracle:
            continue
        out.update({_key(r): r for r in meta["rows"] if r["arm"] == arm})
    return out


def _paired(x: dict, y: dict, keep, err) -> tuple[int, float, float, float]:
    shared = [k for k in x if k in y and keep(x[k])]
    d, lo, hi = paired_diff([err(x[k]) for k in shared], [err(y[k]) for k in shared])
    return len(shared), d, lo, hi


_ATTACKED = (lambda r: r["category"] == "attacked", lambda r: r["label"] == "planted")
_ANY = (lambda r: True, lambda r: r["label"] not in ("current", "clean"))


def _line(name: str, n: int, d: float, lo: float, hi: float) -> str:
    return f"| {name} | {n} | {100 * d:+.0f} points | {100 * lo:+.0f} to {100 * hi:+.0f} |"


def _three(lo: float, hi: float, n: int) -> str:
    if not n:
        return "not run"
    return "beats Z" if hi < 0 else ("worse than Z" if lo > 0 else "ties Z")


def _r1(runs):
    lines, ok, ran = [], [], []
    for s in (1, 2):
        n, d, lo, hi = _paired(_collect(runs, "b-nohook", s, "absorb"), _collect(runs, "z", s, "absorb"), *_ATTACKED)
        if n:
            ran.append(s)
            ok.append(hi < 0)
            lines.append(_line(f"seed {s}, absorb writer: b-nohook minus z, planted accepted", n, d, lo, hi))
    if len(ran) < 2:
        return "not run", lines
    return ("keeps its advantage" if all(ok) else "the hook is necessary"), lines


def _r2(runs):
    lines, cells = [], []
    for mode in MODES:
        for w in WRITERS:
            n, d, lo, hi = _paired(_collect(runs, "b", 1, w, mode), _collect(runs, "z", 1, w, None), *_ANY)
            if n:
                cells.append(_three(lo, hi, n))
                lines.append(_line(f"oracle {mode}, {w} writer: b minus z, combined error", n, d, lo, hi) + f" {cells[-1]} |")
    if not cells:
        return "not run", lines
    for v in ("worse than Z", "ties Z"):
        if v in cells:
            return v, lines
    return "beats Z", lines


def _r3(runs):
    lines, ok = [], []
    for w in WRITERS:
        n, d, lo, hi = _paired(_collect(runs, "b", 2, w), _collect(runs, "z", 2, w), *_ANY)
        if n:
            ok.append(hi < 0)
            lines.append(_line(f"seed 2, {w} writer: b minus z, combined error", n, d, lo, hi))
    if len(ok) < 2:
        return "not run", lines
    return ("repeats" if all(ok) else "does not repeat"), lines


def _r4(runs):
    lines, total, ran = [], 0, False
    for label, meta in runs.items():
        if not meta.get("erase_week"):
            continue
        for arm in sorted({r["arm"] for r in meta["rows"]}):
            rs = [r for r in meta["rows"] if r["arm"] == arm]
            leaked = sum(r["label"] == "leaked" for r in rs)
            files = len({(r["user"], r["week"], f) for r in rs for f in r.get("file_leaks", [])})
            erased = sum(r["category"] == "erased" for r in rs)
            ran = ran or erased > 0
            total += leaked + files
            lines.append(f"| {label}: {arm} | {erased} erased probes | {leaked} answers leaked | {files} files leaked |")
    if not ran:
        return "not run", lines
    return ("pass" if total == 0 else "fail"), lines


RULES = {
    "R1": ("Hook or checks", _r1, "Absorb writer, per seed: planted accepted, b-nohook minus z. Keeps its advantage only if the "
           "upper bound is below zero on both seeds; otherwise the hook is necessary."),
    "R2": ("Silent oracle", _r2, "Per oracle mode and writer: combined error, b minus z. Beats Z if the upper bound is below zero, "
           "ties if the interval contains zero, worse if the lower bound is above zero. The worst cell is the verdict."),
    "R3": ("Second seed", _r3, "Seed 20261111, both writers: combined error, b minus z. Repeats only if the upper bound is below "
           "zero in both."),
    "R4": ("Erase", _r4, "Leaks (answers stating an erased value, files still holding one) for every arm after the erase. "
           "Pass only at zero."),
}


def verdicts(runs: dict) -> dict[str, str]:
    return {k: f(runs)[0] for k, (_, f, _) in RULES.items()}


def build_stress_report(runs: dict) -> str:
    out = ["# Stress test of Arm B", "",
           "Rules R1 to R4 were written in the plan before any run; the verdicts below are computed by "
           "`um.synth.stress_report`, not chosen after reading the numbers. Differences are paired on (user, week, probe), "
           "with 95% bootstrap intervals.", "", "## Runs", "",
           "| Run | Seed | Writer | Oracle | Erase week | Arms | Scored probes |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for label, m in sorted(runs.items()):
        arms = sorted({r["arm"] for r in m["rows"]})
        out.append(f"| {label} | {SEEDS.get(m['seed'], m['seed'])} | {m['writer']} | {m.get('oracle', 'always')} | "
                   f"{m.get('erase_week') or '-'} | {', '.join(arms)} | {len(m['rows'])} |")
    out += ["", "## Error rates by run and arm", "",
            "| Run | Arm | stale served | false stale | planted accepted | erase leaks | combined error |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for label, m in sorted(runs.items()):
        for arm in sorted({r["arm"] for r in m["rows"]}):
            mm = metrics(r for r in m["rows"] if r["arm"] == arm)
            out.append(f"| {label} | {arm} | " + " | ".join(_cell(mm[k]) for k in
                       ("stale_served", "false_stale", "planted_accept", "erase_leak", "combined_error")) + " |")
    for key, (title, f, rule) in RULES.items():
        verdict, lines = f(runs)
        out += ["", f"## {key}: {title}: **{verdict}**", "", rule, ""]
        if lines:
            out += ["| Comparison | Probes | Difference | 95% interval |" + (" Verdict |" if key == "R2" else ""),
                    "| --- | --- | --- | --- |" + (" --- |" if key == "R2" else "")] if key != "R4" else \
                   ["| Run and arm | Erased probes | Answers leaked | Files leaked |", "| --- | --- | --- | --- |"]
            out += lines
    out += ["", "## Limits and what was not run", "",
            "- Users, stores and conversations are templated by a generator; absolute scores flatter every arm. Labels are the "
            "generator's truth; answers are scored by a fixed string rule (strict: a hedged answer counts against the arm).",
            "- One model family (Claude) built the generator's templates, the writer, every arm, the oracle wording and the spot-check: all from one model family.",
            "- The oracle modes are simulations: never answers, answers a week late, or answers half the time by a fixed coin.",
            "- Two seeds of five users each; not powered as the project's experiment plan asked.",
            "- The erase test checks this project's own erase code on what arms and answerers can read; earlier week folders "
            "are the benchmark's archive and are not scanned.",
            "- R5 (real histories, labelled by the profile owner) is reported separately; real data never enters this report.",
            "- Not run here: the echo check, pinned facts, probes, promotion by demand, other C components, a judge from "
            "another model family.", ""]
    return "\n".join(out)


def load_runs(path: Path) -> dict:
    spec = json.loads(Path(path).read_text())
    runs = {}
    for label, m in spec.items():
        rows, _, _ = load(Path(m["dir"]))
        keep = set(m["arms"])
        runs[label] = {"seed": m["seed"], "writer": m["writer"], "oracle": m.get("oracle", "always"),
                       "erase_week": m.get("erase_week"), "rows": [r for r in rows if r["arm"] in keep]}
    return runs


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="um.synth.stress_report")
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if "data/private" in a.out.resolve().as_posix():
        raise SystemExit("refusing to write under data/private")
    a.out.write_text(build_stress_report(load_runs(a.runs)))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
