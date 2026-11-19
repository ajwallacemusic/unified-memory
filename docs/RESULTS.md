# Results

Everything measured for Unified Memory between November 10 and 19, 2026, with the file each number comes from.
[BENCHMARKS.md](BENCHMARKS.md) has the commands. Paths are relative to the repository root.

Conventions:

- Intervals in square brackets are 95% Wilson intervals on a proportion.
- Differences are in percentage points, paired on the same items, with a 95% bootstrap interval. An interval
  that contains zero is reported as a tie.
- "Sonnet" and "Haiku" mean Claude Sonnet 5.5 and Claude Haiku 5.5 unless a section says otherwise.
- Every benchmark here was built, run and scored with Claude models. Section 7 says who wrote which labels.
  Section 8 lists what was not run.

## Summary

| # | Benchmark | n | Compared | Result |
| --- | --- | --- | --- | --- |
| 1 | PrefEval, explicit preferences (public) | 100 items | compiled profile, BM25 over raw turns, full history, no memory | Profile 96%; BM25 75%; full history 99%; none 13%. Profile beats BM25 (+21 [+12, +30]) and ties full history (-3 [-7, +1]). |
| 2 | Claude Code recall bench (ours, fictional user) | 45 questions, 20 implicit tasks | no profile, index, index + standing list, index + standing list + hook, whole profile | Index 45/45 and 17/20. Whole profile 45/45 and 19/20. Standing list 44/45 and 19/20. Hook 44/45 and 19/20. No profile 0/45 and 2/20. The standing list and the hook add nothing measurable. |
| 3 | Replay (ours, synthetic) | 490 probes per arm and run | do nothing (Z), two clean-up passes (A0, A), checked compile (B) | Combined error Z 90/490, A0 122/490, A 101/490, B 0/490 on seed 1. B beats Z on a second seed too. |
| 4 | LongMemEval-S (public) | 100 questions | Z, A0, A, full context, raw files with search | Z 82%, A 82%, A0 76%, full context 91%, files 85%. B was not run. |
| 5 | MemoryAgentBench FactConsolidation (public) | 10 questions (pilot) | same as 1 | Out of scope. The profile stored nothing. |

## 1. PrefEval

PrefEval (Zhao et al., ICLR 2025) tests whether an assistant follows a preference the user stated earlier in
a conversation. We used the explicit-preference subset and the generation task. The dataset is CC BY-NC 4.0.
This repository holds results only; the data and the judge prompts are read at run time from a local clone
and are not redistributed.

Source: `results/public-bench/2026-11-19-prefeval-100/results.jsonl` (500 rows: 100 items by 5 conditions) and
`run_meta.json` beside it. `python3 scripts/make_charts.py` prints the table below from that file.

**Set-up.** 100 items, 5 from each of the 20 topics, drawn with a fixed seed. The history is the stated
preference, the assistant's reply to it, and 10 unrelated exchanges ("inter-turns"). Haiku answered and ran
PrefEval's four judge checks. For the two profile conditions, Sonnet first compiled the history into a profile
with the same compile and checks the plugin uses, starting from an empty profile.

| Condition | What the answer model is given | Following the preference | 95% interval | Mean input tokens | Answers cut off |
| --- | --- | --- | --- | --- | --- |
| No memory | nothing | 13/100 | 8 to 21 | 56 | 9 |
| BM25 over raw turns | best-matching lines of the raw conversation, up to 4,000 characters | 75/100 | 66 to 82 | 651 | 29 |
| Compiled profile, all lines | every line of the compiled profile | 96/100 | 90 to 98 | 121 | 43 |
| Compiled profile, index view + hook | what a Claude Code session has before it opens a file: core lines, standing lines, and lines the prompt hook matches | 93/100 | 86 to 97 | 106 | 47 |
| Full history | the whole conversation | 99/100 | 95 to 100 | 5,850 | 59 |

Paired differences:

| Comparison | Difference | 95% interval | Reading |
| --- | --- | --- | --- |
| Profile, all lines, minus BM25 | +21 | +12 to +30 | profile better |
| Profile, index view + hook, minus BM25 | +18 | +8 to +28 | profile better |
| Profile, all lines, minus full history | -3 | -7 to +1 | tie |
| Profile, index view + hook, minus full history | -6 | -12 to -1 | profile worse |
| Profile, index view + hook, minus profile, all lines | -3 | -7 to 0 | tie |

![PrefEval: preference-following against mean input tokens per answer](prefeval.svg)

**What this shows.** A one-line compiled profile carries a stated preference about as well as the whole
conversation does, in about 2% of the answer's input tokens, and better than word-matching retrieval over the
raw turns.

**What it does not show, and what differs from the paper.**

- **Context placement.** Every condition gets its context inside the system prompt. PrefEval presents the
  history as earlier chat turns. A transcript in the system prompt is probably easier to use, which likely
  inflates the full-history score.
- **Only 10 inter-turns.** The history is about 5,800 tokens, so full history is an easy baseline here.
  PrefEval's 300 inter-turn setting was not run.
- **Judge.** Haiku 5.5 ran the four checks, not the judge model used in the paper. These numbers are not
  comparable with published PrefEval scores.
- **Output limit.** Answers could use 1,000 output tokens (PrefEval: 300), because Haiku 5.5 spends part of
  its output budget before it writes and answers at 300 were cut off in a pilot. Many answers still hit the
  limit (last column). A cut-off answer was judged as it stood. Three answers were empty at the limit, one
  under BM25 and two under the index view + hook condition; they count as failures and were not judged.
- **Four compiles stored nothing.** For 4 of 100 items the compile proposed no change, so both profile
  conditions answered with no context. These are all four failures of the all-lines condition.
- **The index view + hook number is not evidence for the hook's retrieval.** In this run every stored
  preference was labelled a standing line (96 of 96), so it was in context whether or not the hook matched.
  Recomputed offline from the run's profiles, the hook's word match fired for 23 of the 96. The three items
  where this condition trails the all-lines condition are the two empty answers and one cut-off answer.
- **The index view + hook condition is not the plugin's default.** It has the standing list and the prompt
  hook switched on. The plugin ships with both off (section 2.5).
- **The condition was changed after a pilot.** In a 20-item pilot
  (`results/public-bench/2026-11-19-pilot/summary.json`) the condition was core lines plus hook matches, with
  no standing lines and no expansion words. It put nothing in context and scored 6/20. It was then changed
  to the index view described above. One of the pilot's 20 items is also in the 100-item sample.
- **The change cap was lifted.** The compile ran with its per-pass cap on changes effectively off. No compile
  in this run proposed more than one change, so the plugin's default cap would have held nothing back.
- **Token counts are for the answer call.** They exclude the compile, which is one Sonnet call per history
  (about 7,700 input tokens each in this run), and the judge calls.
- **One preference per item.** Each profile is one line. This says nothing about recall from a large profile;
  section 2 covers that.

The per-profile figures in this list (the four empty profiles, the standing labels, the hook matches and the
compile sizes) come from the run's working files, which sit beside benchmark text and are not published.
Answers and judging cost $0.65 through the API (the sum of the `usd` fields in the results file). Compiles
ran on a Claude subscription.

## 2. Claude Code recall bench

Our own benchmark. It asks whether Claude Code knows facts about its user when those facts sit in a stored
profile. Data and scoring rules: [`bench/recall/README.md`](../bench/recall/README.md).

**The data.** A fictional user, Wren Halvorsen, with a profile of 34 files and 271 fact lines in the layout
of Claude's account memory. 90 questions (27 direct, 45 paraphrased, 18 that need two files), 40 off-topic
prompts and 40 implicit tasks, each split in half into dev and test. Retriever choices were tuned on dev.
Every number below is from the held-out test half.

**The sessions.** Each question runs in its own non-interactive Claude Code session (`claude -p`) in a scratch
folder, isolated from the runner's own settings, memory, plugins and MCP servers
(`um/bench/cc_run.py`). Only the Read, Glob and Grep tools exist. A session can read its own folder and, in
the three index setups, the profile folder. Claude Sonnet answered (the `sonnet` alias of Claude Code; the
exact model id is not recorded). The setups:

| Setup | What the session has |
| --- | --- |
| No profile | nothing |
| Index | `CLAUDE.md` holds the generated index: the core profile lines, then one line (path and description) per other profile file. The session may read those files. This is what the plugin ships. |
| Index + standing list | the index, plus the lines labelled as standing preferences listed inline (123 of the 263 labelled lines) |
| Index + standing list + hook | the standing setup, plus the prompt hook, which adds matching profile lines to the prompt |
| Whole profile | every profile file pasted into `CLAUDE.md` (the full-context baseline) |

Input tokens are what `claude -p` reports for the whole session, including Claude Code's own system prompt
and every turn. A session that opens a file has more turns, so it counts more tokens.

**These numbers are from a rerun.** The first runs of this bench, earlier on November 19, passed
`--allowedTools Read,Glob,Grep` to each session. That let a session read any file on the machine, not only
its own folder. Every row from those runs was withdrawn and none is published. The flag was removed, a read of
the parent folder was checked by hand and was denied, and the two runs below were repeated with the current
code. Each setup was run once.

### 2.1 Questions about the user

Source: `results/recall-bench/2026-11-19-e2e-summary.json` (rows in `2026-11-19-e2e.jsonl`). 45 questions:
13 direct, 23 paraphrased, 9 two-file. A hit is an answer term appearing in the reply.

| Setup | Hits | 95% interval | Mean input tokens |
| --- | --- | --- | --- |
| No profile | 0/45 | 0 to 8 | 8.0k |
| Index | 45/45 | 92 to 100 | 17.2k |
| Index + standing list | 44/45 | 88 to 100 | 23.7k |
| Index + standing list + hook | 44/45 | 88 to 100 | 17.8k |
| Whole profile | 45/45 | 92 to 100 | 16.2k |

The index ties the whole-profile baseline at the ceiling. Index minus hook is +2 points [0 to +7], a tie.
Standing list minus hook is 0. The standing and hook setups each missed one question, the same two-file
question. In both, the reply named the right person from the first file and said the fact held in the
second file was unknown. Every other cell is full marks, so 8 of 9 two-file questions for those two setups
and 9 of 9 for the index and the whole profile.

The hook setup used fewer input tokens than the standing setup (17.8k against 23.7k), although it holds
everything the standing setup holds. Tokens are counted over every turn, so this fits hook sessions opening
fewer files. The rows do not record which files a session opened, so this is not confirmed.

On the 20 off-topic test prompts (`2026-11-19-e2e-offtopic.jsonl`, index and hook setups only) the hook setup
used 27.9k mean input tokens against 17.4k for the index. The hook setup includes the standing list, and the
standing setup was not run on off-topic prompts, so the extra cannot be split between the two.

### 2.2 Tasks that never ask about the user

Source: `results/recall-bench/2026-11-19-implicit-summary.json` (rows in `2026-11-19-implicit.jsonl`). 20
tasks (10 work, 10 life), such as drafting, planning or writing code, where one stored fact should change the
answer and the prompt does not mention it. Haiku 5.5 (`claude-haiku-5-5`) judged each reply YES or NO against
a check question. Claude wrote the tasks and the check questions when it wrote the bench. No person reviewed
the checks or the verdicts.

| Setup | Passed | 95% interval | Mean input tokens |
| --- | --- | --- | --- |
| No profile | 2/20 | 3 to 30 | 7.0k |
| Index | 17/20 | 64 to 95 | 18.0k |
| Index + standing list | 19/20 | 76 to 99 | 25.7k |
| Index + standing list + hook | 19/20 | 76 to 99 | 25.1k |
| Whole profile | 19/20 | 76 to 99 | 19.8k |

The index is two tasks behind the other three profile setups, and the intervals overlap. Hook minus index is
+10 points [-10 to +30], a tie. Hook minus standing list and hook minus whole profile are both 0 [-15 to
+15]. The three setups at 19/20 each failed a different task. Two tasks passed with no profile, so some
checks can pass by chance. Twenty tasks cannot tell a two-task gap from noise.

![Claude Code recall bench: hit rate by setup](recall-bench.svg)

### 2.3 Variants that were withdrawn and not rerun

Before the isolation fix, the bench was also run with Claude Haiku answering, with five questions per
session, and with sessions placed inside a fictional project. Those runs had the same fault as the first
runs above: a session could read outside its folder. Their rows were withdrawn with the rest. They were not
rerun, so this document reports no result for them. The published results cover one model (Claude Sonnet), one
question per session, and a scratch folder with no project in it.

### 2.4 The hook's retriever, offline

Source: `results/recall-bench/2026-11-19-retrieval.json`. No model is involved. Recall is the share of
questions for which the text the hook would inject contains an answer term. Off-topic injection is the share
of off-topic prompts that get any profile line. "Before" is plain word overlap; "after" adds expansion words
written per profile line at compile time and a discount for words common in generic developer prompts.

| Held-out test half | Before | After |
| --- | --- | --- |
| Recall, all 45 questions | 36% (16/45) | 56% (25/45) |
| Direct (13) | 85% | 85% |
| Paraphrased (23) | 0% | 43% |
| Two-file (9) | 56% | 44% |
| Off-topic prompts given a line (20) | 35% | 15% |

The change helps paraphrased questions and cuts off-topic injection. It does not help two-file questions, and
15% off-topic injection is above the 5% the project had set as its target for this step.

### 2.5 Conclusion

With the generated index, Claude Code finds profile facts on its own. The index is a list of the profile's
files with a description of each, imported by `CLAUDE.md`. It matches the whole-profile baseline on direct
questions (45/45 each). On implicit tasks it is two behind (17/20 against 19/20), which n=20 cannot separate
from noise.

On this bench the prompt hook and the standing list did not earn their place. Neither moved a score outside
its interval. Each missed one two-file question that the index answered. The standing list cost tokens: 23.7k
against 17.2k mean input tokens per question session. The one sign in their favour is the two extra implicit
tasks, and that difference has an interval that includes zero.

The plugin therefore ships with both off. The index is the mechanism. Each option can be switched on in
`~/.config/unified-memory/config.json`: `"prompt_hook": true` and `"standing": true`.

The offline gain in 2.4 did not carry over. The retriever change raised held-out recall from 36% to 56%
offline, but end to end a Claude Code session with the index already opens the right file.

The hook's retrieval may be useful where a model cannot open files. This project has no clean measurement of
that case: the PrefEval condition that includes the hook was carried by standing lines (section 1).

## 3. Replay benchmark

Our own synthetic benchmark for the compile's checks. Five templated users over six weeks each. Facts change
over time, and false claims are planted in tool output. After each week the arm rewrites the stores and probe
questions are answered from the result. Each run scores 490 probes per arm: 275 for stale facts served, 125
for valid facts wrongly retired ("false stale"), 90 for planted claims accepted.

The arms:

- **Z:** do nothing. The stores as the memory writer left them.
- **A0:** Anthropic's shipped `consolidate-memory` skill, run automatically on each memory store.
- **A:** our own pass that reads every store in one context and writes a new version.
- **B:** the checked compile this plugin ships, with the write-time hook that keeps tool output away from the
  memory writer.

Sonnet ran each arm's pass. Haiku wrote the stores and answered the probes. Labels are the generator's own
truth, scored by a fixed string rule. B's questions were answered by an oracle, a simulated person. Two
writers were tested: "plain" records only what the person said; "absorb" also records what tools report.

**Seed 1.** Sources: `results/synth/2026-11-10-plain/report.md` and `results/synth/2026-11-10-absorb/report.md`.

| Arm | Combined error, plain writer | Minus Z | Combined error, absorb writer | Minus Z | Planted claims accepted, plain / absorb |
| --- | --- | --- | --- | --- | --- |
| Z | 90/490 | | 90/490 | | 66/90, 90/90 |
| A0 | 122/490 | +7 (+3 to +10) | 91/490 | +0 (+0 to +1) | 73/90, 90/90 |
| A | 101/490 | +2 (-1 to +6) | 90/490 | +0 (+0 to +0) | 67/90, 90/90 |
| B | 0/490 | -18 (-22 to -15) | 0/490 | -18 (-22 to -15) | 0/90, 0/90 |

Only B beat doing nothing. A0 was worse than Z with the plain writer and tied it with absorb. A tied Z in
both. Neither clean-up pass lowered planted-claim acceptance. False stale could not be decided between the
arms: Z, A and B all scored 0 of 125, so the benchmark has no headroom there.

**Stress test.** Source: `results/synth/stress/report.md`. The rules were written before the runs and
evaluated by code.

- **Second seed.** B minus Z on combined error: -16 points (-20 to -12) with the plain writer, -17 (-20 to
  -14) with absorb. B was not at zero: 12 of 490 and 7 of 490.
- **The hook is necessary.** With the absorb writer, B without the write-time hook accepted 90 of 90 planted
  claims on both seeds, the same as Z. The checks cannot refuse a claim the writer has already recorded.
- **Unanswered questions.** B still beat Z when its questions were never answered (-6 points), answered a
  week late (-15) or answered half the time (-13), seed 1. That hides a trade: with no answers B served
  stale facts on 59 and 60 of 275 probes, against Z's 24 and 0, because it holds every change it cannot
  confirm.
- **Erase.** 0 of 30 erased probes leaked in answers and 0 files held an erased value, for each of A, B and
  Z. The replay has no bridge, so this shows only that the erase function removes text from the current
  files.
- **A hole, and a fix that has not fired.** On seed 2 with the absorb writer, B accepted 6 of 90 planted
  claims. The compile had added a contradicting line cited to tool output, and the override rule did not
  look at adds. The checks now treat an add that restates a labelled line as an override. In a rerun of four
  runs (`results/synth/addfix/report.md`) B minus Z was -24, -18, -19 and -19 points with 0 of 90 planted
  claims accepted in each, but the new rule did not fire in that rerun. It is shown only by unit tests and an
  offline replay of the original proposal.

**Limits of the replay.**

- The users are templated, so absolute scores flatter every arm. Compare arms, not levels.
- One model family built the generator, the writer, the arms, the oracle and the spot-checks.
- Two seeds of five users. The oracle modes and the erase test ran on seed 1 only.
- The scorer is a strict string rule: a hedged answer counts as accepting the planted claim. A sample of 30
  labels was read by Claude (Opus 5.5); 29 agreed. Under a lenient reading the plain-writer planted counts
  are Z 45, A0 40 and A 52 of 90, and combined error is Z 69, A0 84 and A 77 of 490. B is 0 either way.
- Run-to-run variance is large. Z's planted acceptance on the same seed and writer was 66, 81 and 85 of 90 in
  three runs. Compare within a run.
- A never had the hook, so B against A measures the hook and the checks together.
- B asked 40 questions per run (1.33 per user-week, against a budget of 3), and in the main runs the oracle
  answered every one at once and truthfully.

## 4. LongMemEval-S

Source: `results/longmemeval/2026-11-10/report.md`. 100 questions from LongMemEval-S (cleaned release), drawn
with a fixed seed: 40 knowledge-update, 30 temporal-reasoning, 20 abstention, 10 multi-session. Haiku wrote
the memory stores, answered and judged, using LongMemEval's own answer key and grading prompts. This run
predates the checked compile and compares the earlier arms.

| Arm | Accuracy | 95% interval | Minus Z |
| --- | --- | --- | --- |
| Z, do nothing (store as written) | 82/100 | 73 to 88 | |
| A0, shipped clean-up | 76/100 | 67 to 83 | -6 (-13 to +1) |
| A, our whole-store clean-up | 82/100 | 73 to 88 | +0 (-6 to +5) |
| Full history in the prompt | 91/100 | 84 to 95 | +9 (+1 to +17) |
| Raw session files with search | 85/100 | 77 to 91 | +3 (-7 to +13) |

No memory arm matched full context. **B was not run on this sample.** Claude read 20 of the judge's verdicts
and agreed with 18; both disagreements were correct answers the judge marked wrong. A's prompt carried a hint
that A0's did not. The full-context answers ran at an unrecorded effort setting; 20 of them were rerun at the
recorded setting and all 20 verdicts matched (`results/longmemeval/2026-11-10-full-api-check/`).

Two faults in the run, both from the same report. The memory writer that Z, A0 and A share left 22 of roughly
700 batches without a clean finish; their stores were used as left. Two of A0's 100 clean-up passes hit the
output limit; those two questions were still answered and scored (one right, one wrong) and are in A0's
76/100.

**Pilot with the compiled profile.** Source: `results/public-bench/2026-11-19-pilot/summary.json`. Ten
questions of three types (knowledge-update, single-session-user, single-session-preference), Haiku answering
and judging:

| Condition | Correct |
| --- | --- |
| No memory | 0/10 |
| Compiled profile, all lines | 2/10 |
| Compiled profile, core lines + hook (the earlier form of the condition: no standing lines, no expansion words) | 2/10 |
| BM25 over raw turns | 9/10 |
| Full history | 8/10 |

The profile keeps facts about the person. Most of these questions ask about details of a chat, which the
compile does not store, so raw retrieval wins. This is a pilot of ten questions and nothing more. In its 50
compile passes the checks rejected 51 of 210 proposed changes; the summary does not break the reasons out.

## 5. MemoryAgentBench FactConsolidation

Source: `results/public-bench/2026-11-19-pilot/summary.json`. Out of scope, reported for context only. The
task gives a numbered list of facts about the world in which later facts override earlier ones. The compile
stores facts about the person and stored none of these, so both profile conditions scored 0/10, the same as
no memory. On the same 10 questions (`factconsolidation_sh_6k`, Haiku answering) BM25 over the raw list scored
10/10, the full list 9/10, and a fixed "newest matching statement wins" rule 9/10.

That rule needs no model to pick its fact. Over all 100 questions of the source, the fact it picks contains a
gold answer for 97. This figure is computed directly from the dataset and has no results file;
[BENCHMARKS.md](BENCHMARKS.md) has the command.

## 6. Recall across surfaces on a real account

A canary test on a real account exists: made-up facts stated on one Claude surface and probed on another,
before and after the bridge. It is not published, because it runs against personal data.

## 7. Who wrote the labels

| Item | Written by | Checked by a person |
| --- | --- | --- |
| Recall bench: fictional user and profile, questions, answer terms, off-topic prompts | Claude (Fable 5.2) | no |
| Recall bench: implicit tasks, the facts they target, and their yes/no checks | Claude (Fable 5.2) | no |
| Recall bench: standing labels on profile lines (123 of 263 labelled standing) | Claude Sonnet, without seeing the tasks | no |
| Recall bench: expansion words per profile line | a Claude model, without seeing the questions | no |
| Hook: 667 background prompts used to discount common words | Claude, without seeing the benchmark | no |
| Recall bench: the fictional project's `CLAUDE.md` (used only by the withdrawn in-project runs) | Claude Sonnet | no |
| Replay: users, facts, planted claims, probes, truth labels | a deterministic generator written with Claude | 30 labels spot-checked by Claude, not by a person |
| PrefEval, LongMemEval, MemoryAgentBench: items and answer keys | the benchmarks' authors | n/a |
| Judging: PrefEval checks, LongMemEval grading, implicit-task checks | Claude Haiku 5.5 | 20 LongMemEval verdicts read by Claude, not by a person |

Answering models: Haiku 5.5 for PrefEval, LongMemEval, MemoryAgentBench and the replay probes. Claude Sonnet
for the recall bench; its runs record the Claude Code model alias (`sonnet`), not an exact model id.

## 8. What was not run

- PrefEval with 300 inter-turns, with implicit preferences, with the classification task, with the paper's
  judge, or in the paper's multi-turn format.
- The checked compile (B) on the 100-question LongMemEval sample. LongMemEval beyond 100 questions.
- MemoryAgentBench beyond a 10-question pilot on one source.
- The recall bench with more than one run per setup, with a larger profile, or in interactive sessions.
- The recall bench with Claude Haiku answering, with several questions per session, or inside a project.
  These were run before the isolation fix, withdrawn, and not rerun (section 2.3).
- Off-topic prompts under the standing setup alone, so the hook's own token cost is not isolated.
- A third replay seed, the full-size replay the plan called for, or the replay with real histories.
- Any judge or labeller from another model family. Any human evaluation.
- The scheduled-task surface: nothing was stated on it or probed from it.
- Design components beyond B: pinned facts, probes, promotion by demand, typed transitions, dependency
  links, facts by reference in skills. None was built.

## 9. Limits

- **Small n everywhere.** The widest claims rest on 100 items, 45 questions and 20 tasks. Two-file questions
  are 9.
- **A fictional user.** The recall bench profile is tidy, consistent and written in one sitting. A real
  profile is messier.
- **Model-written labels, model judges, one model family.** See sections 7 and 8.
- **Single runs.** Each published recall-bench setup is one run, made after the isolation fix. The replay
  shows large run-to-run variance.
- **String-match scoring** on recall questions counts a correct answer in other words as a miss, and a
  two-file hit does not prove both files were used.
- **The checked compile has not been shown to improve a real person's stores.** In the only runs on real
  stores (one person, counts only, data not published) it applied no changes. Its benefit so far is on
  synthetic and benchmark histories.
- **The compile's mention check sometimes rejects valid changes.** The rate has not been measured.
- **The bridge** depends on a claude.ai scheduled task, the desktop app being open, and behaviour observed on
  one account. It is not covered by any benchmark here.
- **Isolation of benchmark sessions failed once.** The first recall-bench runs let a session read any file
  on the machine. Their rows were withdrawn and the bench was rerun with sessions confined to their folders
  (section 2). The fix was checked by hand, once, against the Claude Code version installed that day. No
  automated test runs a real session. The account email of whoever runs the bench still reaches the session;
  it cannot help answer questions about a fictional user.
