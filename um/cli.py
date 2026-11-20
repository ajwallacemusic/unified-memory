"""The plugin's command line: compile the profile with Arm B, answer a question, undo, erase, status.

    python -m um.cli init    [--profile P]   (create a profile; P is remembered in ~/.config/unified-memory)
    python -m um.cli compile [--profile P]
    python -m um.cli review  [--profile P]   (questions only; see um/review.py)
    python -m um.cli answer  --profile P --text "Yes, I moved."
    python -m um.cli undo    --profile P
    python -m um.cli erase   --profile P --value V --yes [--purge-history]
    python -m um.cli status  --profile P
    python -m um.cli bootstrap --from EXPORT [--evidence DIR] --profile P

Bootstrap imports an account-memory export unchanged (one commit), then runs the Arm A clean-up pass once,
with the evidence if given, and commits that as a compile so undo reverts it. Arm B compiles from then on:
B alone settles nothing in a legacy store, because it only acts on cited evidence.

The profile is a local git repository. Each compile commits once and writes a receipt to digest/<date>.md;
undo reverts the last compile commit. Questions go to digest/pending.md, at most three a week; an answer
is kept as user-said evidence in .answers/ and is read by the next compile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from um.arms import a as arm_a, b
from um.bridge.inbox import ingest_inbox
from um.bridge.prepare import MIRRORED
from um.digest import receipt
from um.erase import _hit, erase_values, purge_history, raw_copies, remaining
from um.questions import QuestionBudget
from um.transcripts import evidence_from_transcript

RECORDS = (".lineage.jsonl", ".answers", ".pass.json")
IGNORE = ".um/\ninbox/\noutbox/\nstate.json\nbridge-log.jsonl\n"


def _git(p: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(p), *a], check=True, capture_output=True, text=True).stdout


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _store_parts(p: Path) -> list[Path]:
    parts = [p / m.rstrip("/") for m in MIRRORED] + [p / r for r in RECORDS]
    return [x for x in parts if x.exists()]


def _copy_parts(src: Path, dst: Path) -> None:
    for part in _store_parts(src):
        target = dst / part.relative_to(src)
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.copytree(part, target) if part.is_dir() else shutil.copy2(part, target)


def _file_new_parts(out: Path, p: Path) -> None:
    """The compile prompt files new lines under `memory/` (the replay's layout); in a profile they belong in
    `topics/`, the folder the prompt hook, the index and the bridge read. Lines join an existing file there.
    `_copy_parts` copies only the profile's own folders, so without this such a line was applied and then lost."""
    mem = out / "memory"
    if not mem.is_dir():
        return
    for f in sorted(mem.rglob("*.md")):
        target = p / "topics" / f.relative_to(mem)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            body = [x for x in f.read_text().splitlines() if x.lstrip().startswith("- ")]
            target.write_text(target.read_text().rstrip("\n") + "\n" + "".join(x + "\n" for x in body))
        else:
            target.write_text(f.read_text())


def _pending(p: Path) -> list[str]:
    f = p / "digest" / "pending.md"
    return [line for line in f.read_text().splitlines() if line.startswith("- [")] if f.exists() else []


def _llm():
    """The model route from um.config: `subscription` (default; every call through `claude -p` on the user's
    plan, nothing billed to an API), `api`, or `hybrid` (subscription while plan usage is known and low, else the
    API). With UM_LLM=subscription (the unattended daily job) no API client is ever built."""
    from um.config import llm_mode, load_config
    from um.llm_sub import ClaudeCodeLLM
    mode = llm_mode()
    if mode == "subscription":
        return ClaudeCodeLLM()
    from um.budget import Budget
    from um.llm import AnthropicLLM
    cfg = load_config()
    api = AnthropicLLM(Budget(float(cfg.get("api_cap", 50)),
                              Path(cfg.get("spend_log") or "~/.cache/um/spend.jsonl").expanduser()))
    if mode == "api":
        return api
    from um.gate import UsageGate
    from um.llm_sub import HybridLLM
    return HybridLLM(api, ClaudeCodeLLM(), UsageGate(70, 900, Path.home() / ".claude/usage-now.json"))


def _review_last_run(p: Path, rejected: int) -> str:
    """Record the owner's review of the newest bridge run (what `prepare`'s live gate reads)."""
    log = p / "bridge-log.jsonl"
    rows = [x for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
    if not rows:
        raise SystemExit("no bridge run is logged yet; run the scheduled task first")
    last = json.loads(rows[-1])
    last.update(reviewed=True, rejected=rejected)
    rows[-1] = json.dumps(last)
    log.write_text("\n".join(rows) + "\n")
    return f"run of {last.get('run_at', '?')} marked reviewed, {rejected} rejected"


def init_profile(target: Path) -> str:
    """Create an empty profile (a git repository in the account-memory layout), remember it in the config,
    and return the line that makes Claude Code import it. An existing profile is kept as it is."""
    from um.code_index import write_code_index
    from um.config import save_config
    target = Path(target).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not (target / "profile.md").exists():
        raise SystemExit(f"{target} is not empty and holds no profile.md; choose an empty or new folder")
    for d in ("areas", "topics", "people"):
        (target / d).mkdir(parents=True, exist_ok=True)
    if not (target / "profile.md").exists():
        (target / "profile.md").write_text("---\nname: profile\ndescription: Core facts about the user\n---\n")
    if not (target / ".git").exists():
        _git(target, "init", "-q")
    _ignore_bookkeeping(target)
    write_code_index(target)
    _git(target, "add", "-A")
    if _git(target, "status", "--porcelain").strip():
        _git(target, "-c", "user.name=unified-memory", "-c", "user.email=unified-memory@localhost",
             "commit", "-qm", "init profile")
    from um.config import load_config
    defaults = {k: False for k in ("prompt_hook", "standing") if k not in load_config()}
    save_config(profile=str(target), **defaults)
    return f"@{target / 'claude-code.md'}"


def _needs_you(p: Path) -> list[str]:
    """What an unattended run cannot settle: conflicts the bridge left, and the last bridge run's error."""
    out = []
    for f in sorted((p / "inbox" / "conflicts").glob("*.json")) if (p / "inbox" / "conflicts").is_dir() else []:
        try:
            path = json.loads(f.read_text()).get("path") or f.stem
        except ValueError:
            path = f.stem
        out.append(f"conflict on {path}: memory changed since the profile last saw it; nothing was overwritten")
    log = p / "bridge-log.jsonl"
    lines = [x for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
    try:
        last = json.loads(lines[-1]) if lines else {}
    except ValueError:
        last = {"error": "bridge-log.jsonl's last line is unreadable"}
    if last.get("error"):
        out.append(f"last bridge run ({last.get('run_at', '?')}) reported: {last['error']}")
    return out


def _consume(p: Path, um: Path, held: Path, merged: set[str], today: str, started: str) -> None:
    """After a compile that finished: advance the build mark, move its inputs to `*-done`, and record memory's
    version for each pull that was fully merged (with that pull as the next merge's base). A pull that was not
    merged keeps the old version, so the next push conflicts rather than overwriting the chat's edit."""
    from um.bridge.adopt import record_synced
    um.mkdir(exist_ok=True)
    (um / "build.json").write_text(json.dumps({"last_build": today, "last_build_at": started}))
    for f in sorted(held.glob("*.md")) if held.is_dir() else []:
        (um / "held-done").mkdir(exist_ok=True)
        shutil.move(str(f), um / "held-done" / f.name)
    state = _read_json(p / "state.json")
    for f in sorted((p / "inbox").glob("*.json")) if (p / "inbox").is_dir() else []:
        item = json.loads(f.read_text())
        path = item.get("path") or ""
        if path in merged and item.get("version"):
            entry = state.setdefault(path, {})
            entry["version"] = item["version"]
            if entry.get("pushed_sha256") != hashlib.sha256((item.get("content") or "").encode()).hexdigest():
                entry.pop("pushed_sha256", None)
            record_synced(p, path, item.get("content") or "")
        (um / "inbox-done").mkdir(exist_ok=True)
        shutil.move(str(f), um / "inbox-done" / f.name)
    (p / "state.json").write_text(json.dumps(state, indent=1))


def _ignore_bookkeeping(p: Path) -> None:
    """The bridge's own files (state, log, inboxes) change outside compiles; tracked, they make `undo` fail and
    roll back sync state. Keep them out of the profile's history."""
    f = p / ".gitignore"
    have = set(f.read_text().splitlines()) if f.exists() else set()
    missing = [x for x in IGNORE.splitlines() if x not in have]
    if missing:
        with f.open("a") as out:
            out.writelines(x + "\n" for x in missing)
    _git(p, "rm", "-q", "--cached", "--ignore-unmatch", "state.json", "bridge-log.jsonl")


def _memory_holders(p: Path, low: list[str]) -> set[str]:
    """Memory paths whose last known memory text (pulls, the merge base, the last push) holds a value."""
    from um.bridge.adopt import PUSHED, SYNCED
    found: set[str] = set()
    for f in list((p / "inbox").glob("*.json")) + list((p / ".um" / "inbox-done").glob("*.json")):
        item = json.loads(f.read_text())
        if _hit(item.get("content") or "", low):
            found.add(item.get("path") or "")
    from um.bridge.prepare import _mirrored
    state = _read_json(p / "state.json")
    paths = {k: v for k, v in state.items() if k.startswith("/") and isinstance(v, dict)}
    paths.update({"/" + f.relative_to(p).as_posix(): {} for f in _mirrored(p) if "/" + f.relative_to(p).as_posix() not in paths})
    for path, entry in paths.items():
        for f in (p / PUSHED / f"{entry.get('pushed_sha256')}.md",
                  p / SYNCED / f"{re.sub(r'[^a-z0-9]+', '-', path.lower()).strip('-')}.md"):
            if f.exists() and _hit(f.read_text(), low):
                found.add(path)
    return {x for x in found if x}


def _erase_bridge(p: Path, low: list[str], removed: list[str]) -> None:
    """The bridge's copies of memory text: drop the erased lines from the merge bases, remember their hashes so no
    later pull re-adopts them, approve deleting memory files the erase left without a fact, and mark every
    transcript message up to now as read."""
    from um.bridge.adopt import PUSHED, SYNCED, record_erased
    from um.bridge.prepare import _mirrored, fact_lines
    record_erased(p, removed)
    for d in (p / SYNCED, p / PUSHED):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            lines = f.read_text().splitlines(keepends=True)
            keep = [x for x in lines if not _hit(x, low)]
            if len(keep) != len(lines):
                f.write_text("".join(keep))
    emptied = []
    for f in _mirrored(p):
        if not fact_lines(f.read_text()):
            emptied.append("/" + f.relative_to(p).as_posix())
            f.unlink()
    if emptied:
        with (p / "delete-approved.txt").open("a") as out:
            out.writelines(x + "\n" for x in emptied)
    um = p / ".um"
    um.mkdir(exist_ok=True)
    build = _read_json(um / "build.json")
    build["last_build_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (um / "build.json").write_text(json.dumps(build))


def compile_profile(p: Path, projects: Path, model: str, today: str, llm) -> str:
    um = p / ".um"
    build = _read_json(um / "build.json")
    last = build.get("last_build")
    evdir = um / "evidence" / today
    if evdir.exists():
        shutil.rmtree(evdir)
    evdir.mkdir(parents=True)
    since = date.fromisoformat(last) if last else None
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for f in sorted(Path(projects).expanduser().glob("*/*.jsonl")) if Path(projects).expanduser().exists() else []:
        evidence_from_transcript(f, evdir, since=since, after=build.get("last_build_at"))
    ingest_inbox(p / "inbox", evdir, _read_json(p / "state.json"))
    from um.bridge.adopt import adopt_memory
    from um.bridge.prepare import deleted_paths
    adopted, merged = adopt_memory(p, p / "inbox", _read_json(p / "state.json"), deleted_paths(p))
    held = p / "inbox" / "held"
    for f in sorted(held.glob("*.md")) if held.is_dir() else []:
        shutil.copy2(f, evdir / f.name)

    budget = QuestionBudget(3)
    for line in _pending(p):
        m = re.match(r"- \[(\d{4}-\d{2}-\d{2})\]", line)
        if m:
            budget.allow(m.group(1))
    asked: list[str] = []

    def ask(question: dict):
        asked.append(question.get("text") or question.get("attr") or "")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "src", Path(tmp) / "out"
        src.mkdir()
        _copy_parts(p, src)
        outcome = b.apply(src, out, llm, model, today, evidence_dir=evdir, ask=ask, budget=budget)
        record = json.loads((out / b.PASS_FILE).read_text())
        applied = sum(1 for c in record.get("changes", []) if c.get("applied"))
        if applied or asked or outcome != "ok":
            _copy_parts(out, p)
            _file_new_parts(out, p)
    needs = _needs_you(p)
    changed = applied or asked or adopted or needs or outcome != "ok"
    if outcome == "ok":
        _consume(p, um, held, merged, today, started)
    try:  # hook words and standing labels for new lines; a failure only leaves those lines without them
        from um.expand import expand_profile
        from um.standing import label_standing
        from um.config import load_config
        cfg = load_config()
        if cfg.get("prompt_hook") is not False:
            expand_profile(p, llm, model)
        if cfg.get("standing") is True:
            label_standing(p, llm, model)
    except Exception:
        pass
    from um.code_index import write_code_index
    write_code_index(p)
    if not changed:
        return "nothing to do"
    (p / "digest").mkdir(exist_ok=True)
    text = receipt(record)
    if needs:
        text = text.rstrip("\n") + "\n\n## Needs you (" + str(len(needs)) + ")\n\n" + "".join(f"- {x}\n" for x in needs)
    if adopted:
        text += "\n## From account memory (" + str(len(adopted)) + ")\n\n" + "".join(f"- {x}\n" for x in adopted)
    (p / "digest" / f"{today}.md").write_text(text)
    if asked:
        with (p / "digest" / "pending.md").open("a") as f:
            for q in asked:
                f.write(f"- [{today}] {q}\n")
    _ignore_bookkeeping(p)
    _git(p, "add", "-A")
    held_n = sum(1 for c in record.get("changes", []) if c.get("decision") in ("hold", "ask") and not c.get("applied"))
    _git(p, "commit", "-qm", f"compile {today}: {applied} applied, {len(adopted)} from memory, {held_n} held, {len(asked)} asked")
    return f"{applied} applied, {len(adopted)} from memory, {held_n} held, {len(asked)} asked"


def _diff_digest(p: Path, today: str, outcome: str) -> str:
    parts = [m.rstrip("/") for m in MIRRORED if (p / m.rstrip("/")).exists()]
    out = [f"# Bootstrap clean-up, {today}", "", f"Arm A clean-up pass, outcome {outcome}. Undo reverts it.", ""]
    for line in _git(p, "diff", "-U0", "--", *parts).splitlines():
        if line.startswith("+++ b/"):
            out += ["", f"## {line[6:]}", ""]
        elif line.startswith("-") and not line.startswith("---"):
            out.append(f"- removed: `{line[1:]}`")
        elif line.startswith("+"):
            out.append(f"- added: `{line[1:]}`")
    return "\n".join(out) + "\n"


def bootstrap(src: Path, p: Path, evidence: Path | None, model: str, today: str, llm) -> str:
    if p.exists() and any(p.iterdir()):
        raise SystemExit(f"{p} is not empty; bootstrap only starts a new profile")
    shutil.copytree(src, p, dirs_exist_ok=True)
    (p / ".gitignore").write_text(IGNORE)
    _git(p, "init", "-q")
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "import: account memory export (unchanged)")
    with tempfile.TemporaryDirectory() as tmp:
        work, out = Path(tmp) / "src", Path(tmp) / "out"
        work.mkdir()
        _copy_parts(p, work)
        outcome = arm_a.apply(work, out, llm, model, today, evidence_dir=evidence)
        if outcome == "ok":
            _copy_parts(out, p)
            (p / b.PASS_FILE).unlink(missing_ok=True)
    if not _git(p, "status", "--porcelain").strip():
        return f"imported; clean-up outcome {outcome}, no changes"
    (p / "digest").mkdir(exist_ok=True)
    (p / "digest" / f"{today}-bootstrap.md").write_text(_diff_digest(p, today, outcome))
    _git(p, "add", "-A")
    files = len([x for x in _git(p, "diff", "--cached", "--name-only").splitlines() if not x.startswith("digest/")])
    _git(p, "commit", "-qm", f"compile {today}: bootstrap cleanup (arm A), {files} files changed")
    return f"imported; clean-up changed {files} files; receipt digest/{today}-bootstrap.md"


DESKTOP_SESSIONS = "~/Library/Application Support/Claude/local-agent-mode-sessions"


def _search_roots(a) -> tuple[Path, Path | None]:
    """Claude Code projects and desktop session folders to catch up from. `--desktop` defaults to the desktop
    app's local-agent sessions when that folder exists."""
    projects = Path(a.projects or "~/.claude/projects").expanduser()
    if a.desktop is not None:
        return projects, Path(a.desktop).expanduser()
    d = Path(DESKTOP_SESSIONS).expanduser()
    return projects, (d if d.is_dir() else None)


def _catch_up(index, a, force: bool) -> dict:
    import time
    from um.config import search_include_sdk
    from um.search.ingest import catch_up
    projects, desktop = _search_roots(a)
    return catch_up(index, projects=projects, desktop=desktop, now=time.time(),
                    include_sdk=search_include_sdk(), force=force)


def _export_age(web: str) -> str:
    day = web[:10]
    try:
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(day)).days
    except ValueError:
        return f"web export {day}"
    return f"web export {day} ({age} day{'' if age == 1 else 's'} old)"


def _search_status_line() -> str:
    """One line for `um.cli status`. Never creates the index."""
    from um.config import search_index_path
    from um.search.index import Index
    path = search_index_path()
    if not path.exists():
        return "search: no index"
    try:
        index = Index(path)
    except ValueError as e:
        return f"search: {e}"
    try:
        n = sum(index.stats()["sessions"].values())
        web = index.get_meta("web_export_date")
    finally:
        index.close()
    if not web:
        return f"search: {n} sessions, no web export"
    try:
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(web[:10])).days
        return f"search: {n} sessions, web export {age} days old"
    except ValueError:
        return f"search: {n} sessions, web export {web[:10]}"


def _erase_index(a) -> str | None:
    """After the profile erase: catch up, then erase the values from the search index. With no index yet, create
    it holding only the erase guard (no catch-up), so a later build drops the values too. Returns the exception
    name on failure (the caller exits non-zero), None otherwise."""
    from um.config import profile_path, search_index_path
    path = search_index_path()
    try:
        from um.search import forget
        from um.search.index import Index, check_index_path
        existed = path.exists()
        if not existed:
            check_index_path(path, profile_path())
        index = Index(path)
        try:
            if existed:
                _catch_up(index, a, force=True)
            r = forget.erase_from_index(index, a.value)
        finally:
            index.close()
    except Exception as e:  # never silent: reported here and by the exit status
        print(f"search index NOT erased: {type(e).__name__}")
        return type(e).__name__
    if existed:
        print(f"search index: removed {r['chunks']} chunks in {r['sessions']} sessions")
    else:
        print("search index: none yet; created it holding the erase, so a later build drops the value")
    return None


def _chunk_fmt(params) -> str:
    return "unrecorded" if params is None else f"{params[0]}/{params[1]}"


def _search(a) -> None:
    import os
    from um.config import profile_path, search_index_path
    from um.search.index import Index, check_index_path
    path = search_index_path()
    try:
        check_index_path(path, profile_path())
    except ValueError as e:
        raise SystemExit(str(e))
    if a.scmd == "forget":
        if not a.yes:
            raise SystemExit("refusing to forget without --yes: it cannot be undone")
        if a.all:
            if not path.exists():
                print("no search index to empty")
                return
            index = Index(path)
            try:
                n = index.forget_all()
            finally:
                index.close()
            print(f"search index emptied ({n} chunks removed); erase records kept, so erased values stay out "
                  "when it is rebuilt")
            return
    from um.config import SEARCH_OFF, search_enabled
    if a.scmd in ("index", "query", "recent") and not search_enabled():
        if getattr(a, "if_enabled", False):
            return                                    # the SessionStart hook: a quiet no-op
        raise SystemExit(SEARCH_OFF)
    try:
        index = Index(path)
    except ValueError as e:
        raise SystemExit(str(e))
    try:
        if a.scmd in ("index", "query", "recent", "rebuild"):
            import sys
            r = index.rechunk() if a.scmd == "rebuild" else index.ensure_chunk_params()
            if r is not None:
                frm = "unrecorded" if r["from"] is None else f"{r['from'][0]}/{r['from'][1]}"
                msg = (f"re-chunked {r['sessions']} sessions ({r['turns']} turns) from {frm} to "
                       f"{index.get_meta('chunk_chars')}/{index.get_meta('lead_chars')}"
                       + (f"; {r['turns_skipped']} turns with erased parts left as they were"
                          if r["turns_skipped"] else ""))
                # query/recent output must start with the search notice, so the note goes to stderr there
                print(msg, file=sys.stderr if a.scmd in ("query", "recent") else sys.stdout)
        if a.scmd == "index":
            r = _catch_up(index, a, force=a.force)
            print("catch-up skipped (ran under 10 seconds ago)" if r["skipped"] else
                  f"{r['files_read']} files read, {r['chunks_written']} chunks written, as of {r['as_of']}"
                  + (f"; {r['files_failed']} file{'' if r['files_failed'] == 1 else 's'} failed (retried next time)"
                     if r.get("files_failed") else ""))
        elif a.scmd == "import-export":
            import zipfile
            from um.search.ingest import import_export
            for src in a.paths:
                try:
                    r = import_export(index, src, keep_deleted=a.keep_deleted, force=a.force)
                except FileNotFoundError:
                    raise SystemExit(f"{src}: no such file or folder")
                except zipfile.BadZipFile as e:
                    raise SystemExit(f"{src}: not a readable zip ({e})")
                except (ValueError, OSError) as e:
                    raise SystemExit(f"{src}: {' '.join(str(e).split())}")
                print(f"{src}: {r['added']} added, {r['replaced']} replaced, {r['unchanged']} unchanged, "
                      f"{r['removed']} removed; export dated {r['export_date'] or 'unknown'}"
                      + ("" if r["complete"] else " (partial export: nothing removed)"))
        elif a.scmd in ("query", "recent"):
            from um.search.tools import ToolArgError, call_tool
            if a.scmd == "query":
                name = "conversation_search"
                args = {"query": " ".join(a.text), "max_results": a.max_results, "after": a.after,
                        "before": a.before, "sort": a.sort, "surface": a.surface, "project": a.project,
                        "within_session_id": a.within}
            else:
                name = "recent_chats"
                args = {"n": a.n, "after": a.after, "before": a.before, "sort_order": a.order}
            args = {k: v for k, v in args.items() if v is not None}
            try:
                r = call_tool(index, name, args, env=os.environ, before_query=lambda: _catch_up(index, a, False))
            except ToolArgError as e:
                raise SystemExit(f"search {a.scmd}: {e}")
            print(r["text"])
        elif a.scmd == "status":
            st = index.stats()
            print(f"search index {path}")
            for surface in ("code", "desktop", "web"):
                print(f"{surface}: {st['sessions'].get(surface, 0)} sessions, {st['chunks'].get(surface, 0)} chunks")
            code = index.get_meta("code_as_of")
            print(f"code and desktop as of {code}" if code else "code and desktop not indexed yet")
            web = index.get_meta("web_export_date")
            print(_export_age(web) if web else "no web export imported")
            print(f"source gone: {st['source_gone']}")
            from um.config import search_enabled
            if not search_enabled():
                print('search is off ("search": false in the config)')
            mm = index.chunk_params_mismatch()
            if mm is None:
                print(f"chunking {_chunk_fmt(index.stored_chunk_params())} (current)")
            else:
                print(f"chunking {_chunk_fmt(mm['stored'])}, current is {_chunk_fmt(mm['current'])}: run "
                      "python -m um.cli search rebuild (index, query and the tools also re-chunk on first use)")
            failed = index.get_meta("catch_up_files_failed")
            if failed and failed != "0":
                print(f"files failed at the last catch-up: {failed}")
        elif a.scmd == "forget":
            from um.search.forget import forget_session
            n = forget_session(index, a.session)
            print(f"removed {n} chunks" if n else f"no session {a.session!r} in the index")
    finally:
        index.close()


def _add_search_parser(sub) -> None:
    s = sub.add_parser("search")
    ss = s.add_subparsers(dest="scmd", required=True)

    def roots(p):
        p.add_argument("--projects", type=Path, default=None)
        p.add_argument("--desktop", type=Path, default=None)

    p = ss.add_parser("index")
    roots(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--if-enabled", action="store_true", help="do nothing, quietly, when search is off (the hook)")
    ss.add_parser("rebuild", help="re-chunk the stored conversations with the current chunk parameters")
    p = ss.add_parser("import-export")
    p.add_argument("paths", type=Path, nargs="+")
    p.add_argument("--keep-deleted", action="store_true")
    p.add_argument("--force", action="store_true")
    p = ss.add_parser("query")
    p.add_argument("text", nargs="+")
    p.add_argument("--max-results", type=int)
    p.add_argument("--after")
    p.add_argument("--before")
    p.add_argument("--sort", choices=("relevance", "newest", "oldest"))
    p.add_argument("--surface", nargs="+")
    p.add_argument("--project")
    p.add_argument("--within")
    roots(p)
    p = ss.add_parser("recent")
    p.add_argument("--n", type=int)
    p.add_argument("--after")
    p.add_argument("--before")
    p.add_argument("--order", choices=("desc", "asc"))
    roots(p)
    ss.add_parser("status")
    p = ss.add_parser("forget")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--session")
    g.add_argument("--all", action="store_true")
    p.add_argument("--yes", action="store_true")


def main(argv: list[str] | None = None, llm=None) -> None:
    ap = argparse.ArgumentParser(prog="um.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("compile", "answer", "undo", "erase", "status", "review"):
        s = sub.add_parser(name)
        s.add_argument("--profile", type=Path, default=None)
        s.add_argument("--today", default=date.today().isoformat())
        if name == "compile":
            s.add_argument("--projects", type=Path, default=Path("~/.claude/projects"))
        if name in ("compile", "review"):
            s.add_argument("--model", default="claude-sonnet-5-5")
        if name == "answer":
            s.add_argument("--text", required=True)
        if name == "erase":
            s.add_argument("--value", action="append", required=True)
            s.add_argument("--raw-root", type=Path, action="append", default=[])
            s.add_argument("--yes", action="store_true")
            s.add_argument("--purge-history", action="store_true")
            s.add_argument("--projects", type=Path, default=None)   # search-index catch-up before the erase
            s.add_argument("--desktop", type=Path, default=None)
    _add_search_parser(sub)
    s = sub.add_parser("bootstrap")
    s.add_argument("--from", dest="src", type=Path, required=True)
    s.add_argument("--evidence", type=Path)
    s.add_argument("--profile", type=Path, default=None)
    s.add_argument("--today", default=date.today().isoformat())
    s.add_argument("--model", default="claude-sonnet-5-5")
    s = sub.add_parser("init")
    s.add_argument("--profile", type=Path, default=None)
    s = sub.add_parser("bridge-prompt")
    s.add_argument("--profile", type=Path, default=None)
    s = sub.add_parser("bridge-review")
    s.add_argument("--profile", type=Path, default=None)
    s.add_argument("--rejected", type=int, default=0)
    a = ap.parse_args(argv)
    if a.cmd == "search":
        _search(a)
        return
    from um.config import profile_path
    p = profile_path(a.profile)

    if a.cmd == "init":
        line = init_profile(p)
        print(f"profile ready at {p}\nTo let every Claude Code session read it, add this line to ~/.claude/CLAUDE.md:\n{line}")
        return
    if a.cmd == "bridge-prompt":
        tpl = (Path(__file__).resolve().parents[1] / "bridge" / "task-prompt.md").read_text()
        print(tpl.replace("{{PROFILE}}", str(p.resolve())).replace("{{MOUNT}}", p.resolve().name), end="")
        return
    if a.cmd == "bridge-review":
        print(_review_last_run(p, a.rejected))
        return

    if a.cmd == "bootstrap":
        print(bootstrap(a.src.expanduser(), p, a.evidence, a.model, a.today, llm or _llm()))
    elif a.cmd == "review":
        from um.review import review_store, write_review
        found, dropped = review_store(p, llm or _llm(), a.model, a.today)
        write_review(found, p / "digest" / f"{a.today}-review.md", a.today, dropped)
        print(f"{len(found)} questions, {dropped} dropped; digest/{a.today}-review.md")
    elif a.cmd == "compile":
        print(compile_profile(p, a.projects, a.model, a.today, llm or _llm()))
    elif a.cmd == "answer":
        d = p / ".answers"
        d.mkdir(exist_ok=True)
        n = len(list(d.glob(f"u{a.today.replace('-', '')}-*.md"))) + 1
        f = d / f"u{a.today.replace('-', '')}-{n:02d}.md"
        f.write_text(f"origin: user-said\ndate: {a.today}\n\n{a.text.strip()}\n")
        print(f"kept as {f.name}; the next compile reads it")
    elif a.cmd == "undo":
        subject = _git(p, "log", "-1", "--format=%s").strip()
        if not subject.startswith("compile "):
            raise SystemExit(f"the last commit is not a compile ({subject!r}); nothing undone")
        print(f"reverting: {subject}")
        try:
            _git(p, "revert", "--no-edit", "HEAD")
        except subprocess.CalledProcessError as e:
            _git(p, "revert", "--abort") if (p / ".git" / "REVERT_HEAD").exists() else None
            raise SystemExit(f"undo failed, nothing changed: {e.stderr.strip()[:300]}")
    elif a.cmd == "erase":
        if not a.yes:
            raise SystemExit("refusing to erase without --yes: it cannot be undone")
        dirs = [d for d in (p / ".um" / "evidence").glob("*") if d.is_dir()] if (p / ".um" / "evidence").exists() else []
        dirs += [d for d in (p / "inbox" / "held", p / ".um" / "held-done") if d.is_dir()]
        rep = erase_values(p, a.value, dirs)
        low = [v.lower() for v in a.value]
        holders = _memory_holders(p, low)
        for f in list((p / "inbox").glob("*.json")) + list((p / ".um" / "inbox-done").glob("*.json")):
            if _hit(f.read_text(), low):
                f.unlink()
        _erase_bridge(p, low, [line for _, line in rep.lines_removed])
        if _git(p, "status", "--porcelain").strip():
            _git(p, "add", "-A")
            _git(p, "commit", "-qm", f"erase: {len(rep.lines_removed)} lines removed")
        left = remaining(p, a.value)
        print(f"removed {len(rep.lines_removed)} lines; still present in the profile: {', '.join(left) if left else 'nowhere'}")
        if holders:
            print("account memory still holds it until the next live push: " + ", ".join(sorted(holders)))
        print("transcript messages before now will not be read again; run compile before erase to keep them")
        index_failed = _erase_index(a)
        roots = a.raw_root or [Path("~/.claude/projects").expanduser()]
        for v, files in raw_copies(a.value, roots).items():
            print(f"raw copies outside the profile ({len(files)}), delete them in their own apps:")
            for f in files:
                print(f"  {f}")
        if a.purge_history:
            purge_history(p, a.value)
            print("git history rewritten")
        else:
            print("the profile's git history still holds the value; rerun with --purge-history to rewrite it")
        if index_failed:
            raise SystemExit(f"search index NOT erased: {index_failed}")
    elif a.cmd == "status":
        build = _read_json(p / ".um" / "build.json")
        held = len(list((p / "inbox" / "held").glob("*.md"))) if (p / "inbox" / "held").is_dir() else 0
        pend = _pending(p)
        needs = _needs_you(p)
        conflicts = sum(1 for x in needs if x.startswith("conflict"))
        print(f"last build {build.get('last_build', 'never')}, held {held}, pending {len(pend)}, "
              f"{conflicts} conflict{'s' if conflicts != 1 else ''}"
              + (f", next question: {pend[0]}" if pend else ""))
        for x in needs:
            print(f"  - {x}")
        print(_search_status_line())


if __name__ == "__main__":
    main()
