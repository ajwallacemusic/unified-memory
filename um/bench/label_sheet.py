"""Human label-check sheet: a fixed-seed sample of recall questions and implicit-task verdicts for hand review.

Run `python -m um.bench.label_sheet` to write bench/recall/label-check.md, and `--score` after filling it in.
"""
import argparse
import json
import random
import re
from pathlib import Path

VERDICT = "Your verdict: [ ] agree  [ ] disagree  — note:"
ROOT = Path(__file__).resolve().parents[2]


def _jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def _answer_lines(profile: Path, rel, terms: list[str]) -> list[str]:
    out = []
    for r in ([rel] if isinstance(rel, str) else rel or []):
        f = profile / r
        if r and f.is_file():
            out += [l for l in f.read_text().splitlines() if any(t.lower() in l.lower() for t in terms)]
    return out


def _files(rel) -> str:
    return rel if isinstance(rel, str) else ", ".join(rel or [])


def build_sheet(questions, profile, implicit, results, n=15, seed=20261119) -> str:
    rng = random.Random(seed)
    qs = [q for q in _jsonl(questions) if q.get("split") == "test"]
    qs = rng.sample(qs, min(n, len(qs)))
    tasks = {t["id"]: t for t in _jsonl(implicit)}
    allrows = _jsonl(results)
    rows = rng.sample(allrows, min(n, len(allrows)))
    out = ["# Label check", "",
           "Labels were written by Claude models; implicit-task verdicts by a Haiku judge. Mark one box per item.",
           "Part A: is the question fair and are the answer terms right? "
           "Part B: does the verdict (hit = the answer acted on the stored fact) match your reading?", "",
           "## Part A: recall questions", ""]
    k = 0
    for q in qs:
        k += 1
        out += [f"### {k}. {q['id']}", "", f"Question: {q['question']}",
                f"Answer terms: {', '.join(q['answer_terms'])}", f"File: {_files(q.get('file'))}", "", "Profile lines:"]
        lines = _answer_lines(Path(profile), q.get("file", ""), q["answer_terms"])
        out += [f"    {l}" for l in lines] or ["    (not found by term match)"]
        out += ["", VERDICT, ""]
    out += ["## Part B: implicit-task verdicts", ""]
    for r in rows:
        k += 1
        t = tasks.get(r["id"], {})
        ans = r.get("answer") or ""
        ans = ans[:1200] + (" [...truncated]" if len(ans) > 1200 else "")
        out += [f"### {k}. {r['id']} (condition: {r.get('condition')})", "", "Task prompt:", "", "````",
                t.get("prompt", "(missing)"), "````", "", f"Check question: {t.get('check', '(missing)')}",
                f"Stored fact: {t.get('fact', '(none)')}", "", "Model answer:", "", "````", ans, "````", "",
                f"Haiku verdict: {'hit' if r.get('hit') else 'miss'}", "", VERDICT, ""]
    return "\n".join(out)


def score(md: str) -> dict:
    part, res = None, {k: {"agree": 0, "disagree": 0, "blank": 0} for k in ("recall", "implicit")}
    for line in md.splitlines():
        if line.startswith("## Part A"):
            part = "recall"
        elif line.startswith("## Part B"):
            part = "implicit"
        elif line.startswith("Your verdict:") and part:
            a = re.search(r"\[[xX]\]\s*agree", line)
            d = re.search(r"\[[xX]\]\s*disagree", line)
            res[part]["agree" if a and not d else "disagree" if d and not a else "blank"] += 1
    return res


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--score", action="store_true")
    a = p.parse_args(argv)
    b = ROOT / "bench/recall"
    if a.score:
        r = score((b / "label-check.md").read_text())
        (b / "label-check-result.json").write_text(json.dumps(r, indent=2) + "\n")
        print(json.dumps(r))
    else:
        md = build_sheet(b / "questions.jsonl", b / "profile", b / "implicit.jsonl",
                         ROOT / "results/recall-bench/2026-11-19-implicit.jsonl")
        (b / "label-check.md").write_text(md + "\n")


if __name__ == "__main__":
    main()
