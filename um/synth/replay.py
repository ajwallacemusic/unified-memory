"""Replay a generated user week by week through one arm, and score the answers mechanically.

Each week: the week's evidence is written; the shared plain writer adds notes from that week's
conversations to the memory store; the arm turns the stores into a new version; the week's probe
questions are answered from that version. The next week starts from it. No file, prompt or
question dated after a week's checkpoint exists while that week runs.

Arm B is the one exception in how the writer is fed: its harness holds back conversations whose new
input was tool output, so those reach memory only through B's checked compile pass. That is the
"enforced in a hook" part of Arm B in the design.

    python -m um.synth.replay --users 5 --seed 20261110 --arms z,a0,a,b --out DIR --cap 24
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from um.arms import ARMS
from um.bench.run import Meter
from um.llm import LLM, outcome_of
from um.prompts import load_prompt
from um.questions import QuestionBudget
from um.synth.render import as_sessions, render_evidence, render_static
from um.erase import erase_values, remaining
from um.synth.erase_case import after_erase, erase_targets, values_of
from um.synth.oracle import MODES, Oracle
from um.synth.scenario import Probe, Scenario, generate
from um.synth.score import classify
from um.tools import Toolbox
from um.writer import write_memory

_NUM = re.compile(r"^\s*(\d+)[.)]\s*(.*)$")


def _visible_copy(root: Path) -> Path:
    """A temporary copy of the stores without hidden records, so answers come from store content only."""
    tmp = Path(tempfile.mkdtemp(prefix="um-ans-"))
    for p in Path(root).rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not any(x.startswith(".") for x in rel.parts):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, tmp / rel)
    return tmp


def answer_probes(probes: list[Probe], root: Path, llm: LLM, model: str, today: date) -> dict[str, str]:
    view = _visible_copy(root)
    try:
        system = load_prompt("answer_many.md").replace("{today}", today.isoformat())
        user = "\n".join(f"{n}. {p.question}" for n, p in enumerate(probes, 1))
        reply = llm.run_tools(model=model, system=system, user=user, tools=Toolbox(view, writable=False),
                              max_turns=20, max_tokens=8_000, label="answer:probes")
    finally:
        shutil.rmtree(view, ignore_errors=True)
    answers: dict[int, str] = {}
    current = None
    for line in reply.text.splitlines():
        m = _NUM.match(line)
        if m:
            current = int(m.group(1))
            answers[current] = m.group(2).strip()
        elif current is not None and line.strip():
            answers[current] = (answers[current] + " " + line.strip()).strip()
    return {p.id: answers.get(n, "") for n, p in enumerate(probes, 1)}


def oracle(scn: Scenario, day: date):
    """Plan 2's oracle: answers at once with the value true on `day`."""
    o = Oracle(scn, "always")
    return lambda question: o.ask(question, day)


def _copy(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def replay(scn: Scenario, arm: str, out: Path, llm: LLM, arm_model: str, small_model: str,
           writer_prompt: str = "writer.md", hook: bool | None = None,
           oracle_mode: str = "always", erase_week: int | None = None) -> list[dict]:
    """`arm` is a key of ARMS, or "b-nohook": Arm B whose writer also sees tool-output conversations."""
    out = Path(out)
    base_arm = arm.partition("-")[0]
    if hook is None:
        hook = arm == "b"
    checked = base_arm == "b"
    base = out / "week-0"
    if not (base / ".done").exists():
        if base.exists():
            shutil.rmtree(base)
        render_static(scn, base / "out")
        (base / ".done").write_text("{}")
    budget = QuestionBudget(3)
    person = Oracle(scn, oracle_mode)
    targets = erase_targets(scn) if erase_week else []
    erased_values = [v for a in targets for v in values_of(scn, a)]
    rows: list[dict] = []
    prev = base / "out"
    since = scn.start
    for w, day in enumerate(scn.checkpoints, 1):
        wdir = out / f"week-{w}"
        marker = wdir / ".done"
        if marker.exists():
            done = json.loads(marker.read_text())
            rows += done["rows"]
            for _ in range(done["pass"]["questions_asked"]):
                budget.allow(day.isoformat())
            person.restore(done["pass"].get("oracle_queue", []))
            if erase_week == w:
                scn = after_erase(scn, targets, day)
            prev, since = wdir / "out", day
            continue
        if wdir.exists():
            shutil.rmtree(wdir)
        evidence = wdir / "evidence"
        paths = render_evidence(scn, since, day, evidence)
        if hook:
            paths = [p for p in paths if p.read_text().splitlines()[0] != "origin: tool-output"]
        meter = Meter(llm)
        _copy(prev, wdir / "in")
        if checked:
            for aid, text in person.due(day):
                (wdir / "in" / ".answers").mkdir(exist_ok=True)
                (wdir / "in" / ".answers" / f"{aid}.md").write_text(f"origin: user-said\ndate: {day.isoformat()}\n\n{text}\n")
        writer_outcomes = (write_memory(as_sessions(paths), wdir / "in" / "memory", meter, small_model, prompt=writer_prompt)
                           if paths else [])
        n_allowed_before = budget.total()
        arm_outcome = ARMS[base_arm].apply(wdir / "in", wdir / "out", meter, arm_model, day.isoformat(),
                                           evidence_dir=evidence, ask=(lambda q, d=day: person.ask(q, d)) if checked else None,
                                           budget=budget if checked else None)
        questions = budget.total() - n_allowed_before
        probes = [p for p in scn.probes if p.day == day]
        answers = answer_probes(probes, wdir / "out", meter, small_model, day) if probes else {}
        week_rows = [{"user": scn.user, "arm": arm, "week": w, "probe_id": p.id, "category": p.category,
                      "label": classify(answers.get(p.id, ""), p), "answer": answers.get(p.id, "")} for p in probes]
        if erase_week and w > erase_week:
            leaks = remaining(wdir / "out", erased_values)
            for r in week_rows:
                r["file_leaks"] = leaks
        record = {"user": scn.user, "arm": arm, "week": w, "writer_outcomes": writer_outcomes, "arm_outcome": arm_outcome,
                  "questions_asked": questions, "oracle_queue": person.state(), "input_tokens": meter.input_tokens, "output_tokens": meter.output_tokens,
                  "usd": meter.usd}
        if erase_week == w:
            rep = erase_values(wdir / "out", erased_values, [evidence])
            record["erase"] = {"attrs_erased": len(targets), "lines_removed": len(rep.lines_removed),
                               "lineage_rows": rep.lineage_rows, "pass_entries": rep.pass_entries,
                               "answers_deleted": len(rep.answers_deleted), "evidence_deleted": len(rep.evidence_deleted),
                               "file_leaks": remaining(wdir / "out", erased_values)}
            scn = after_erase(scn, targets, day)
        marker.write_text(json.dumps({"rows": week_rows, "pass": record}))
        rows += week_rows
        prev, since = wdir / "out", day
    return rows


def main(argv: list[str] | None = None) -> None:
    from um.budget import Budget
    from um.gate import UsageGate
    from um.llm import AnthropicLLM
    from um.llm_sub import ClaudeCodeLLM, HybridLLM

    ap = argparse.ArgumentParser(prog="um.synth.replay")
    ap.add_argument("--users", type=int, default=5)
    ap.add_argument("--first-user", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--arms", default="z,a0,a,b")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cap", type=float, required=True)
    ap.add_argument("--arm-model", default="claude-sonnet-5-5")
    ap.add_argument("--small-model", default="claude-haiku-5-5")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--sub-ceiling", type=float, default=70.0)
    ap.add_argument("--writer", choices=("plain", "absorb"), default="plain",
                    help="plain: the writer records what the person said; absorb: it also records what tools report")
    ap.add_argument("--erase-week", type=int, default=None, help="erase two facts after this week's answers")
    ap.add_argument("--oracle", choices=MODES, default="always", help="how the person answers Arm B's questions")
    a = ap.parse_args(argv)

    budget = Budget(a.cap, Path("results/spend.jsonl"))
    llm = HybridLLM(AnthropicLLM(budget), ClaudeCodeLLM(), UsageGate(a.sub_ceiling, 900, Path.home() / ".claude/usage-now.json"))
    a.out.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    jobs = [(u, arm) for u in range(a.first_user, a.first_user + a.users) for arm in a.arms.split(",")]

    def work(job):
        u, arm = job
        scn = generate(a.seed, u)
        try:
            rows = replay(scn, arm, a.out / scn.user / arm, llm, a.arm_model, a.small_model,
                          writer_prompt="writer.md" if a.writer == "plain" else "writer_absorb.md", oracle_mode=a.oracle, erase_week=a.erase_week)
        except Exception as e:   # left unfinished; a rerun continues from the last finished week
            with lock, (a.out / "errors.jsonl").open("a") as f:
                f.write(json.dumps({"user": scn.user, "arm": arm, "error": repr(e)[:500]}) + "\n")
            return
        with lock:
            print(f"done {scn.user} {arm}: {len(rows)} rows", flush=True)

    with ThreadPoolExecutor(a.workers) as pool:
        list(pool.map(work, jobs))
    print(f"API ledger total ${budget.spent():.2f} of ${a.cap:.2f}")


if __name__ == "__main__":
    main()
