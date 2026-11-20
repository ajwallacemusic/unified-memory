"""Write report.md for one benchmark run directory.

    python -m um.bench.report DIR
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from um.bench.stats import paired_diff, wilson

ARM_LABELS = {
    "z": "do nothing (store as written)",
    "a0": "shipped clean-up (consolidate-memory skill)",
    "a": "our whole-store clean-up pass",
    "full": "reference: full history in the prompt",
    "files": "reference: raw session files with search",
}
ALL_ARMS = ["z", "a0", "a", "full", "files"]
NOT_RUN = [
    "Arm B and every Arm C component (later work).",
    "The custom multi-store benchmark with planted claims (later work).",
    "STALE, Bemula, Memora, MemoryAgentBench and store-level checks.",
    "A second labeller or a judge from a different model family.",
    "Sonnet 5.5 or any model other than the one named above.",
]


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _acc_cell(rows: list[dict]) -> str:
    ok = [r for r in rows if r["outcome"] == "ok"]
    if not ok:
        return "n/a (0 answered)"
    k = sum(bool(r["correct"]) for r in ok)
    lo, hi = wilson(k, len(ok))
    return f"{_pct(k / len(ok))} ({k}/{len(ok)}; {_pct(lo)} to {_pct(hi)})"


def build_report(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    if "data/private" in run_dir.resolve().as_posix():
        raise SystemExit("refusing to write a report for a directory under data/private")
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines() if line.strip()]
    seen = Counter((r["qid"], r["arm"]) for r in rows)
    dupes = sorted(pair for pair, n in seen.items() if n > 1)
    if dupes:
        raise SystemExit(f"duplicate rows for {len(dupes)} (question, arm) pairs, e.g. {dupes[0]}; refusing to report")
    meta = json.loads((run_dir / "run_meta.json").read_text()) if (run_dir / "run_meta.json").exists() else {}
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    arms = [a for a in ALL_ARMS if a in by_arm]
    qtypes = sorted({r["qtype"] for r in rows})
    qids = sorted({r["qid"] for r in rows})
    model = meta.get("model", "unknown")

    out = [f"# LongMemEval-S sample: {run_dir.name}", ""]
    out += [
        f"- Sample: {len(qids)} questions, fixed seed {meta.get('seed', '?')}, by type: "
        + ", ".join(f"{t} {sum(1 for q in {r['qid'] for r in rows if r['qtype'] == t})}" for t in qtypes) + ".",
        f"- Answering model and judge: `{model}`. Effort is set to medium on both backends. The judge is from the "
        "same model family as the systems it grades.",
        "- Labels: LongMemEval's own answer key; grading uses LongMemEval's published per-type prompts.",
        "- Intervals are 95% Wilson intervals. Differences are paired on the same questions with a bootstrap interval.",
        "- Accuracy is over answered questions; refusals, cut-off and empty replies are counted separately below.",
        "",
        "## Accuracy",
        "",
        "| Arm | What it is | Overall | " + " | ".join(qtypes) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in qtypes) + " |",
    ]
    for a in arms:
        cells = [_acc_cell([r for r in by_arm[a] if r["qtype"] == t]) for t in qtypes]
        out.append(f"| {a} | {ARM_LABELS[a]} | {_acc_cell(by_arm[a])} | " + " | ".join(cells) + " |")

    out += ["", "## Difference from doing nothing (arm z)", ""]
    if "z" in by_arm:
        z = {r["qid"]: r for r in by_arm["z"] if r["outcome"] == "ok"}
        out += ["| Arm | Questions compared | Accuracy minus z | 95% interval |", "| --- | --- | --- | --- |"]
        for a in arms:
            if a == "z":
                continue
            pairs = [(bool(r["correct"]), bool(z[r["qid"]]["correct"])) for r in by_arm[a]
                     if r["outcome"] == "ok" and r["qid"] in z]
            d, lo, hi = paired_diff([p[0] for p in pairs], [p[1] for p in pairs])
            out.append(f"| {a} | {len(pairs)} | {100 * d:+.0f} points | {100 * lo:+.0f} to {100 * hi:+.0f} |")
    else:
        out.append("Arm z was not run, so there is nothing to compare against.")

    out += ["", "## Replies that were not answers", "",
            "| Arm | Rows | refusal | max_tokens | empty | max_turns | judge failed | arm pass failed |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for a in arms:
        c = Counter(r["outcome"] for r in by_arm[a])
        failed = sum(1 for r in by_arm[a] if r.get("arm_outcome") not in (None, "ok"))
        out.append(f"| {a} | {len(by_arm[a])} | {c['refusal']} | {c['max_tokens']} | {c['empty']} | {c['max_turns']} | "
                   f"{c['judge_failed']} | {failed} |")

    out += ["", "## Tokens, cost and backend", "", "| Arm | Input tokens | Output tokens | API dollars | Rows by backend |",
            "| --- | --- | --- | --- | --- |"]
    for a in arms:
        backends = Counter(r.get("backend", "api") for r in by_arm[a])
        out.append(f"| {a} | {sum(r['input_tokens'] for r in by_arm[a]):,} | {sum(r['output_tokens'] for r in by_arm[a]):,} | "
                   f"${sum(r.get('usd', 0.0) for r in by_arm[a]):.2f} | " + ", ".join(f"{b} {n}" for b, n in sorted(backends.items())) + " |")
    writer_path = run_dir / "writer.jsonl"
    if writer_path.exists():
        w = [json.loads(line) for line in writer_path.read_text().splitlines() if line.strip()]
        bad = sum(1 for r in w for o in r["outcomes"] if o != "ok")
        out.append(f"\nShared memory writer (once per question, used by z, a0 and a): {sum(r['input_tokens'] for r in w):,} input "
                   f"tokens, {sum(r['output_tokens'] for r in w):,} output tokens, ${sum(r.get('usd', 0.0) for r in w):.2f}; "
                   f"{bad} writer batches did not finish cleanly.")
    for a in arms:
        split = defaultdict(list)
        for r in by_arm[a]:
            split[r.get("backend", "api")].append(r)
        if len(split) > 1:
            out.append(f"\nArm {a} spans both backends: " + "; ".join(f"{b}: {_acc_cell(rs)}" for b, rs in sorted(split.items())) + ".")
    judged = [r for r in rows if r.get("judge_backend")]
    if judged:
        jb = Counter(r["judge_backend"] for r in judged)
        out.append("\nJudge calls by backend: " + ", ".join(f"{b} {n}" for b, n in sorted(jb.items())) + ".")
    for n, inv in enumerate(meta.get("invocations", []), 1):
        parts = [f"arms {','.join(inv.get('arms', []))}"]
        if "api_usd_this_run" in inv:
            parts.append(f"API cost ${inv['api_usd_this_run']:.2f}")
        out.append(f"\nInvocation {n}: " + "; ".join(parts) + ".")
    errors_path = run_dir / "errors.jsonl"
    if errors_path.exists():
        out.append(f"\nErrors logged during the run: {len(errors_path.read_text().splitlines())} (see errors.jsonl).")

    check_path = run_dir / "judge_check.json"
    if check_path.exists():
        c = json.loads(check_path.read_text())
        out += ["", "## Judge check", "",
                f"{c['agree']} of {c['n']} sampled verdicts matched a manual read by {c['checked_by']}."]
        out += [f"- {line}" for line in c.get("notes", [])]
    if meta.get("notes"):
        out += ["", "## Notes on this run", ""] + [f"- {line}" for line in meta["notes"]]

    out += ["", "## Not run", ""] + [f"- {line}" for line in NOT_RUN] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m um.bench.report DIR")
    run_dir = Path(args[0])
    text = build_report(run_dir)
    (run_dir / "report.md").write_text(text)
    print(f"wrote {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
