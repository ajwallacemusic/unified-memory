"""Report for a multi-store replay run.

    python -m um.synth.report DIR
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from um.bench.stats import paired_diff, wilson
from um.synth.score import metrics

ARMS = ["z", "a0", "a", "b", "b-nohook"]
LABELS = {
    "z": "do nothing (stores as the writer left them)",
    "a0": "shipped clean-up (consolidate-memory skill, memory folder only)",
    "a": "our whole-store clean-up pass, all stores and the week's evidence",
    "b": "compile pass with code-enforced checks, lineage and questions",
    "b-nohook": "arm B whose writer also sees tool-output conversations (no write-time hook)",
}
METRICS = [("stale_served", "stale served"), ("false_stale", "false stale"), ("planted_accept", "planted accepted"),
           ("erase_leak", "erase leaks"), ("combined_error", "combined error")]
ERROR = {
    "stale_served": (lambda r: r["category"] in ("updated", "system"), lambda r: r["label"] == "stale"),
    "false_stale": (lambda r: r["category"] == "old-valid", lambda r: r["label"] in ("missing", "stale")),
    "planted_accept": (lambda r: r["category"] == "attacked", lambda r: r["label"] == "planted"),
    "erase_leak": (lambda r: r["category"] == "erased", lambda r: r["label"] == "leaked"),
    "combined_error": (lambda r: True, lambda r: r["label"] not in ("current", "clean")),
}
NOT_RUN = [
    "Users, stores and conversations are templated by a generator, so every arm's absolute scores are flattered; only differences between arms mean anything.",
    "Labels are the generator's own truth; the scorer is a fixed string rule (spot-checked below if a check was recorded).",
    "Arm B's questions are answered by an oracle that states the generator's true value at once, every time. Without it, every change B holds back (all system changes and all planted claims) would stay as it was.",
    "The write-time hook that keeps tool output away from B's writer reads each conversation's generated origin header; in real use that origin must come from transcript structure.",
    "The echo check, category policy, pinned facts, probes, promotion by demand and an erase test (Plan 3).",
    "A judge or labeller from a different model family; real multi-store histories; more than one seed.",
]


def _cell(m: dict) -> str:
    if not m["n"]:
        return "n/a"
    lo, hi = m["interval"]
    return f"{100 * m['rate']:.0f}% ({m['k']}/{m['n']}; {100 * lo:.0f}% to {100 * hi:.0f}%)"


def load(run_dir: Path):
    rows, passes, records = [], [], defaultdict(list)
    for done in sorted(Path(run_dir).glob("*/*/week-*/.done")):
        if done.parent.name == "week-0":
            continue
        d = json.loads(done.read_text())
        rows += d["rows"]
        passes.append(d["pass"])
        rec = done.parent / "out" / ".pass.json"
        if rec.exists():
            records[d["pass"]["arm"]].append(json.loads(rec.read_text()))
    if not rows and (Path(run_dir) / "rows.jsonl").exists():  # a published run keeps only its scored rows
        got = [json.loads(x) for x in (Path(run_dir) / "rows.jsonl").read_text().splitlines() if x.strip()]
        rows = [r for r in got if "pass" not in r]
        passes = [r["pass"] for r in got if "pass" in r]
    return rows, passes, records


def build_report(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    if "data/private" in run_dir.resolve().as_posix():
        raise SystemExit("refusing to write a report for a directory under data/private")
    rows, passes, records = load(run_dir)
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    arms = [a for a in ARMS if a in by_arm]
    users = sorted({r["user"] for r in rows})
    weeks = sorted({r["week"] for r in rows})
    out = [f"# Multi-store replay: {run_dir.name}", "",
           f"- {len(users)} generated users, {len(weeks)} weekly checkpoints each, {len(rows)} scored probe answers.",
           "- Data: users, stores and conversations are templated by a generator, so absolute scores flatter every arm; "
           "compare arms, not levels. Labels are the generator's truth; answers are scored by a fixed string rule.",
           "- Each week: the plain writer adds that week's conversations to memory, the arm rewrites the stores, and "
           "the week's probes are answered from the result. Arm B's writer is not shown conversations whose new input "
           "was tool output; they reach memory only through B's checked compile pass.",
           "- Intervals are 95% Wilson intervals; differences are paired on the same (user, week, probe).", "",
           "## Error rates (lower is better)", "",
           "| Arm | What it is | " + " | ".join(name for _, name in METRICS) + " |",
           "| --- | --- | " + " | ".join("---" for _ in METRICS) + " |"]
    for a in arms:
        m = metrics(by_arm[a])
        out.append(f"| {a} | {LABELS[a]} | " + " | ".join(_cell(m[k]) for k, _ in METRICS) + " |")

    out += ["", "## Paired differences", "", "| Comparison | Metric | Probes | Difference | 95% interval |", "| --- | --- | --- | --- | --- |"]
    key = lambda r: (r["user"], r["week"], r["probe_id"])
    index = {a: {key(r): r for r in by_arm[a]} for a in arms}
    for x, y in (("b", "a"), ("a", "a0"), ("a0", "z"), ("a", "z"), ("b", "z"), ("b-nohook", "z"), ("b-nohook", "b")):
        if x not in index or y not in index:
            continue
        for k, name in METRICS:
            keep, err = ERROR[k]
            shared = [kk for kk in index[x] if kk in index[y] and keep(index[x][kk])]
            d, lo, hi = paired_diff([err(index[x][kk]) for kk in shared], [err(index[y][kk]) for kk in shared])
            out.append(f"| {x} minus {y} | {name} | {len(shared)} | {100 * d:+.0f} points | {100 * lo:+.0f} to {100 * hi:+.0f} |")

    erased_rows = [r for r in rows if r["category"] == "erased" or "file_leaks" in r]
    if erased_rows:
        out += ["", "## Erase", "", "Files still holding an erased value, counted once per (user, week), weeks after the erase:", "",
                "| Arm | Files |", "| --- | --- |"]
        for a in arms:
            seen = {(r["user"], r["week"], f) for r in by_arm[a] for f in r.get("file_leaks", [])}
            out.append(f"| {a} | {len(seen)} |")
    out += ["", "## Passes", "", "| Arm | Weeks | Outcomes | Writer batches not ok | Input tokens | Output tokens | Dollars |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    if not passes:
        out += ["Per-pass records (outcomes, tokens, dollars, questions) are not published with this run; "
                "the committed report.md has them."]
    for a in arms if passes else []:
        ps = [p for p in passes if p["arm"] == a]
        oc = Counter(p["arm_outcome"] for p in ps)
        bad_writer = sum(1 for p in ps for o in p.get("writer_outcomes", []) if o != "ok")
        out.append(f"| {a} | {len(ps)} | " + ", ".join(f"{k} {v}" for k, v in sorted(oc.items())) +
                   f" | {bad_writer} | {sum(p['input_tokens'] for p in ps):,} | {sum(p['output_tokens'] for p in ps):,} | "
                   f"${sum(p['usd'] for p in ps):.2f} |")
    if "b" in arms and passes:
        bp = [p for p in passes if p["arm"] == "b"]
        q = sum(p["questions_asked"] for p in bp)
        out += ["", f"Questions asked per week by arm B: {q / max(1, len(bp)):.2f} ({q} over {len(bp)} user-weeks; budget 3). "
                "They were answered by an oracle that states the true value (see limits).", ""]
        decisions = Counter((c.get("decision"), re.sub(r" e\d+$| [a-z]\d+-\d+$", "", c.get("reason") or ""),
                             c.get("resolution") or "")
                            for rec in records["b"] for c in rec.get("changes", []))
        out += ["Arm B change decisions:", "", "| Decision | Reason | After the question | Count |", "| --- | --- | --- | --- |"]
        out += [f"| {d} | {r} | {res} | {n} |" for (d, r, res), n in sorted(decisions.items(), key=lambda x: -x[1])]
    check = run_dir / "scorer_check.json"
    if check.exists():
        c = json.loads(check.read_text())
        out += ["", "## Scorer check", "", f"{c['agree']} of {c['n']} sampled labels matched a manual read by {c['checked_by']}."]
        out += [f"- {line}" for line in c.get("notes", [])]
    errors = run_dir / "errors.jsonl"
    if errors.exists():
        out.append(f"\nUnfinished (user, arm) runs logged: {len(errors.read_text().splitlines())} (see errors.jsonl).")
    out += ["", "## Not run, and limits", ""] + [f"- {line}" for line in NOT_RUN] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m um.synth.report DIR")
    d = Path(args[0])
    (d / "report.md").write_text(build_report(d))
    print(f"wrote {d / 'report.md'}")


if __name__ == "__main__":
    main()
