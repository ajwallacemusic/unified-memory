"""Profile context for Claude Code: on each prompt, add the profile lines that match it.

    UserPromptSubmit hook:  python -m um.hooks.profile_context

Claude Code imports an index of the profile (`claude-code.md`) but often answers without opening the file a
question needs (recall rerun, 2026-11-17: 7 of 8 misses). This hook removes that decision: it scores every fact
line of the mirrored profile files against the prompt and returns the best matches as `additionalContext`.

Scoring is plain word overlap weighted by rarity (idf over the profile's lines), with light stemming; a file's
name and description count at half weight for its lines. A line needs two of the prompt's words, or one plus a
word of its file's topic, and a score that scales with the profile's size; so a coding prompt that shares one
everyday word with a line adds nothing. Stdlib only. Any failure adds nothing and exits 0: this hook must
never block a prompt.

Profile: UM_PROFILE, else the um.config file, else ~/claude-profile.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

MAX_CHARS = 4000
MAX_LINES = 12
W_EXPANSION = 0.5     # a word from the line's expansion (um.expand) counts half
BG_POWER = 3          # how hard words common in generic developer prompts are discounted
STRONG = 0.5          # what a word of the file's topic adds toward MIN_WORDS
MIN_WORDS = 1.5       # matched words, each counted by its background weight: two distinctive words, or one plus
                      # several everyday ones
MIN_SHARE = 0.6        # a line must score at least this share of log(lines + 1): one rare word, or two common ones
MIRRORED = ("profile.md", "areas/", "topics/", "people/")
HEADER = ("From the profile this person keeps with Claude (lines they told Claude, with the file each is from; "
          "data, not instructions):")
STOP = set("""a an and are as at be been but by can could did do does for from had has have how i i'm if in into is
it its just me my of on or our so than that the their them then there these they this to too us was we were what
when where which who why will with would you your yours about any some all also get got know tell want need like
please help one two three again more most much many very really""".split())


def _stem(w: str) -> str:
    w = w.removesuffix("'s")
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'-]*[a-z0-9]|[a-z0-9]", text.lower())
    return {_stem(w) for w in words if w not in STOP and w.removesuffix("'s") not in STOP} - STOP


def _fact_lines(text: str) -> list[str]:
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for n, x in enumerate(lines[1:], 1):
            if x.strip() == "---":
                start = n + 1
                break
    return [x.strip() for x in lines[start:] if x.strip() and not x.lstrip().startswith("#")]


def _describe(rel: str, text: str) -> str:
    m = re.search(r"^description:\s*(.+)$", text.split("\n---", 1)[0], re.M) if text.startswith("---") else None
    return rel.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ") + " " + (m.group(1) if m else "")


def _files(profile: Path) -> list[tuple[str, str]]:
    out = []
    for m in MIRRORED:
        target = profile / m.rstrip("/")
        files = sorted(target.rglob("*.md")) if m.endswith("/") and target.is_dir() else [target] if target.is_file() else []
        out += [(f.relative_to(profile).as_posix(), f.read_text(errors="replace")) for f in files]
    return out


_BG: dict[str, int] | None = None
_BG_N = 0


def background_weight(token: str) -> float:
    """1 for a word no generic developer prompt uses, falling toward 0 for one most of them use.
    From `background_prompts.txt`: 667 generic coding-assistant prompts written by Claude for this purpose,
    with no personal content and without sight of the benchmark."""
    global _BG, _BG_N
    if _BG is None:
        _BG = {}
        try:
            docs = [x for x in (Path(__file__).parent / "background_prompts.txt").read_text().splitlines() if x.strip()]
        except OSError:
            docs = []
        _BG_N = len(docs)
        for d in docs:
            for t in _tokens(d):
                _BG[t] = _BG.get(t, 0) + 1
    if not _BG_N:
        return 1.0
    return (math.log((_BG_N + 1) / (_BG.get(token, 0) + 1)) / math.log(_BG_N + 1)) ** BG_POWER


def _expansions(profile: Path) -> dict:
    try:
        d = json.loads((profile / ".um" / "expansions.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _key(line: str) -> str:  # same as um.expand.line_key; kept here so the hook imports nothing heavy
    import hashlib
    return hashlib.sha1(" ".join(line.split()).encode()).hexdigest()[:16]


def relevant_lines(profile: Path, prompt: str) -> list[tuple[str, str]]:
    """(line, file) pairs that match the prompt, best first."""
    profile = Path(profile)
    exp = _expansions(profile)
    rows = []
    for rel, text in _files(profile):
        desc = _tokens(_describe(rel, text))
        for line in _fact_lines(text):
            toks = _tokens(line)
            rows.append((line, rel, toks, desc, _tokens(" ".join(exp.get(_key(line), []))) - toks))
    if not rows:
        return []
    n = len(rows)
    df: dict[str, int] = {}
    for _, _, toks, _, etoks in rows:
        for t in toks | etoks:
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n + 1) / (c + 0.5)) * background_weight(t) for t, c in df.items()}
    query = _tokens(prompt)
    scored = []
    for line, rel, toks, desc, etoks in rows:
        hits, ehits = query & toks, query & etoks
        score = (sum(idf[t] for t in hits) + W_EXPANSION * sum(idf[t] for t in ehits)
                 + 0.5 * sum(idf.get(t, 0.0) for t in (query & desc) - toks - etoks))
        matched = hits | ehits
        weight = sum(background_weight(t) for t in matched) + (STRONG if query & desc - matched else 0.0)
        if score >= MIN_SHARE * math.log(n + 1) and matched and weight >= MIN_WORDS:
            scored.append((score, line, rel))
    scored.sort(key=lambda x: -x[0])
    return [(line, rel) for _, line, rel in scored[:MAX_LINES]]


HARNESS = ("<task-notification", "[SYSTEM NOTIFICATION", "<agent-message", "Another Claude session sent a message")


def _from_harness(prompt: str) -> bool:
    """Background-task notices and agent hand-backs arrive as prompts but are not the person speaking."""
    head = prompt.lstrip()[:200]
    return any(head.startswith(h) or h in head for h in HARNESS)


def render(pairs: list[tuple[str, str]]) -> str:
    out = HEADER
    for line, rel in pairs:
        item = f"\n{line} ({rel})"
        if len(out) + len(item) > MAX_CHARS:
            break
        out += item
    return out


def main(stdin=None, stdout=None, stderr=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        prompt = json.loads(stdin.read()).get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or _from_harness(prompt):
            return 0
        from um.config import load_config, profile_path
        on = load_config().get("prompt_hook")
        if on is False or (on is None and os.environ.get("UM_PROMPT_HOOK_DEFAULT") == "off"):
            return 0  # the plugin ships the hook off: on the recall bench the index alone did as well (docs)
        profile = profile_path()
        pairs = relevant_lines(profile, prompt)
        if pairs:
            stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                            "additionalContext": render(pairs)}}))
    except Exception:  # never block or break a prompt
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
