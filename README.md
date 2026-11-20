# Unified Memory

Claude keeps what it knows about you in several places: account memory on claude.ai, auto memory and
`CLAUDE.md` files in Claude Code, skills, scheduled-task prompts. They drift apart, and you end up repeating
yourself. Unified Memory keeps one profile of you as Markdown files in a local git repository, laid out like
Claude's account memory. It is compiled from what you say in Claude Code sessions: a model proposes changes,
each with a quote from the evidence, and code decides which ones land. Tool output can never override
something you said. Claude Code reads the profile through a generated index. An optional bridge mirrors it into
claude.ai account memory, so chat and mobile see the same facts.

The profile holds what is true about you now. For what was said in a past conversation, the plugin adds
conversation search: two tools Claude Code can call, over a local index of your Claude Code sessions, the
desktop app's local sessions and, if you import an export, your claude.ai chats.

This is a Claude Code plugin and the benchmark code behind it. It is a personal research project by AJ Wallace,
not an Anthropic product. The numbers are small-sample; read [the limits](#limits) before quoting any of them.

## Results

| Benchmark | n | Result |
| --- | --- | --- |
| **PrefEval** (public; explicit preferences, 10 inter-turns) | 100 items | Compiled profile: 96% preference-following [90 to 98] at 121 mean input tokens. BM25 over the raw turns: 75% [66 to 82] at 651 tokens. Full history: 99% [95 to 100] at 5,850 tokens. No memory: 13% [8 to 21]. |
| **PrefEval**, the same items with 300 inter-turns | 100 items | Compiled profile: 84% [76 to 90] at 161 mean input tokens. BM25 over the raw turns: 36% [27 to 46] at 1,433. Full history: 81% [72 to 87] at 162,462. No memory: 17% [11 to 26]. |
| **Claude Code recall bench**, questions about the user (ours; fictional user) | 45 held-out questions, two answering models | Claude Sonnet: no profile 0/45, generated index 45/45, whole profile pasted into `CLAUDE.md` 45/45, index plus standing list 44/45, index plus standing list and prompt hook 44/45. Claude Haiku: 0/45, 44/45, 45/45, 41/45, 42/45. |
| **Claude Code recall bench**, tasks that never ask about the user | 20 held-out tasks, judged by Claude Haiku 5.5 | Claude Sonnet: no profile 2/20, index 17/20, whole profile 19/20, index plus standing list 19/20, index plus standing list and prompt hook 19/20. Claude Haiku: 1/20, 15/20, 17/20, 16/20, 17/20. |
| **LongMemEval-S with conversation search** (public; questions about past sessions) | 100 questions | Compiled profile alone: 42% [33 to 52] at 1,018 mean input tokens. Profile plus search: 74% [65 to 82] at 7,311. Search alone: 74%. Full history: 91% [84 to 95] at 167,168. |
| **Replay** (ours; synthetic users, false claims planted in tool output) | 490 probes per arm, seed 1 | Combined error: doing nothing 90/490, compile with code checks 0/490. Planted claims accepted: 66/90 against 0/90. A second seed gave 12/490 and 7/490 against 91/490 and 90/490. |

Brackets are 95% Wilson intervals. What the table does and does not show:

- On PrefEval the compiled profile beat BM25 retrieval over the raw conversation by 21 points [+12 to +30]
  and used about a fifth of its input tokens. It did **not** beat full history. The difference is -3 points
  [-7 to +1], which is a tie at this sample size, at about 2% of the input tokens. The token counts are for
  the answer call only; compiling the profile is a separate model call.
- With 300 unrelated exchanges in the history in place of 10, every memory condition scored lower: BM25 by 39
  points, full history by 18, the profile by 12. The profile and full history tie there (+3 points [-7 to
  +13]) while the answer call reads about a thousandth of the tokens, and the profile beat BM25 by 48 points
  [+36 to +60]. All 16 profile failures were items for which the compile stored nothing, which happened for
  17 of 100 items against 4 of 100 at 10 inter-turns. The compile itself reads the whole history once. The
  two lengths were run with different output limits, so the drop is not a controlled comparison.
- On the recall bench the index matches the whole-profile baseline on questions with Sonnet (45/45 each) and
  is one behind with Haiku (44/45 against 45/45). On implicit tasks it is two behind with both models (17/20
  against 19/20, and 15/20 against 17/20; intervals overlap). The prompt hook and the standing list did not
  measurably improve on the index (hook minus index on implicit tasks: +10 points [-10 to +30] with each
  model), so both ship turned off.
- The recall bench numbers are from a rerun. The first runs let a session read files outside its folder.
  Those rows were withdrawn and are not published. Each setup was then run once per answering model, with
  sessions confined to their folders.
- On LongMemEval-S, adding conversation search to the profile gained 32 points [+22 to +42]. It did **not**
  match full history: -17 points [-27 to -8], at about 4% of the input tokens. The profile added nothing to
  search on these questions. An earlier arm that let the model read the raw session files scored 85% on the
  same questions in a different run, at 17,342 mean input tokens, so search as built is not the best way
  measured here to read history.
  A companion test on PrefEval found no drop in preference-following with the search tools offered (93%
  against 94%), but the model never called them there.
- The replay result is from templated synthetic users. It shows the checks and the write-time hook doing
  what they were built to do, not how the system behaves on real histories.

![PrefEval: preference-following against mean input tokens per answer](docs/prefeval.svg)

![Claude Code recall bench: hit rate by setup](docs/recall-bench.svg)

The charts draw the 10 inter-turn PrefEval run and the Sonnet recall-bench runs. All numbers, their source
files and what was not run are in [docs/RESULTS.md](docs/RESULTS.md).

## Install

You need Claude Code, `git`, and `python3` (3.10 or later) on your `PATH`. The project was developed and run on
macOS. Linux is untested. Windows is not supported: the hooks use Unix file locking.

```sh
claude plugin marketplace add ajwallacemusic/unified-memory
claude plugin install unified-memory@unified-memory
```

Then, in a Claude Code session:

```
/unified-memory:setup
```

Setup asks where the profile should live (it suggests `~/claude-profile`; the folder must not be under
`~/.claude`), creates it as a git repository, and offers to add one import line to `~/.claude/CLAUDE.md`. That
line is what lets every Claude Code session read the profile. Setup asks before it changes the file.

Model calls go through `claude -p` on your own Claude plan by default. No API key is needed.

## Quickstart

| Command | What it does |
| --- | --- |
| `/unified-memory:compile` | Reads your Claude Code sessions since the last compile and adds what you said about yourself. Writes a receipt and one git commit. |
| `/unified-memory:status` | Last build, held items, pending questions, anything that needs you. |
| `/unified-memory:answer <text>` | Answers a pending question. The answer is kept as something you said. |
| `/unified-memory:undo` | Reverts the last compile. |
| `/unified-memory:erase <value>` | Removes a value from the profile, its records and its evidence, and lists raw copies left in other apps. Asks first. |
| `/unified-memory:bridge` | Walks you through connecting the profile to claude.ai account memory. Optional. |

Conversation search needs no command. With the plugin on, Claude Code has two more tools,
`conversation_search` and `recent_chats`, and can call them when you ask about a past conversation ("what did
we decide about the migration last month?"). Claude Code and desktop local sessions are indexed automatically.
claude.ai chats are not: request your data export in claude.ai settings, download it, and import it from a
clone of this repository. There is no slash command for this yet.

```sh
python3 -m um.cli search import-export PATH-TO-EXPORT   # the conversations zip or the unpacked folder
python3 -m um.cli search status                         # sessions per surface, age of the export
python3 -m um.cli search query migration decision       # the same search the tool runs
python3 -m um.cli search rebuild                        # re-cut stored chats after a chunk-size change
```

To turn conversation search off, set `"search": false` in `~/.config/unified-memory/config.json`. While it
is off, the session-start catch-up does nothing, `search index`, `search query` and `search recent` refuse
with a message, and the two tools answer that search is off without reading or updating the index. The index
file is left as it is; set the key back to `true` (or remove it) to turn search on again.

A typical first day: run setup, work as usual, then run `/unified-memory:compile` and read the receipt it shows
you. The profile is plain Markdown under git, so you can read it and see every change in `git log`.

## How it works

```
Claude Code sessions ──> evidence ──> compile ──> checks ──> profile (git) ──> index ──> Claude Code
(origin from structure)              (a model)    (code)          │
                                                                  └──> bridge ──> claude.ai account memory
                                                                      (optional)   (chat, mobile, tasks)

Claude Code sessions ──┐
desktop local sessions ─┼──> search index (local SQLite, no model) ──> two search tools ──> Claude Code
claude.ai export ───────┘
```

1. **Evidence.** The compile reads Claude Code transcripts. Each piece gets an origin from the transcript's
   structure, never from a model: something you typed, something the assistant wrote, or tool output.
   Non-interactive sessions (`claude -p`) are skipped, so a prompt sent by a script or a benchmark never
   counts as something you said.
2. **Compile.** A model proposes changes to the profile. Every change must cite evidence and quote it.
3. **Checks.** Code accepts or refuses each change. The quote must exist in the cited evidence and mention
   what the change asserts. Tool output can add a line but can never replace or remove one. A line you stated
   changes only on something you said. A blocked change becomes a question, at most three a week.
4. **Profile.** Accepted changes are committed to the profile's git repository with a receipt.
5. **Readers.** Claude Code imports a generated index: the core profile lines, and one line per other file
   (its path and a description) so the session can open the file a question needs. The bridge copies the
   same files into claude.ai account memory.

A second hook, the memory guard, covers the write side: in a turn that has taken in web, shell or MCP tool
output, a direct write to the profile or to Claude Code's memory files is denied, and the text is held as
tool-output evidence for the next compile.

**Conversation search** is separate from all of that. It indexes what you typed and what the assistant wrote
(never tool output or thinking), ranks by word matching (BM25) with no embeddings and no model call, and
returns dated, cited quotes. It never writes the profile, and the compile ignores its results, so an old
quote cannot come back as a new fact. When a quote disagrees with the profile or with what you say now, the
tools' instructions tell Claude that the profile and you win.

Two options are off by default, because neither showed a measured gain on the recall bench. The prompt hook
adds matching profile lines to each prompt. The standing list puts lines labelled as standing preferences
inline in the index. Turn them on with `"prompt_hook": true` and `"standing": true` in
`~/.config/unified-memory/config.json`.

More detail: [docs/DESIGN.md](docs/DESIGN.md).

## Privacy and safety properties

- **Tool output cannot override what you said.** This is enforced in code, in the checks and in the memory
  guard hook, not left to the model. In the replay benchmark the hook was necessary: without it, 90 of 90
  planted claims got through when the memory writer recorded tool output.
- **Receipts and undo.** Every compile writes a receipt (what changed, the quote, its source) and exactly one
  commit. `/unified-memory:undo` reverts it.
- **Erase.** Removes a value from the profile, lineage, answers and evidence, and every chunk containing it
  from the search index. It can also rewrite the profile's git history if you ask. It reports raw copies that
  remain in other apps' files; it does not delete those.
- **The search index stays on your machine.** It is one SQLite file under `~/.local/share/unified-memory/`,
  outside the profile and outside any git repository. Building and querying it makes no network call. It holds
  conversation text, and it keeps a session after Claude Code has deleted the transcript, so treat it like the
  transcripts themselves. `python3 -m um.cli search forget --all --yes` empties it of conversation text and
  compacts the file; it keeps only the salted hashes of erased values, so a rebuild from transcripts cannot bring
  them back. Turning search off (`"search": false`, above) stops it from collecting more.
- **Search results are quotes, not instructions.** Every result starts with a notice saying so, and code keeps
  a quote from changing the profile or memory. The notice is the only guard against the model acting on
  quoted text in the current turn.
- **Local by default.** The profile and its evidence stay in a folder on your machine. The plugin has no
  server of its own. Model calls go to Claude through your own `claude` login, the same place your sessions
  already go. The profile reaches claude.ai account memory only through the bridge, and only if you set it up.
- **The bridge starts in propose-only mode.** It writes nothing to account memory until two reviewed runs in
  a row have nothing rejected. Local code decides what may be pushed, under a category policy and a block on
  card, ID and credential patterns. Versions are checked so an edit made in a chat is not overwritten.

## Limits

- **Small samples.** 100 PrefEval items, 100 LongMemEval questions, 45 questions, 20 implicit tasks, two replay
  seeds of five users. Each recall bench setup was run once per answering model, and each PrefEval length
  once.
- **The profile is not a memory of past conversations, and search only partly is.** The profile keeps current
  facts and preferences. On LongMemEval-S (100 questions about past sessions) it scored 42% alone. With
  conversation search it scored 74%, against 91% for the full history in the prompt and 85% for an earlier arm
  that read the raw session files (a different run). Most of the gap is not retrieval: in 19 of the 21
  questions search lost to full history, the right session was in the results. See
  [RESULTS](docs/RESULTS.md) sections 4 and 6.
- **Conversation search is measured on benchmark chats only.** Nothing measures how well it answers from real
  Claude Code sessions, or how often Claude Code calls it when it should or should not. The test for harm to
  preference-following passed without a single search call, so it does not cover search results in context.
  A code review after the benchmark runs led to 11 fixes, one of them to ranking. The benchmarks were not
  rerun after them ([RESULTS](docs/RESULTS.md) section 6.6).
- **claude.ai chats are searchable only through an export.** They are as old as the last export you imported.
  The export does not say which project a chat belongs to. Cloud sessions that the export leaves out are not
  searchable. Search does not run inside claude.ai or the desktop app's chats.
- **A fictional user and model-written labels.** Claude models wrote the recall bench's user, questions,
  implicit tasks and checks, and the hook's expansion words, standing labels and background prompts. No
  person checked them.
- **Judges are Claude Haiku 5.5.** PrefEval was not scored with the paper's judge model. No judge from another
  model family was run. No human evaluation was done.
- **One model family built, ran and scored the benchmarks.**
- **PrefEval is not run in the paper's format.** Every condition gets its context in the system prompt, which
  likely helps the full-history baseline. The 10 and 300 inter-turn settings were each run once. Each PrefEval
  item has one preference, and each compiled profile is one line at 10 inter-turns and one to three at 300.
- **The bridge depends on a claude.ai scheduled task.** It needs the Claude desktop app open on the machine
  that holds the profile, and it relies on behaviour observed on one account in November 2026, not on
  documented guarantees.
- **The compile's mention check sometimes rejects valid changes.** The check requires a change's quote to
  mention what the change asserts, by a word-matching rule. A rejected change is not applied, so a fact you
  stated can fail to reach the profile. How often this happens has not been measured.
- **Real use is barely measured.** A canary test of recall across surfaces on a real account exists and is
  not published, because it involves personal data.

## Documents

- [docs/RESULTS.md](docs/RESULTS.md): every number, with n, intervals, source file and caveats.
- [docs/DESIGN.md](docs/DESIGN.md): the design, what was tried and dropped, what is not built.
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md): the commands that produce each number.

License: MIT (see [LICENSE](LICENSE)).
