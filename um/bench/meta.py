"""What a run_meta.json invocation may record: facts about the run, not the author's plan usage or total spend."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PRIVATE_FIELDS = frozenset({
    "cap_usd", "sub_ceiling_pct", "usage_before", "usage_after", "gate_open_at_start",
    "api_usd_total", "api_usd_ledger_before", "api_usd_ledger_after",
})
_PRIVATE_FLAGS = ("--api-cap", "--cap", "--ledger", "--usage-file", "--sub-ceiling")


def _scrub_argv(argv: list[str]) -> list[str]:
    out, skip = [], False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in _PRIVATE_FLAGS:
            skip = True
            continue
        if tok.startswith(tuple(f + "=" for f in _PRIVATE_FLAGS)):
            continue
        out.append(_unhome(tok))
    return out


def _unhome(tok: str) -> str:
    """Absolute paths name the author's home folder: repo paths become relative, others start at <home>."""
    repo, home = str(REPO) + "/", str(Path.home())
    return tok.replace(repo, "").replace(home, "<home>")


def public_invocation(inv: dict, spent_before: float | None = None, spent_after: float | None = None) -> dict:
    """Drop plan-usage and ledger fields; record only this run's own API cost."""
    out = {k: v for k, v in inv.items() if k not in PRIVATE_FIELDS}
    if "argv" in out:
        out["argv"] = _scrub_argv(list(out["argv"]))
    if spent_before is not None and spent_after is not None:
        out["api_usd_this_run"] = round(spent_after - spent_before, 4)
    return out
