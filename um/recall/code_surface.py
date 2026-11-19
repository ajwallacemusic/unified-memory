"""State canaries to, or probe, the two Claude Code surfaces with non-interactive runs.

    python -m um.recall.code_surface state  code:unified-memory
    python -m um.recall.code_surface probe  code:home

Non-interactive Claude Code stands in for an interactive session.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from um.llm_sub import subscription_env
from um.recall.canaries import CANARIES

REPO = Path(__file__).resolve().parents[2]
CWD = {"code:unified-memory": REPO, "code:home": Path.home()}
RAW = REPO / "results" / "recall" / "raw"
MODEL = "sonnet"

PROBE_INTRO = ("Answer each question from what you already know about me. Do not search the web or my files "
               "beyond your own memory. If you do not know, answer UNKNOWN. Reply as a numbered list with only "
               "the answers.\n\n")


class ProbeError(Exception):
    """The Claude Code call failed, so its reply says nothing about what the surface knows."""


def ask(prompt: str, cwd: Path, extra: list[str], runner=subprocess.run) -> str:
    cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json", *extra]
    proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=600, cwd=cwd, env=subscription_env())
    if proc.returncode != 0:
        raise ProbeError(f"exit {proc.returncode}: {proc.stderr[:300]}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as e:
        raise ProbeError(f"unreadable output: {proc.stdout[:200]!r}") from e
    if data.get("is_error") or "result" not in data:
        raise ProbeError(str(data.get("result") or data.get("subtype") or "error")[:300])
    return data["result"]


def probe_prompt(surface: str, only: set[str] | None = None) -> tuple[str, list]:
    others = [c for c in CANARIES if c.stated_on != surface and (only is None or c.id in only)]
    return PROBE_INTRO + "\n".join(f"{n}. {c.question}" for n, c in enumerate(others, 1)), others


def main() -> None:
    action, surface = sys.argv[1], sys.argv[2]
    RAW.mkdir(parents=True, exist_ok=True)
    tag = surface.replace(":", "_")
    if action == "state":
        for c in (c for c in CANARIES if c.stated_on == surface):
            out = ask(c.statement, CWD[surface], ["--permission-mode", "acceptEdits"])
            (RAW / f"state_{tag}_{c.id}.txt").write_text(out)
            print(c.id, "stated;", len(out), "chars of reply")
    elif action == "probe":
        only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
        prompt, others = probe_prompt(surface, only)
        out = ask(prompt, CWD[surface], [])
        (RAW / f"probe_{tag}.txt").write_text(out)
        for c in others:
            print(json.dumps({"canary_id": c.id, "stated_on": c.stated_on, "probed_on": surface, "hit": c.token in out}))
    else:
        raise SystemExit("usage: python -m um.recall.code_surface state|probe SURFACE")


if __name__ == "__main__":
    main()
