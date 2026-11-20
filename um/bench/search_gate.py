"""The conversation-search evidence gate (spec 2026-11-19, "Evidence gate").

    python -m um.bench.search_gate --bench tune --out results/search-gate/2026-11-tune
    python -m um.bench.search_gate --bench lme --n 10 --out DIR --api-cap X --params PARAMS.json
    python -m um.bench.search_gate --bench prefeval --n 100 --out DIR --api-cap X --params PARAMS.json
    python -m um.bench.search_gate --bench report --out DIR

LongMemEval-S: the fixed 100-question sample (seed 20261110), each question with its own scratch index of its own
history, answered under `LME_CONDITIONS`. `--n` takes the first n of that sample (ordered by id), so a pilot's rows
are reused by the full run. PrefEval: the same 100 items as the 2026-11-19 run, under `PREF_CONDITIONS`. The
development split (every LongMemEval-S question outside the 100) is used only by `tune`, which calls no model.

One JSON line per (item, condition) goes to OUT/results.jsonl; a pair already there is not run again. Indexes,
profiles and any benchmark text stay under OUT/stores/, which git ignores; rows hold ids, answers, verdicts and
counts. Compiles go to the subscription only; answers, tool loops and judges go to the API under `--api-cap`.
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from um.bench import longmemeval as lm
from um.bench.answer import answer_full_context
from um.bench.meta import public_invocation
from um.bench.public import lme
from um.bench.public import pipeline as pl
from um.bench.public.pipeline import Session
from um.bench.stats import paired_diff, wilson
from um.budget import BudgetExceeded
from um.llm import EFFORT, outcome_of
from um.search.index import Index
from um.search.model import Exchange, SessionDoc, chunks_of
from um.search.tools import TOOL_SPECS, ToolArgError, call_tool

LME_CONDITIONS = ("profile", "search", "profile+search", "full", "search-1shot")
PREF_CONDITIONS = ("profile-full", "profile-full+search")
SEARCH_CONDITIONS = ("search", "profile+search", "search-1shot", "profile-full+search")
PROFILE_CONDITIONS = ("profile", "profile+search", "profile-full", "profile-full+search")
MAX_TOOL_TURNS = 8
SURFACE = "bench"
DEFAULT_PARAMS = {"chunk_chars": 2000, "lead_chars": 300, "per_session": 2, "half_life_days": None}
DEFAULT_GRID = {"chunk_chars": [1000, 2000, 4000], "lead_chars": [0, 300], "per_session": [1, 2, 3],
                "half_life_days": [None, 90]}
SEARCH_KEYS = ("per_session", "half_life_days")
FULL_REUSE = Path("results/longmemeval/2026-11-10-full-api-check/results.jsonl")
PREF_REUSE = Path("results/public-bench/2026-11-19-prefeval-100/stores")
ANSWER_MODEL = JUDGE_MODEL = "claude-haiku-5-5"
COMPILE_MODEL = "claude-sonnet-5-5"
CAP_FLOOR = 100_000   # change cap lifted, as in the PrefEval run


# ---------------------------------------------------------------- index and toolbox

def _exchanges(s: Session) -> tuple[Exchange, ...]:
    """One exchange per user turn with the assistant turns after it; assistant turns before the first user turn
    form an exchange of their own with no user text."""
    groups: list[list] = []
    for role, text in s.turns:
        if role == "user" or not groups:
            groups.append([text if role == "user" else "", []])
            if role != "user":
                groups[-1][1].append(text)
        else:
            groups[-1][1].append(text)
    return tuple(Exchange(f"t{n}", s.date, u, "\n\n".join(a)) for n, (u, a) in enumerate(groups))


def build_index(sessions: list[Session], path: Path, *, chunk_chars: int = 2000, lead_chars: int = 300) -> Index:
    index = Index(Path(path))
    for s in sessions:
        doc = SessionDoc(SURFACE, s.id, "", None, None, s.date, s.date, _exchanges(s))
        index.upsert_session(doc, chunks_of(doc, chunk_chars, lead_chars), replace=True)
    return index


class SearchToolbox:
    """The contract `um.llm.run_tools` expects, over one scratch index."""

    def __init__(self, index: Index, *, params: dict | None = None, now: str | None = None):
        self.index = index
        p = {**DEFAULT_PARAMS, **(params or {})}
        self.params = {k: p[k] for k in SEARCH_KEYS}
        if now:
            self.params["now"] = now
        self.retrieved: set[str] = set()
        self.calls = 0

    def specs(self) -> list[dict]:
        out = []
        for spec in TOOL_SPECS:
            s = {k: v for k, v in spec.items() if k != "inputSchema"}
            s["input_schema"] = spec["inputSchema"]
            out.append(s)
        return out

    def call(self, name: str, args: dict) -> str:
        self.calls += 1
        try:
            res = call_tool(self.index, name, args, params=self.params)
        except ToolArgError as e:
            return f"ERROR: {e}"
        self.retrieved |= {r["session_id"] for r in res["structured"]["results"]}
        return res["text"]


def session_recall(index: Index, question: str, answer_ids: set[str], k: int, **search_kw) -> bool:
    """True when at least one answer session is among the sessions of the top k chunks."""
    return any(h.native_id in answer_ids for h in index.search(question, limit=k, **search_kw))


def _now(item: lm.Item) -> str:
    return lm.parse_date(item.question_date).isoformat()


def _search_kw(params: dict, item: lm.Item | None = None) -> dict:
    kw = {k: params.get(k, DEFAULT_PARAMS[k]) for k in SEARCH_KEYS}
    if item is not None:
        kw["now"] = _now(item)
    return kw


def _item_index(sessions: list[Session], wd: Path, params: dict) -> Index:
    """The item's scratch index for these chunk settings, built once; a build cut short is redone."""
    cc, lc = params.get("chunk_chars", 2000), params.get("lead_chars", 300)
    path, marker = wd / f"search-{cc}-{lc}.sqlite", wd / f"search-{cc}-{lc}.done"
    if not marker.exists():
        path.unlink(missing_ok=True)
        build_index(sessions, path, chunk_chars=cc, lead_chars=lc).close()
        marker.write_text("done\n")
    return Index(path)


# ---------------------------------------------------------------- splits and tuning

def dev_items(path: Path, *, counts: dict[str, int] = lm.SAMPLE_COUNTS, seed: int = lm.SEED) -> list[lm.Item]:
    items = lm.load(Path(path))
    test = {i.qid for i in lm.sample(items, counts, seed)}
    return [i for i in items if i.qid not in test]


def _setting_key(s: dict) -> tuple:
    return tuple(s[k] for k in DEFAULT_PARAMS)


def tune(path: Path, out: Path, grid: dict, *, counts: dict[str, int] = lm.SAMPLE_COUNTS,
         seed: int = lm.SEED) -> dict:
    """Answer-session recall@5 and @10 for every grid setting on the development split; no model is called.
    Writes OUT/tune.json and OUT/params.json and returns the chosen parameters: best recall@5, then recall@10,
    then the defaults; the defaults are kept unless the best beats them by more than 1 point of recall@5."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    grid = {k: list(grid.get(k, [v])) for k, v in DEFAULT_PARAMS.items()}
    items = [i for i in dev_items(path, counts=counts, seed=seed) if i.answer_session_ids]
    hits = {}   # setting key -> [hit@5 count, hit@10 count]
    scratch = out / "stores" / "tune"
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.time()
    for n, item in enumerate(items, 1):
        sessions = lme.sessions(item)
        answer = set(item.answer_session_ids)
        for cc, lc in itertools.product(grid["chunk_chars"], grid["lead_chars"]):
            ipath = scratch / "item.sqlite"
            ipath.unlink(missing_ok=True)
            index = build_index(sessions, ipath, chunk_chars=cc, lead_chars=lc)
            try:
                for ps, hl in itertools.product(grid["per_session"], grid["half_life_days"]):
                    kw = {"per_session": ps, "half_life_days": hl, "now": _now(item)}
                    tally = hits.setdefault((cc, lc, ps, hl), [0, 0])
                    tally[0] += session_recall(index, item.question, answer, 5, **kw)
                    tally[1] += session_recall(index, item.question, answer, 10, **kw)
            finally:
                index.close()
                ipath.unlink(missing_ok=True)
        if n % 25 == 0:
            print(f"tune: {n}/{len(items)} items, {time.time() - started:.0f}s", file=sys.stderr)
    shutil.rmtree(out / "stores", ignore_errors=True)
    total = len(items)
    settings = [{**dict(zip(DEFAULT_PARAMS, key)), "n": total,
                 "recall@5": round(h5 / total, 4) if total else 0.0,
                 "recall@10": round(h10 / total, 4) if total else 0.0} for key, (h5, h10) in hits.items()]
    default = _setting_key(DEFAULT_PARAMS)
    best = max(settings, key=lambda s: (s["recall@5"], s["recall@10"], _setting_key(s) == default))
    base = next((s for s in settings if _setting_key(s) == default), None)
    chosen = base if base is not None and best["recall@5"] - base["recall@5"] <= 0.01 else best
    params = {k: chosen[k] for k in DEFAULT_PARAMS}
    (out / "tune.json").write_text(json.dumps({"items": total, "grid": grid, "settings": settings,
                                               "default": dict(DEFAULT_PARAMS), "chosen": params}, indent=1))
    (out / "params.json").write_text(json.dumps(params, indent=1) + "\n")
    return params


# ---------------------------------------------------------------- shared run plumbing

def _done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    text = path.read_text()
    if text and not text.endswith("\n"):   # a torn last line from an interrupted write
        text = text[: text.rfind("\n") + 1]
        path.write_text(text)
    return {(r["qid"], r["condition"]) for r in map(json.loads, text.splitlines()) if r}


def _append(path: Path, row: dict, lock: threading.Lock) -> None:
    with lock, path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _graded_row(item_id: str, qtype: str, condition: str, reply, grade, tally: pl.Tally, box) -> dict:
    """Grade a reply (the judge sees only non-empty answers) and build its row."""
    outcome = outcome_of(reply)
    correct = False
    extra: dict = {}
    if reply.text.strip():
        verdict = grade(reply.text, tally)
        correct = verdict.get("correct")
        extra = {k: v for k, v in verdict.items() if k != "correct"}
        if correct is None:
            outcome = "judge_failed"   # never graded; not a wrong answer
    judge_usd = sum(r.usd for r in tally.replies)
    row = {"qid": item_id, "qtype": qtype, "condition": condition, "correct": correct, "outcome": outcome,
           "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens, "usd": reply.usd + judge_usd,
           "backend": reply.backend, "tool_calls": box.calls if box is not None else 0, "answer": reply.text,
           **extra}
    return row


def _run_items(items, work, workers: int) -> None:
    if workers <= 1:
        for it in items:
            work(it)
    else:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(work, items))


# ---------------------------------------------------------------- LongMemEval

def prompt_at_commit(results: Path) -> bytes | None:
    """`um/prompts/answer.md` as it was at the commit that added `results`; None when git cannot say."""
    try:
        sha = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", str(results)],
                             capture_output=True, text=True, check=True).stdout.split()
        if not sha:
            return None
        return subprocess.run(["git", "show", f"{sha[-1]}:um/prompts/answer.md"], capture_output=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def _reusable_full(full_reuse: Path | None, reuse_prompt: bytes | None, answer_model: str) -> dict[str, dict]:
    """Rows of the earlier API `full` run, keyed by qid, when its answer prompt and model match today's."""
    if full_reuse is None or not Path(full_reuse).exists():
        return {}
    current = (Path(lm.__file__).parent.parent / "prompts" / "answer.md").read_bytes()
    if (reuse_prompt if reuse_prompt is not None else prompt_at_commit(full_reuse)) != current:
        return {}
    meta = Path(full_reuse).parent / "run_meta.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        efforts = {i.get("effort") for i in m.get("invocations", [])} - {None}
        if m.get("model", answer_model) != answer_model or (efforts and efforts != {EFFORT}):
            return {}
    rows = [json.loads(x) for x in Path(full_reuse).read_text().splitlines() if x.strip()]
    return {r["qid"]: r for r in rows if r.get("arm") == "full" and r.get("outcome") == "ok"
            and r.get("correct") is not None}


def run_lme(path: Path, out: Path, llm, *, conditions=LME_CONDITIONS, n: int = 100, params: dict,
            counts: dict[str, int] = lm.SAMPLE_COUNTS, seed: int = lm.SEED, answer_model: str = ANSWER_MODEL,
            judge_model: str = JUDGE_MODEL, compile_model: str = COMPILE_MODEL, cap_floor: int = CAP_FLOOR,
            full_reuse: Path | None = FULL_REUSE, reuse_prompt: bytes | None = None, workers: int = 1) -> list[str]:
    """Run the first `n` items of the fixed sample under `conditions`; returns their ids."""
    unknown = set(conditions) - set(LME_CONDITIONS)
    if unknown:
        raise ValueError(f"unknown conditions: {sorted(unknown)}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items = lm.sample(lm.load(Path(path)), counts, seed)[:n]
    results, recall_path = out / "results.jsonl", out / "recall.jsonl"
    done = _done(results)
    recall_done = ({json.loads(x)["qid"] for x in recall_path.read_text().splitlines() if x.strip()}
                   if recall_path.exists() else set())
    reuse = _reusable_full(full_reuse, reuse_prompt, answer_model) if "full" in conditions else {}
    lock, stop = threading.Lock(), threading.Event()

    def grade_for(item):
        return lambda text, judge: lme.grade(item, text, judge, judge_model)

    def work(item: lm.Item) -> None:
        pending = [c for c in conditions if (item.qid, c) not in done]
        if not pending or stop.is_set():
            return
        wd = out / "stores" / item.qid
        answer_ids = set(item.answer_session_ids)
        try:
            sessions = lme.sessions(item)
            index = None
            if set(pending) & set(SEARCH_CONDITIONS):
                index = _item_index(sessions, wd, params)
                if item.qid not in recall_done:
                    kw = _search_kw(params, item)
                    r = {k: (session_recall(index, item.question, answer_ids, k, **kw) if answer_ids else None)
                         for k in (5, 10)}
                    _append(recall_path, {"qid": item.qid, "qtype": item.qtype,
                                          "recall@5": r[5], "recall@10": r[10]}, lock)
            profile_ctx = ""
            if set(pending) & {"profile", "profile+search"}:
                profile = pl.profile_from_sessions(sessions, llm, compile_model, wd / "b", cap_floor=cap_floor)
                profile_ctx = pl.profile_full(profile)
            for c in pending:
                if stop.is_set():
                    return
                if c == "full" and item.qid in reuse:
                    old = reuse[item.qid]
                    row = {"qid": item.qid, "qtype": item.qtype, "condition": "full", "correct": old["correct"],
                           "outcome": old["outcome"], "input_tokens": old.get("input_tokens", 0),
                           "output_tokens": old.get("output_tokens", 0), "usd": old.get("usd", 0.0),
                           "backend": old.get("backend", "api"), "tool_calls": 0, "answer": old.get("response", ""),
                           "reused": True}
                    _append(results, row, lock)
                    continue
                tally, box = pl.Tally(llm), None
                if c == "profile":
                    reply = pl.answer(lme.question_text(item), profile_ctx, tally, answer_model,
                                      instructions=lme.instructions(item, "profile-full"), max_tokens=lme.MAX_TOKENS,
                                      label="answer:lme-profile")
                elif c in ("search", "profile+search"):
                    box = SearchToolbox(index, params=params, now=_now(item))
                    system = lme.instructions(item, c)
                    if c == "profile+search" and profile_ctx.strip():
                        system += "\n\n" + profile_ctx
                    reply = tally.run_tools(model=answer_model, system=system, user=lme.question_text(item),
                                            tools=box, max_turns=MAX_TOOL_TURNS, max_tokens=lme.MAX_TOKENS,
                                            label="answer:lme-search")
                elif c == "search-1shot":
                    box = SearchToolbox(index, params=params, now=_now(item))
                    ctx = box.call("conversation_search", {"query": item.question})
                    reply = pl.answer(lme.question_text(item), ctx, tally, answer_model,
                                      instructions=lme.instructions(item, "raw-retrieval"),
                                      max_tokens=lme.MAX_TOKENS, label="answer:lme-search-1shot")
                else:   # full
                    reply = answer_full_context(item, tally, answer_model)
                judge = pl.Tally(llm)
                row = _graded_row(item.qid, item.qtype, c, reply, grade_for(item), judge, box)
                row["input_tokens"] = sum(r.input_tokens for r in tally.replies)
                row["output_tokens"] = sum(r.output_tokens for r in tally.replies)
                row["usd"] = sum(r.usd for r in tally.replies) + sum(r.usd for r in judge.replies)
                if c in SEARCH_CONDITIONS:
                    row["retrieved_answer_session"] = bool(box.retrieved & answer_ids) if box else False
                _append(results, row, lock)
            if index is not None:
                index.close()
        except BudgetExceeded as e:
            stop.set()
            _append(out / "errors.jsonl", {"qid": item.qid, "error": f"stopped: {e}"}, lock)
        except Exception as e:   # left unrecorded so a rerun retries it
            if type(e).__name__ == "SubscriptionClosed":
                stop.set()
            _append(out / "errors.jsonl", {"qid": item.qid, "error": repr(e)[:500],
                                           "trace": traceback.format_exc()[-1500:]}, lock)

    _run_items(items, work, workers)
    if stop.is_set():
        print("stopped early (spend cap or plan usage); rerun to continue", file=sys.stderr)
    return [i.qid for i in items]


# ---------------------------------------------------------------- PrefEval

def run_prefeval(root: Path, out: Path, llm, *, conditions=PREF_CONDITIONS, n: int = 100, seed: int = 20261119,
                 params: dict, reuse_stores: Path | None = PREF_REUSE, n_inter: int = 10,
                 answer_model: str = ANSWER_MODEL, judge_model: str = JUDGE_MODEL,
                 compile_model: str = COMPILE_MODEL, cap_floor: int = CAP_FLOOR, workers: int = 1) -> list[str]:
    """PrefEval-100 under `conditions`. A store from the earlier run (`reuse_stores/<item>`, holding the reply to
    the preference and the compiled profile) is copied in before anything is generated, so its profile is used as
    is; what is missing is generated (the reply on the API, the compile on the subscription)."""
    from um.bench.public import prefeval as pe
    unknown = set(conditions) - set(PREF_CONDITIONS)
    if unknown:
        raise ValueError(f"unknown conditions: {sorted(unknown)}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items = pe.sample(pe.load(root), n, seed)
    inter = pe.inter_turns(root, n_inter)
    results = out / "results.jsonl"
    done = _done(results)
    lock, stop = threading.Lock(), threading.Event()

    def work(item) -> None:
        pending = [c for c in conditions if (item.id, c) not in done]
        if not pending or stop.is_set():
            return
        key = item.id.replace(":", "-")
        wd = out / "stores" / key
        try:
            if reuse_stores is not None and (Path(reuse_stores) / key).is_dir() and not wd.exists():
                shutil.copytree(Path(reuse_stores) / key, wd)
            f = wd / "pref_generation.json"
            if not f.exists():
                r = pe.pref_generation(item, llm, answer_model)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps({"text": r.text, "input_tokens": r.input_tokens,
                                         "output_tokens": r.output_tokens, "usd": r.usd, "backend": r.backend}))
            sessions = pe.sessions(item, json.loads(f.read_text())["text"], inter)
            profile = pl.profile_from_sessions(sessions, llm, compile_model, wd / "b", cap_floor=cap_floor)
            ctx = pl.profile_full(profile)
            index = _item_index(sessions, wd, params) if "profile-full+search" in pending else None

            def grade(text, judge):
                checks = pe.judge(item, text, judge, judge_model, root)
                s = pe.score(checks)
                return {"correct": s["preference_following"], **{k: checks[k] for k in pe.CHECKS}}

            for c in pending:
                if stop.is_set():
                    return
                tally, box = pl.Tally(llm), None
                if c == "profile-full":
                    reply = pl.answer(pe.question_text(item), ctx, tally, answer_model, instructions=pe.SYSTEM_PROMPT,
                                      max_tokens=pe.ANSWER_MAX_TOKENS, label="answer:prefeval:profile-full")
                else:
                    box = SearchToolbox(index, params=params, now=pe.SESSION_DATE)
                    system = pe.SYSTEM_PROMPT + ("\n\n" + ctx if ctx.strip() else "")
                    reply = tally.run_tools(model=answer_model, system=system, user=pe.question_text(item),
                                            tools=box, max_turns=MAX_TOOL_TURNS, max_tokens=pe.ANSWER_MAX_TOKENS,
                                            label="answer:prefeval-search")
                judge = pl.Tally(llm)
                row = _graded_row(item.id, item.topic, c, reply, grade, judge, box)
                row["usd"] = sum(r.usd for r in tally.replies) + sum(r.usd for r in judge.replies)
                if box is not None:
                    row["retrieved_answer_session"] = bool(box.retrieved)
                _append(results, row, lock)
            if index is not None:
                index.close()
        except BudgetExceeded as e:
            stop.set()
            _append(out / "errors.jsonl", {"qid": item.id, "error": f"stopped: {e}"}, lock)
        except Exception as e:
            if type(e).__name__ == "SubscriptionClosed":
                stop.set()
            _append(out / "errors.jsonl", {"qid": item.id, "error": repr(e)[:500],
                                           "trace": traceback.format_exc()[-1500:]}, lock)

    _run_items(items, work, workers)
    if stop.is_set():
        print("stopped early (spend cap or plan usage); rerun to continue", file=sys.stderr)
    return [i.id for i in items]


# ---------------------------------------------------------------- report

def _pct(x: float) -> str:
    return f"{100 * x:+.1f}"


def _paired(by: dict, a: str, b: str) -> tuple[int, tuple[float, float, float]] | None:
    if a not in by or b not in by:
        return None
    qids = sorted(set(by[a]) & set(by[b]))
    if not qids:
        return None
    return len(qids), paired_diff([bool(by[a][q]["correct"]) for q in qids], [bool(by[b][q]["correct"]) for q in qids])


def report(out: Path) -> str:
    out = Path(out)
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines() if x.strip()]
    by: dict[str, dict[str, dict]] = {}
    for r in rows:
        by.setdefault(r["condition"], {})[r["qid"]] = r
    pref = any(c in by for c in PREF_CONDITIONS)
    order = PREF_CONDITIONS if pref else LME_CONDITIONS
    lines = [f"# Conversation-search gate: {'PrefEval' if pref else 'LongMemEval-S'}", "",
             "| Condition | n | Correct | 95% Wilson | Judge failed | Mean input tokens | Tool calls (mean) | Reused |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in order:
        rs = list(by.get(c, {}).values())
        if not rs:
            continue
        k = sum(1 for r in rs if r["correct"])
        lo, hi = wilson(k, len(rs))
        lines.append(f"| `{c}` | {len(rs)} | {k} ({100 * k / len(rs):.0f}%) | {100 * lo:.0f} to {100 * hi:.0f} | "
                     f"{sum(1 for r in rs if r.get('outcome') == 'judge_failed')} | "
                     f"{sum(r.get('input_tokens', 0) for r in rs) / len(rs):,.0f} | "
                     f"{sum(r.get('tool_calls', 0) for r in rs) / len(rs):.2f} | "
                     f"{sum(1 for r in rs if r.get('reused'))} |")
    lines += ["", "## Paired differences (points, 95% bootstrap interval)", ""]
    pairs = ([("profile-full+search", "profile-full")] if pref else
             [("profile+search", "profile"), ("profile+search", "full"), ("search", "profile+search"),
              ("search-1shot", "search")])
    for a, b in pairs:
        p = _paired(by, a, b)
        if p:
            n, (pt, lo, hi) = p
            lines.append(f"- `{a}` minus `{b}`: {_pct(pt)} ({_pct(lo)} to {_pct(hi)}), n = {n}")
    lines += ["", "## Verdicts", ""]
    if pref:
        p = _paired(by, "profile-full+search", "profile-full")
        if p:
            n, (pt, lo, hi) = p
            ok = pt >= -0.02 and lo <= 0 <= hi
            lines.append(f"- G3 {'PASS' if ok else 'FAIL'}: point {_pct(pt)}, interval {_pct(lo)} to {_pct(hi)}, "
                         f"n = {n} (pass: point at least -2.0 and the interval includes 0)")
        else:
            lines.append("- G3 n/a: a condition is missing")
    else:
        p = _paired(by, "profile+search", "profile")
        if p:
            n, (pt, lo, hi) = p
            lines.append(f"- G1 {'PASS' if lo > 0 else 'FAIL'}: point {_pct(pt)}, interval {_pct(lo)} to {_pct(hi)}, "
                         f"n = {n} (pass: lower bound above 0)")
        else:
            lines.append("- G1 n/a: a condition is missing")
        if "profile" in by and "profile+search" in by:
            qids = [q for q in set(by["profile"]) & set(by["profile+search"]) if by["profile"][q]["qtype"] == "abstention"]
            kp = sum(1 for q in qids if by["profile"][q]["correct"])
            kps = sum(1 for q in qids if by["profile+search"][q]["correct"])
            lines.append(f"- G2 {'PASS' if kps >= kp - 1 else 'FAIL'}: abstention `profile+search` {kps} of {len(qids)}"
                         f" against `profile` {kp} (pass: no more than 1 fewer)")
        else:
            lines.append("- G2 n/a: a condition is missing")
        recall_path = out / "recall.jsonl"
        if recall_path.exists():
            rec = [json.loads(x) for x in recall_path.read_text().splitlines() if x.strip()]
            rec = [r for r in rec if r["recall@5"] is not None]
            if rec:
                lines += ["", "## Answer-session recall (no model)", "",
                          f"- recall@5 {sum(r['recall@5'] for r in rec) / len(rec):.3f}, recall@10 "
                          f"{sum(r['recall@10'] for r in rec) / len(rec):.3f}, over {len(rec)} questions with answer sessions"]
        if "full" in by and "profile+search" in by:
            miss = [q for q in set(by["full"]) & set(by["profile+search"])
                    if by["full"][q]["correct"] and not by["profile+search"][q]["correct"]]
            no_ret = sum(1 for q in miss if by["profile+search"][q].get("retrieved_answer_session") is False)
            lines += ["", "## Embeddings-gate inputs", "",
                      f"- `full` right and `profile+search` wrong: {len(miss)}; of those, no answer session retrieved: "
                      f"{no_ret}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- command line

def _record(out: Path, inv: dict, spent_before: float, spent_after: float) -> None:
    meta_path = out / "run_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"invocations": []}
    meta["invocations"].append(public_invocation(inv, spent_before, spent_after))
    meta_path.write_text(json.dumps(meta, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="um.bench.search_gate")
    ap.add_argument("--bench", required=True, choices=("lme", "prefeval", "tune", "report"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--api-cap", type=float, default=None, help="hard API cap in dollars, whole ledger")
    ap.add_argument("--ledger", type=Path, default=Path("results/spend.jsonl"))
    ap.add_argument("--conditions", default=None, help="comma list; default: all for the benchmark")
    ap.add_argument("--params", type=Path, default=None, help="JSON written by --bench tune")
    ap.add_argument("--grid", type=Path, default=None, help="tune: JSON grid; default: the plan's grid")
    ap.add_argument("--lme-data", type=Path, default=Path("data/public/longmemeval/longmemeval_s_cleaned.json"))
    ap.add_argument("--prefeval-root", type=Path, default=Path("data/public/prefeval"))
    ap.add_argument("--reuse-stores", type=Path, default=PREF_REUSE)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sub-ceiling", type=float, default=70.0)
    ap.add_argument("--usage-file", type=Path, default=Path.home() / ".claude/usage-now.json")
    a = ap.parse_args(argv)

    if a.bench == "report":
        text = report(a.out)
        (a.out / "report.md").write_text(text)
        print(text)
        return
    if a.bench == "tune":
        grid = json.loads(a.grid.read_text()) if a.grid else DEFAULT_GRID
        print(json.dumps(tune(a.lme_data, a.out, grid)))
        return
    if a.api_cap is None:
        ap.error("--api-cap is required for lme and prefeval")

    from um.bench.public.run import Router
    from um.budget import Budget
    from um.gate import UsageGate
    from um.llm import AnthropicLLM
    from um.llm_sub import ClaudeCodeLLM

    params = {**DEFAULT_PARAMS, **(json.loads(a.params.read_text()) if a.params else {})}
    budget = Budget(a.api_cap, a.ledger)
    llm = Router(AnthropicLLM(budget), ClaudeCodeLLM(), UsageGate(a.sub_ceiling, 900, a.usage_file),
                 sub_prefixes=("compile",))
    spent_before = budget.spent()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.bench == "lme":
        conditions = tuple(a.conditions.split(",")) if a.conditions else LME_CONDITIONS
        ids = run_lme(a.lme_data, a.out, llm, conditions=conditions, n=a.n, params=params, workers=a.workers)
    else:
        conditions = tuple(a.conditions.split(",")) if a.conditions else PREF_CONDITIONS
        ids = run_prefeval(a.prefeval_root, a.out, llm, conditions=conditions, n=a.n, params=params,
                           reuse_stores=a.reuse_stores, workers=a.workers)
    _record(a.out, {"argv": sys.argv[1:] if argv is None else list(argv), "started": started,
                    "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bench": a.bench,
                    "items": ids, "conditions": list(conditions), "params": params, "answer_model": ANSWER_MODEL,
                    "judge_model": JUDGE_MODEL, "compile_model": COMPILE_MODEL, "effort": EFFORT,
                    "cap_floor": CAP_FLOOR, "max_tool_turns": MAX_TOOL_TURNS},
            spent_before, budget.spent())
    print(f"API cost of this run ${budget.spent() - spent_before:.4f}")


if __name__ == "__main__":
    main()
