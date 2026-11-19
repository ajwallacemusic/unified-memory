"""Draw the two result charts as SVG, from the results files, with the standard library only.

    python3 scripts/make_charts.py [--out DIR] [--prefeval RESULTS.jsonl]

Reads
    results/public-bench/2026-11-19-prefeval-100/results.jsonl
    results/recall-bench/2026-11-19-e2e-summary.json
    results/recall-bench/2026-11-19-implicit-summary.json
and writes prefeval.svg and recall-bench.svg to DIR (default: docs/public if that folder exists, else docs).
It also prints every number it draws, with 95% Wilson intervals and the paired differences quoted in the docs,
so the tables in RESULTS.md can be checked against the files with one command.

Each SVG carries its own surface and switches to dark colours under `prefers-color-scheme: dark`, so it stays
readable on a light or a dark page. Colours are two validated categorical slots (blue, orange); shape repeats
the distinction (circle, square), and every mark has a text label.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
PREFEVAL = ROOT / "results/public-bench/2026-11-19-prefeval-100/results.jsonl"
RECALL_Q = ROOT / "results/recall-bench/2026-11-19-e2e-summary.json"
RECALL_I = ROOT / "results/recall-bench/2026-11-19-implicit-summary.json"

W = 760
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
STYLE = """
  .surface { fill: #fcfcfb; stroke: #e1e0d9; }
  .ink { fill: #0b0b0b; }
  .ink2 { fill: #52514e; }
  .muted { fill: #898781; }
  .grid { stroke: #e1e0d9; stroke-width: 1; }
  .axis { stroke: #c3c2b7; stroke-width: 1; }
  .lead { stroke: #898781; stroke-width: 1; }
  .ours { fill: #2a78d6; stroke: #fcfcfb; stroke-width: 2; }
  .base { fill: #eb6834; stroke: #fcfcfb; stroke-width: 2; }
  .ours-ci { stroke: #2a78d6; stroke-width: 2; stroke-linecap: round; }
  .base-ci { stroke: #eb6834; stroke-width: 2; stroke-linecap: round; }
  text { font-family: %s; }
  .t { font-size: 16px; font-weight: 600; }
  .s { font-size: 12.5px; }
  .l { font-size: 13px; }
  .k { font-size: 12px; }
  .h { font-size: 13px; font-weight: 600; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; stroke: #2c2c2a; }
    .ink { fill: #f0efec; }
    .ink2 { fill: #c3c2b7; }
    .grid { stroke: #2c2c2a; }
    .axis { stroke: #383835; }
    .ours { fill: #3987e5; stroke: #1a1a19; }
    .base { fill: #d95926; stroke: #1a1a19; }
    .ours-ci { stroke: #3987e5; }
    .base-ci { stroke: #d95926; }
  }
""" % FONT


# ---------------------------------------------------------------- statistics (same as um/bench/stats.py)

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (0.0 if k == 0 else max(0.0, centre - half), 1.0 if k == n else min(1.0, centre + half))


def paired_diff(a: list[bool], b: list[bool], n_boot: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    diffs = [int(x) - int(y) for x, y in zip(a, b)]
    n = len(diffs)
    point = sum(diffs) / n
    if not any(diffs):
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_boot))
    return (point, means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))])


# ---------------------------------------------------------------- data

PREFEVAL_ROWS = (  # condition in the file, label on the chart, class
    ("none", "No memory", "base"),
    ("raw-retrieval", "BM25 over raw turns", "base"),
    ("full-history", "Full history", "base"),
    ("profile-full", "Compiled profile, all lines", "ours"),
    ("profile-hook", "Compiled profile, index view + hook", "ours"),
)
PREFEVAL_PAIRS = (("profile-hook", "raw-retrieval"), ("profile-full", "raw-retrieval"),
                  ("profile-hook", "full-history"), ("profile-full", "full-history"),
                  ("profile-hook", "profile-full"))


def prefeval(path: Path = PREFEVAL) -> dict:
    by: dict[str, dict[str, dict]] = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            by.setdefault(r["condition"], {})[r["item"]] = r
    out = {"conditions": {}, "pairs": {}}
    for cond, rows in by.items():
        n, k = len(rows), sum(bool(r["correct"]) for r in rows.values())
        lo, hi = wilson(k, n)
        out["conditions"][cond] = {
            "n": n, "k": k, "rate": k / n, "lo": lo, "hi": hi,
            "mean_input_tokens": sum(r["input_tokens"] for r in rows.values()) / n,
            "cut_off": sum(r["outcome"] == "max_tokens" for r in rows.values()),
            "empty": sum(not (r.get("answer") or "").strip() for r in rows.values()),
            "no_context": sum(r["context_chars"] == 0 for r in rows.values()),
        }
    items = sorted(by["none"])
    for a, b in PREFEVAL_PAIRS:
        out["pairs"][(a, b)] = paired_diff([bool(by[a][i]["correct"]) for i in items],
                                           [bool(by[b][i]["correct"]) for i in items])
    return out


RECALL_ROWS = (("none", "No profile"), ("index", "Index"), ("standing", "Index + standing list"),
               ("hook", "Index + standing list + hook"), ("full", "Whole profile in CLAUDE.md"))
RECALL_Q_ROWS = RECALL_I_ROWS = RECALL_ROWS  # both published runs have all five setups


def recall(path: Path) -> dict:
    return json.loads(path.read_text())["conditions"]


# ---------------------------------------------------------------- drawing

def _t(x: float, y: float, text: str, cls: str, anchor: str = "start") -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}"{a}>{text}</text>'


def _open(h: int, title: str, desc: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" '
            f'aria-labelledby="t d">',
            f'<title id="t">{escape(title)}</title>', f'<desc id="d">{escape(desc)}</desc>',
            f'<style>{STYLE}</style>',
            f'<rect class="surface" x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="8"/>']


def _pct(v: float) -> str:
    return f"{100 * v:.0f}%"


def prefeval_svg(d: dict) -> str:
    h = 456
    x0, x1, y0, y1 = 64, 728, 112, 392          # plot box
    lo_t, hi_t = 40, 10_000

    def px(tokens: float) -> float:
        return x0 + (x1 - x0) * math.log10(tokens / lo_t) / math.log10(hi_t / lo_t)

    def py(rate: float) -> float:
        return y1 - (y1 - y0) * rate

    c = d["conditions"]
    desc = "; ".join(f"{label}: {_pct(c[k]['rate'])} at {c[k]['mean_input_tokens']:.0f} mean input tokens"
                     for k, label, _ in PREFEVAL_ROWS)
    o = _open(h, "PrefEval: preference-following against context size", desc)
    o.append(_t(24, 34, "PrefEval: preference-following against context size", "t ink"))
    o.append(_t(24, 54, "100 items (5 per topic), explicit preferences, 10 inter-turns. Claude Haiku 5.5 answers and "
                        "judges.", "s ink2"))
    o.append(_t(24, 71, "Lines are 95% Wilson intervals.", "s ink2"))
    # legend
    o.append(f'<circle class="ours" cx="{x1 - 250}" cy="88" r="6"/>')
    o.append(_t(x1 - 238, 92.5, "Compiled profile", "k ink2"))
    o.append(f'<rect class="base" x="{x1 - 124}" y="82" width="12" height="12" rx="2"/>')
    o.append(_t(x1 - 106, 92.5, "Baselines", "k ink2"))
    o.append(_t(x0, 98, "Preference-following", "k muted"))
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        o.append(f'<line class="{"axis" if v == 0 else "grid"}" x1="{x0}" x2="{x1}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>')
        o.append(_t(x0 - 8, py(v) + 4, _pct(v), "k muted", "end"))
    for tk in (50, 100, 200, 500, 1000, 2000, 5000, 10_000):
        o.append(f'<line class="axis" x1="{px(tk):.1f}" x2="{px(tk):.1f}" y1="{y1}" y2="{y1 + 5}"/>')
        o.append(_t(px(tk), y1 + 20, f"{tk:,}", "k muted", "middle"))
    o.append(_t((x0 + x1) / 2, y1 + 44, "Mean input tokens per answer (log scale)", "k muted", "middle"))
    for key, _, cls in PREFEVAL_ROWS:   # intervals under the markers
        v = c[key]
        x = px(v["mean_input_tokens"])
        o.append(f'<line class="{cls}-ci" x1="{x:.1f}" x2="{x:.1f}" y1="{py(v["lo"]):.1f}" y2="{py(v["hi"]):.1f}"/>')
    for key, _, cls in PREFEVAL_ROWS:
        v = c[key]
        x, y = px(v["mean_input_tokens"]), py(v["rate"])
        if cls == "ours":
            o.append(f'<circle class="ours" cx="{x:.1f}" cy="{y:.1f}" r="6"/>')
        else:
            o.append(f'<rect class="base" x="{x - 5.5:.1f}" y="{y - 5.5:.1f}" width="11" height="11" rx="2"/>')

    def label(key: str, text: str, x: float, y: float, anchor: str = "start") -> None:
        v = c[key]
        o.append(f'<text x="{x:.1f}" y="{y:.1f}" class="l ink"' + (f' text-anchor="{anchor}"' if anchor != "start" else "")
                 + f'>{escape(text)} <tspan class="h">{_pct(v["rate"])}</tspan></text>')

    n, r, f_, pf, ph = (c[k] for k in ("none", "raw-retrieval", "full-history", "profile-full", "profile-hook"))
    label("none", "No memory", px(n["mean_input_tokens"]) + 13, py(n["rate"]) + 4.5)
    label("raw-retrieval", "BM25 over raw turns", px(r["mean_input_tokens"]) + 13, py(r["rate"]) + 4.5)
    label("full-history", "Full history", px(f_["mean_input_tokens"]) - 13, py(f_["rate"]) + 22, "end")
    xr = px(pf["mean_input_tokens"]) + 14
    label("profile-full", "Profile, all lines", xr, py(pf["rate"]) - 2)
    yh = py(ph["rate"]) + 24
    xh, yhp = px(ph["mean_input_tokens"]), py(ph["rate"])
    o.append(f'<line class="lead" x1="{xh + 5:.1f}" y1="{yhp + 6:.1f}" x2="{xr - 4:.1f}" y2="{yh - 5:.1f}"/>')
    label("profile-hook", "Profile, index view + hook", xr, yh)
    o.append("</svg>")
    return "\n".join(o) + "\n"


def recall_svg(q: dict, i: dict) -> str:
    row_h, lab_x, x0, x1, val_x = 30, 24, 268, 628, 736
    panels = (("Questions about the user", "45 held-out questions, one session each; a hit is an answer term in "
               "the reply", RECALL_Q_ROWS, q),
              ("Tasks that never ask about the user", "20 held-out tasks; Claude Haiku 5.5 judges whether the "
               "reply respected the stored fact", RECALL_I_ROWS, i))
    h = 96 + sum(64 + row_h * len(p[2]) + 34 for p in panels) - 6
    desc = "; ".join(f"{title}: " + ", ".join(f"{lab} {c[k]['hits']}/{c[k]['n']}" for k, lab in rows)
                     for title, _, rows, c in panels)
    o = _open(h, "Claude Code recall bench, by setup", desc)
    o.append(_t(24, 34, "Claude Code recall bench, by setup", "t ink"))
    o.append(_t(24, 54, "Fictional user, 34 profile files. Isolated claude -p sessions, Claude Sonnet answers.",
                "s ink2"))
    o.append(_t(24, 71, "Dots are hit rates; lines are 95% Wilson intervals.", "s ink2"))

    def px(rate: float) -> float:
        return x0 + (x1 - x0) * rate

    y = 96
    for title, sub, rows, c in panels:
        o.append(_t(lab_x, y + 14, title, "h ink"))
        o.append(_t(lab_x, y + 32, sub, "k ink2"))
        top = y + 48
        bottom = top + row_h * len(rows)
        for v in (0, 0.25, 0.5, 0.75, 1.0):
            o.append(f'<line class="{"axis" if v == 0 else "grid"}" x1="{px(v):.1f}" x2="{px(v):.1f}" y1="{top}" '
                     f'y2="{bottom}"/>')
            o.append(_t(px(v), bottom + 16, _pct(v), "k muted", "middle"))
        for n_, (key, lab) in enumerate(rows):
            v = c[key]
            cy = top + row_h * n_ + row_h / 2
            lo, hi = wilson(v["hits"], v["n"])
            cls = "base" if key == "none" else "ours"
            o.append(_t(lab_x, cy + 4.5, escape(lab), "l ink"))
            o.append(f'<line class="{cls}-ci" x1="{px(lo):.1f}" x2="{px(hi):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
            if cls == "ours":
                o.append(f'<circle class="ours" cx="{px(v["rate"]):.1f}" cy="{cy:.1f}" r="6"/>')
            else:
                o.append(f'<rect class="base" x="{px(v["rate"]) - 5.5:.1f}" y="{cy - 5.5:.1f}" width="11" height="11" '
                         f'rx="2"/>')
            o.append(_t(val_x, cy + 4.5, f'{v["hits"]}/{v["n"]}', "h ink", "end"))
        y = bottom + 34 + 16
    o.append("</svg>")
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- report

def report(d: dict, q: dict, i: dict, source: Path = PREFEVAL) -> str:
    source = Path(source).resolve()
    out = [f"PrefEval ({source.relative_to(ROOT) if source.is_relative_to(ROOT) else source})",
           f"  {'condition':<14} {'correct':>8} {'95% Wilson':>12} {'mean input tokens':>18} {'cut off':>8} "
           f"{'empty':>6} {'no context':>11}"]
    for key, _, _ in PREFEVAL_ROWS:
        v = d["conditions"][key]
        out.append(f"  {key:<14} {v['k']:>4}/{v['n']:<3} {100 * v['lo']:>5.1f}-{100 * v['hi']:<5.1f} "
                   f"{v['mean_input_tokens']:>18.1f} {v['cut_off']:>8} {v['empty']:>6} {v['no_context']:>11}")
    out.append("  paired differences, percentage points (bootstrap, 10,000 resamples, seed 0)")
    for (a, b), (p, lo, hi) in d["pairs"].items():
        out.append(f"  {a} minus {b}: {100 * p:+.0f} [{100 * lo:+.0f}, {100 * hi:+.0f}]")
    for name, path, rows, c in (("questions", RECALL_Q, RECALL_Q_ROWS, q), ("implicit tasks", RECALL_I, RECALL_I_ROWS, i)):
        out += ["", f"Recall bench, {name} ({path.relative_to(ROOT)})"]
        for key, lab in rows:
            v = c[key]
            lo, hi = wilson(v["hits"], v["n"])
            out.append(f"  {key:<9} {v['hits']:>3}/{v['n']:<3} {100 * lo:>5.1f}-{100 * hi:<5.1f} "
                       f"mean input tokens {v['mean_input_tokens']:>8.0f}   {lab}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None, help="folder for the SVGs (default: docs/public, else docs)")
    ap.add_argument("--prefeval", type=Path, default=PREFEVAL, help="results.jsonl of a PrefEval run")
    a = ap.parse_args(argv)
    out = a.out or (ROOT / "docs/public" if (ROOT / "docs/public").is_dir() else ROOT / "docs")
    out.mkdir(parents=True, exist_ok=True)
    d, q, i = prefeval(a.prefeval), recall(RECALL_Q), recall(RECALL_I)
    (out / "prefeval.svg").write_text(prefeval_svg(d))
    (out / "recall-bench.svg").write_text(recall_svg(q, i))
    print(report(d, q, i, a.prefeval))
    print(f"\nwrote {out / 'prefeval.svg'}\nwrote {out / 'recall-bench.svg'}")


if __name__ == "__main__":
    main()
