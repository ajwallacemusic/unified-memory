# Reproducing the numbers

Two kinds of reproduction are possible:

1. **Recompute** every published number from the published result rows. No model calls, no cost, a few
   seconds. Section 2.
2. **Re-run** a benchmark. This calls Claude models, so answers will differ from run to run. Sections 3 to 6.

Commands run from the repository root. [RESULTS.md](RESULTS.md) explains what each number means.

## 1. Set-up

```sh
git clone https://github.com/ajwallacemusic/unified-memory
cd unified-memory
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

Python 3.10 or later. The tests use no network and no model.

Re-running a benchmark also needs some of the following. Each section says which.

- **The `claude` CLI, logged in.** Recall-bench sessions and all "subscription" calls go through `claude -p`.
- **An API key.** `ANTHROPIC_API_KEY` in the environment or in a `.env` file in the repository root. Calls
  through the API are metered in a local ledger (`results/spend.jsonl`, created on first use) and stop at the
  dollar cap you pass.
- **A plan-usage file.** The runners that mix subscription and API calls send work to the subscription only
  while a usage file says plan usage is under a ceiling (70% by default). The author's machine writes that
  file from a status line; yours will not have it. The file looks like this, and a sample older than 15
  minutes counts as missing:

  ```json
  {"samples": [{"t": 1763570000000, "u": {"fh": 0, "sd": 0}}]}
  ```

  `t` is epoch milliseconds; `fh` and `sd` are five-hour and seven-day usage percentages. To keep a fresh one
  while a run is going:

  ```sh
  while true; do
    python3 -c 'import json,time; print(json.dumps({"samples":[{"t":int(time.time()*1000),"u":{"fh":0,"sd":0}}]}))' > /tmp/um-usage.json
    sleep 300
  done &
  ```

  This tells the runner your usage is 0%, so it will not stop on its own. The gate was checked with a
  hand-written file like this one; no full benchmark run was repeated that way.

Model ids used: `claude-haiku-5-5` and `claude-sonnet-5-5`. The recall bench passes Claude Code's `sonnet`
alias for the answering model instead, and its result rows do not record the exact model id or the Claude
Code version.

## 2. Recompute from the published rows

### Charts and the PrefEval and recall-bench tables

```sh
python3 scripts/make_charts.py
```

Standard library only. It reads

- `results/public-bench/2026-11-19-prefeval-100/results.jsonl`
- `results/recall-bench/2026-11-19-e2e-summary.json`
- `results/recall-bench/2026-11-19-implicit-summary.json`

writes `docs/prefeval.svg` and `docs/recall-bench.svg`, and prints every number it draws: counts, Wilson
intervals, mean input tokens, cut-off and empty answers, and the PrefEval paired differences (bootstrap,
10,000 resamples, seed 0). Use `--out DIR` to write the SVGs somewhere else.

### Recall bench

The summaries are computed from the row files beside them (`*.jsonl`, one row per question and setup). To
check the data itself, and to recompute the hook's offline retrieval numbers:

```sh
.venv/bin/python -c "from pathlib import Path; from um.bench.recall_data import validate; print(validate(Path('bench/recall')))"
.venv/bin/python -m um.bench.retrieval_eval bench/recall test
.venv/bin/python -m um.bench.retrieval_eval bench/recall dev
```

The first prints `[]` when no question gives a free or ambiguous hit. The other two print the "after" rows of
`results/recall-bench/2026-11-19-retrieval.json` (test: recall 0.556, off-topic injection 0.15). The "before"
rows were produced with the hook as it was before expansion words and background weighting. That version is
not in this repository, so the "before" rows cannot be recomputed here.

### Replay

```sh
REPO=$PWD
mkdir -p /tmp/um-check/results
cp -R results/synth /tmp/um-check/results/synth
for d in 2026-11-10-plain 2026-11-10-absorb; do
  .venv/bin/python -m um.synth.report /tmp/um-check/results/synth/$d
done
(cd /tmp/um-check && "$REPO/.venv/bin/python" -m um.synth.stress_report \
  --runs results/synth/stress/runs.json --out stress.md)
```

`um.synth.report` rebuilds a report from the folder's `rows.jsonl` alone. It writes `report.md` into the
folder it reads, so it runs on a copy. `um.synth.stress_report` reads the folders named in `runs.json`
relative to the current directory, so it runs from the copy too.

The two seed-1 row files each hold 120 per-pass rows beside their 1,960 probe rows; the report reads both.
The stress and add-fix folders hold probe rows only.

What comes out, against the published files:

- **Seed 1.** The error-rate and paired-difference tables have the same counts and intervals as the published
  `report.md` files. The layout has gained an "erase leaks" column and a "stale served" row per comparison.
- **Passes.** For seed 1 the per-arm table of outcomes, tokens and dollars and the number of questions B asked
  rebuild from the per-pass rows. B's change-decision table needs per-week pass records that are not
  published, so it is only in the committed `report.md` files. Folders with no per-pass rows say so in one line.
- **Stress.** The same as `results/synth/stress/report.md`, except one line of its limits list that has been
  reworded since.

`results/synth/addfix/report.md` is a summary assembled from the six row files in that folder. To recompute
its counts, run `um.synth.report` on a copy of each subfolder in the same way.

### LongMemEval-S

```sh
cp -R results/longmemeval/2026-11-10 /tmp/um-check/lme
.venv/bin/python -m um.bench.report /tmp/um-check/lme
```

Rebuilds the report from `results.jsonl`. Only the title line differs from the published one.

### Public-benchmark pilot

```sh
mkdir -p /tmp/um-check/pilot
cp -R results/public-bench/2026-11-19-pilot/prefeval results/public-bench/2026-11-19-pilot/longmemeval \
      results/public-bench/2026-11-19-pilot/mab /tmp/um-check/pilot/
.venv/bin/python -m um.bench.public.report /tmp/um-check/pilot
```

Writes `summary.json` with the same per-condition counts as the published one. The `compile` blocks will be
empty: they are read from the runs' working folders, which are not published.

## 3. Re-run PrefEval

Needs: the PrefEval repository, an API key (answers and judging), the `claude` CLI (compiles), a usage file.

```sh
git clone https://github.com/amazon-science/PrefEval data/public/prefeval
```

The published run used commit `50795054b5ff`. PrefEval is CC BY-NC 4.0; `data/` is git-ignored and nothing
from it is copied into this repository.

The command that produced the published results, as recorded in `run_meta.json`:

```sh
.venv/bin/python -m um.bench.public.run --bench prefeval --n 100 \
  --out results/public-bench/2026-11-19-prefeval-100 --api-cap 35 --workers 4
```

To run it yourself, change `--out` to a new folder (a finished item is never run again, so the command above
does nothing against the published folder), add `--usage-file /tmp/um-usage.json`, and set `--api-cap` to
what you are willing to spend. The published run cost $0.65 through the API and took 24 minutes. Defaults
that matter: `--seed 20261119`, `--inter-turns 10`, `--answer-model claude-haiku-5-5`,
`--judge-model claude-haiku-5-5`, `--compile-model claude-sonnet-5-5`, and `--cap-floor 100000`, which lifts
the compile's per-pass change cap (the plugin's default is 5).

The run writes `results.jsonl` (one row per item and condition), `run_meta.json`, and a git-ignored `stores/`
folder with each item's evidence, compile record and profile. Then:

```sh
python3 scripts/make_charts.py --prefeval results/public-bench/YOUR-RUN/results.jsonl --out /tmp/um-check
```

This prints the table for your run and writes its chart to `/tmp/um-check` instead of over the published one.

The per-profile figures quoted in RESULTS.md (how many profiles were empty, how many lines were labelled
standing, how often the hook matched) come from `stores/`. After your own run:

```sh
.venv/bin/python - <<'EOF'
import collections, json
from pathlib import Path
from um.bench.public import pipeline as pl, prefeval as pe
from um.hooks.profile_context import relevant_lines
from um.standing import standing_lines

out = Path("results/public-bench/YOUR-RUN")
items = {i.id: i for i in pe.load(Path("data/public/prefeval"))}
tally = collections.Counter()
for iid in json.loads((out / "run_meta.json").read_text())["invocations"][0]["items"]:
    prof = out / "stores" / iid.replace(":", "-") / "b" / "profile"
    lines = sum(len(pl.fact_lines(f.read_text())) for f in prof.rglob("*.md"))
    tally[(f"{lines} line(s)", "standing" if standing_lines(prof) else "not standing",
           "hook matched" if relevant_lines(prof, items[iid].question) else "hook did not match")] += 1
for key, n in sorted(tally.items()):
    print(n, *key)
EOF
```

On the published run this prints 4 profiles with 0 lines, 23 one-line standing profiles the hook matched, and
73 it did not.

## 4. Re-run the recall bench

Needs: the `claude` CLI, logged in. No API key. Every call goes through `claude -p`, including the
implicit-task judge.

The runner does not record its command line. These are the commands for the two published runs, as given by
the runner's flags and the published output files:

```sh
# RESULTS.md 2.1: questions, plus off-topic prompts under the index and hook setups
.venv/bin/python -m um.bench.recall_run --split test --model sonnet \
  --out results/recall-bench/2026-11-19-e2e

# RESULTS.md 2.2: implicit tasks, judged by Claude Haiku 5.5
.venv/bin/python -m um.bench.recall_run --set implicit --split test --model sonnet \
  --out results/recall-bench/2026-11-19-implicit
```

To run it yourself, change `--out` to a new name. A rerun with the same `--out` resumes and retries only
failed rows, so against the published files it starts no session.

Each command runs all five setups: `none`, `index`, `full`, `standing` and `hook` (`--conditions` picks a
subset). Each writes `<out>.jsonl`, `<out>-summary.json` and, for question runs, `<out>-offtopic.jsonl`.
Defaults: `--split test`, `--model sonnet`, `--workers 4`, scratch folders under `/tmp/um-recall-runs`.

Things to know:

- **Runs pause at 70% plan usage, but only if a usage file exists.** The file is `--usage-file`, by default
  `~/.claude/usage-now.json`, in the format shown in section 1. While five-hour or seven-day usage is at 70%
  or more, the runner starts no session and records the row as an error; the same command picks those rows up
  later. A file whose newest sample is older than 15 minutes counts as over the limit, so nothing runs. With
  no file there is no pause. The published runs were made in more than one sitting for this reason.
- **The hook setup includes the standing list.** `standing` is the index plus the standing list. `hook` is
  `standing` plus the prompt hook. Both are built by `um/bench/cc_run.py` from the labels and expansion words
  in `bench/recall/profile/.um/`, so both can be rebuilt from this repository.
- **Your own config can switch the hook off.** The hook reads `~/.config/unified-memory/config.json`. If you
  have installed the plugin and that file says `"prompt_hook": false`, the hook setup will silently behave
  like the standing setup. Run the bench with `UM_CONFIG=/nonexistent` in the environment to rule that out.
- **Isolation, and how it failed once.** Sessions run in a scratch folder that is not a git repository, with
  `--setting-sources project`, `--strict-mcp-config`, `GIT_CONFIG_GLOBAL=/dev/null`, no stdin, and
  `--tools Read,Glob,Grep`. The profile folder is added with `--add-dir` only for the setups meant to read
  it. The first runs of this bench also passed `--allowedTools Read,Glob,Grep`, which let a session read any
  file on the machine. Those rows were withdrawn and are not published, the flag was removed, and the bench
  was rerun. After the fix, a read of the parent folder was checked by hand and was denied. That check was
  made once, in November 2026, against the Claude Code version installed that day. The unit test checks only
  that the flag is absent. One known leak remains: the account email of the person running the bench reaches
  the session.
- **Check the floor first.** Run `--conditions none` before reading anything else. If "no profile" scores
  above zero on questions, isolation has failed on your machine. A zero does not prove isolation. Also ask
  one session to read a file in the parent of its scratch folder and confirm that the read is denied.
- **Variants with no published result.** The runner also accepts `--model haiku`, `--batch N` (several
  questions per session) and `--project-md FILE` (sessions inside a project). Runs with those flags were made
  before the isolation fix, withdrawn, and not rerun.

## 5. Re-run the replay

Needs: an API key. If no usage file is found at `~/.claude/usage-now.json`, every call goes to the API.

```sh
# seed 1, both writers (RESULTS.md section 3, first table)
.venv/bin/python -m um.synth.replay --users 5 --seed 20261110 --arms z,a0,a,b \
  --out results/synth/MY-plain --cap 24
.venv/bin/python -m um.synth.replay --users 5 --seed 20261110 --arms z,a0,a,b --writer absorb \
  --out results/synth/MY-absorb --cap 24
.venv/bin/python -m um.synth.report results/synth/MY-plain
.venv/bin/python -m um.synth.report results/synth/MY-absorb
```

`--cap` is the hard API cap in dollars across the whole ledger. The caps used for the published runs were not
recorded; each seed-1 run of four arms cost about $2 at November 2026 prices (the "Passes" table in each
report). Defaults: `--arm-model claude-sonnet-5-5`, `--small-model claude-haiku-5-5`, `--oracle always`.

Arm `a0` reads the text of Anthropic's `consolidate-memory` skill from a local Claude desktop install at run
time. The text is not in this repository. Without that install, leave `a0` out of `--arms`.

The stress runs use the same command with these changes (`results/synth/stress/runs.json` lists every run):

| Run | Change |
| --- | --- |
| second seed | `--seed 20261111 --arms z,a,b,b-nohook`, once per writer |
| no write-time hook | `--arms b-nohook`, once per writer |
| unanswered questions | `--arms b --oracle never`, `--oracle late`, `--oracle flaky`, once per writer |
| erase | `--arms z,a,b --erase-week 3`, plain writer |

Then write a `runs.json` in the same shape as the published one and run `um.synth.stress_report` as in
section 2. The generator is deterministic for a seed, so the users, facts, planted claims and probes will be
the same. The model outputs will not: on the same seed and writer, the do-nothing arm accepted 66, 81 and 85
of 90 planted claims in three published runs.

## 6. Re-run the other public benchmarks

### LongMemEval-S, 100 questions (RESULTS.md section 4)

Needs: an API key, and `longmemeval_s_cleaned.json` (277 MB, MIT) from the Hugging Face dataset
`xiaowu0162/longmemeval-cleaned`, saved under `data/public/longmemeval/`.

```sh
.venv/bin/python -m um.bench.run --data data/public/longmemeval/longmemeval_s_cleaned.json \
  --out results/longmemeval/MY-RUN --arms z,a0,a,full,files --n 100 --cap 12
.venv/bin/python -m um.bench.report results/longmemeval/MY-RUN
```

This is the documented form of the command; the exact command lines of the two published invocations were
not recorded. This runner sends single-shot calls to the subscription when it finds a fresh usage file, by
default the Claude desktop app's own; pass `--usage-file` to choose the file, or point it at a missing path to
send everything to the API.

The published run cost $7.40 through the API for `z`, `a0`, `a` and `files`. Its `full` arm ran through a
subscription; through the API, full-context prompts exceed 100,000 tokens each and 20 of them cost $1.69.
Arm `a0` has the same local-install requirement as in section 5.

### LongMemEval-S and FactConsolidation pilots (RESULTS.md sections 4 and 5)

Needs: an API key, the `claude` CLI, a usage file.

```sh
.venv/bin/python -m um.bench.public.run --bench longmemeval --n 10 \
  --out results/public-bench/MY-pilot/longmemeval --api-cap 5 --workers 3 --usage-file /tmp/um-usage.json
.venv/bin/python -m um.bench.public.run --bench mab --n 10 \
  --out results/public-bench/MY-pilot/mab --api-cap 5 --workers 4 --usage-file /tmp/um-usage.json
.venv/bin/python -m um.bench.public.report results/public-bench/MY-pilot
```

These pilots ran before the hook condition was changed (RESULTS.md section 1), so a re-run will build that
condition differently.

The FactConsolidation runner expects `data/public/memoryagentbench/conflict_resolution.json`: the rows of the
`Conflict_Resolution` split of the Hugging Face dataset `ai-hyz/MemoryAgentBench` (MIT) as one JSON list, each
row with `context`, `questions`, `answers` and `metadata` (`source`, `qa_pair_ids`). The dataset ships that
split as a parquet file. The script that converted it is not in this repository.

The "newest matching statement wins" figure (97 of 100) needs that file and no model:

```sh
.venv/bin/python - <<'EOF'
from pathlib import Path
from um.bench.public import mab

ctx = mab.load(Path("data/public/memoryagentbench/conflict_resolution.json"), "factconsolidation_sh_6k")
hits = sum(mab.sub_em(mab.last_write(ctx, it.question), it.answers) for it in ctx.items)
print(hits, "of", len(ctx.items))
EOF
```

## 7. What cannot be reproduced from this repository

- The recall across surfaces on a real account. It is not published.
- Any run on real stores.
- The per-item working folders (`stores/`) of the published public-benchmark runs, and so the compile
  figures in RESULTS.md section 1 and the `compile` blocks of the pilot summary. A re-run produces its own.
- The week-by-week stores of the replay runs. The row files are published; the stores are not.
- The hook as it was before expansion words and background weighting ("before" in the retrieval table).
- The withdrawn recall-bench runs: the first runs, and the Claude Haiku, batched and in-project variants.
  Their rows are not published.
- The "Passes" section of the replay reports (see section 2).
- Exact answers. Every re-run samples new model outputs, and no run here fixed a temperature or a model
  snapshot beyond the ids named above.
