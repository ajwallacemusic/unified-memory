# Unified Memory

A Claude Code plugin that gives Claude one checked profile of you and local search over your past
conversations, so a new session already knows what you have told Claude before.

**The problem.** What Claude knows about a person is split across stores that do not see each other: account
memory on claude.ai, `CLAUDE.md` and auto memory in Claude Code, and past chats in Claude Code, the desktop app
and claude.ai. Claude Code is the most cut off: a new session reads its own files and sees neither account
memory nor chats from the other apps. So you repeat yourself.

**What the plugin does.**

- **One profile.** Plain Markdown in a local git repository, compiled from what you say in Claude Code
  sessions and checked by code before anything lands.
- **Search over past conversations.** Two tools Claude Code can call, over a local index of your Claude Code
  sessions, the desktop app's local sessions and, from an export, your claude.ai chats.
- **Undo and erase.** Every compile is one commit you can revert. Erase removes a value from the profile,
  its evidence and the search index.
- **Local.** The profile and the index stay on your machine. Model calls use your own `claude` login.

A personal research project by AJ Wallace, not an Anthropic product.

## Headline numbers

| Test | n and models | Without | With the plugin | Reference |
| --- | --- | --- | --- | --- |
| Facts about the user, asked in Claude Code. Recall bench (ours, fictional user) | 45 held-out questions. Claude Sonnet answers | no profile: 0/45 | profile index: 45/45 (44/45 with Haiku) | whole profile pasted into `CLAUDE.md`: 45/45 |
| Questions about past conversations. LongMemEval-S (public) | 100 questions. Claude Haiku 5.5 answers and judges | profile alone: 42. One search call, top 5 results: 48 | profile + search: 74 (mean 75.75 over four runs: 74, 77, 77, 75) | full history in the prompt: 91, at about 23 times the input tokens |
| A preference stated 300 exchanges earlier. PrefEval (public) | 100 items. Haiku 5.5 answers and judges | no memory: 17. BM25 over the raw turns: 36 | compiled profile: 84, at 161 input tokens per answer | full history: 81, at 162,462 tokens |

Scores are correct answers out of n, one run unless stated. Brackets are 95% intervals.

- **The profile ties full history on PrefEval and does not beat it:** +3 points [-7 to +13]. Each answer
  reads about a thousandth of the tokens, after one compile that reads the whole history.
- **Search is well behind full history:** -17 points [-27 to -8]. It is 32 points ahead of the profile alone
  [+22 to +42].
- **Repeat LongMemEval runs disagree on 11 to 14 of 100 questions,** so a gap of a few points between two
  single runs is noise.

**Tried and dropped.** A prompt hook that adds matching profile lines to each prompt: no measured gain over
the index, so it ships off. A `read_chat` tool that reads a whole past session: it failed a rule fixed before
the repeat runs, twice (four runs per arm), and did not ship. Embeddings: not built, because in 19 of the 21
questions search lost to full history, the right session was already in the results.

![Claude Code recall bench: hit rate by setup](docs/recall-bench.svg)

![PrefEval: preference-following against mean input tokens per answer](docs/prefeval.svg)

The PrefEval chart is the easier 10 inter-turn run, not the table's 300.

## Demo

One of four recorded questions: Claude Code (Sonnet) with the plugin, over a synthetic LongMemEval-S chat
history.

> **Question (asked on 2023/03/26):** How many days passed between the day I repotted the previous spider
> plant and the day I gave my neighbor, Mrs. Johnson, a few cuttings from my spider plant?
>
> `conversation_search {"query": "spider plant repotted", "max_results": 10}`<br>
> `conversation_search {"query": "Mrs. Johnson spider plant cuttings neighbor", "max_results": 10}`
>
> **Answer:** 14 days passed between the two events. You repotted the previous spider plant on March 4, 2023.
> You gave Mrs. Johnson the cuttings on March 18, 2023. I took both dates from the dates of the conversations
> where you mentioned each one. In both, you said "today".

Three of the four matched the gold answer; one was partial. They were picked from questions the benchmark
run had answered correctly, so this shows how the plugin works, not how often. All four:
[docs/DEMO.md](docs/DEMO.md).

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

Then work as usual and run `/unified-memory:compile` to update the profile. The other commands, under the
same prefix: `status`, `answer <text>`, `undo`, `erase <value>`, and `bridge` (optional: mirrors the profile
into claude.ai account memory).

Search needs no command. Claude Code and desktop local sessions are indexed automatically. claude.ai chats
need an export, imported from a clone of this repository:

```sh
python3 -m um.cli search import-export PATH-TO-EXPORT
```

## How it works

- **Origin comes from structure, never from a model:** a piece of a transcript is typed by you, written by
  the assistant, or tool output.
- **A model proposes, code decides.** Every change must quote its evidence. Tool output can add a line but
  never replace or remove one. In a synthetic replay, 0 of 90 false claims planted in tool output were
  accepted, against 66 of 90 with no checks. A second seed let up to 6 of 90 through.
- **Claude Code reads a generated index:** the core profile lines, plus one line per other file so a session
  can open the one it needs.
- **Search is word matching (BM25) in one local SQLite file.** No embeddings, no model call, no network. It
  returns dated quotes and never writes the profile.
- **A write-time hook** denies direct writes to memory files in a turn that has taken in tool output.

More: [docs/DESIGN.md](docs/DESIGN.md).

## Limits and what was not run

- **Small samples,** 45 to 100 items, and most conditions were run once.
- **Claude models built and ran everything; Claude Haiku 5.5 is the main judge.** A second judge from OpenAI
  re-scored 1,100 saved answers and agreed with Haiku on 91 to 96% of them; no ranking changed
  ([RESULTS.md section 8.1](docs/RESULTS.md)).
- **No human evaluation.** Our own benches have model-written labels. The author's check of 30
  (`bench/recall/label-check.md`) is not filled in yet.
- **Search is measured on benchmark chats.** On real conversations there are four live sessions on the
  author's index, read by Claude. Search was called in all four; that is not a measured call rate.
- **The first search-test run predates 11 code-review fixes,** one of them to ranking. Three later runs of
  the fixed code scored 77, 77 and 75.
- **The checked compile is not shown to help on real stores,** only on synthetic and benchmark histories.
- **Run on macOS only.** Linux is untested.

## Documents

- [docs/RESULTS.md](docs/RESULTS.md): every number, its source file and caveats.
- [docs/DESIGN.md](docs/DESIGN.md): the design, and what was dropped.
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md): the commands behind each number.
- [docs/DEMO.md](docs/DEMO.md): four recorded questions.

License: MIT (see [LICENSE](LICENSE)).
