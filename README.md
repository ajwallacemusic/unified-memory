# Unified Memory

A Claude Code plugin that gives Claude one checked profile of you and search over your past conversations,
so a new session already knows what you have told Claude before.

A personal research project by AJ Wallace, not an Anthropic product.

## The problem

What Claude knows about you is split across stores that do not see each other: account memory on claude.ai,
`CLAUDE.md` and auto memory in Claude Code, and past chats in Claude Code, the desktop app and claude.ai. A new
Claude Code session reads only its own files, so you repeat yourself.

## The fix

- **One profile.** Plain Markdown in a local git repository, compiled from your Claude Code sessions. A model
  proposes each change; code checks it against quoted evidence before it lands.
- **Search over past conversations.** Two tools over a local index of Claude Code sessions, desktop app
  sessions and, from an export, claude.ai chats.
- **Undo and erase.** Every compile is one revertable commit. Erase removes a value from the profile, its
  evidence and the index.
- **Local.** The profile and index stay on your machine. Model calls use your own `claude` login.

## Results

| Test | Without | With the plugin | Reference |
| --- | --- | --- | --- |
| **Facts about you, asked in Claude Code.** Recall bench (ours, fictional user), 45 held-out questions, Sonnet answers | no profile: 0/45 | **45/45** (44/45 with Haiku) | whole profile in `CLAUDE.md`: 45/45 |
| **Questions about past conversations.** LongMemEval-S, 100 questions, Haiku 5.5 answers and judges | profile alone: 42; one search, top 5: 48 | **74** (mean 75.75 over four runs) | full history in prompt: 91, at ~23× the input tokens |
| **A preference stated 300 exchanges earlier.** PrefEval, 100 items, Haiku 5.5 answers and judges | no memory: 17; BM25 over raw turns: 36 | **84**, at 161 input tokens per answer | full history: 81, at 162,462 tokens |

Correct answers out of n; one run unless stated. Brackets below are 95% intervals.

- **The profile ties full history on PrefEval** (+3 points [-7 to +13]) while reading about a thousandth of
  the tokens per answer.
- **Search trails full history** by 17 points [-27 to -8] but adds 32 over the profile alone [+22 to +42].
- **Repeat LongMemEval runs disagree on 11 to 14 of 100 questions,** so a few points between single runs is
  noise.

![Claude Code recall bench: hit rate by setup](docs/recall-bench.svg)

![PrefEval: preference-following against mean input tokens per answer](docs/prefeval.svg)

The PrefEval chart is the easier 10-inter-turn run, not the table's 300.

**Tried and dropped:** a prompt hook that injects matching profile lines (no gain over the index); a
`read_chat` tool that reads a whole past session (failed a pre-set rule in two sets of four runs);
embeddings (in 19 of the 21 questions where search lost to full history, the right session was already in
the results).

## Demo

Claude Code (Sonnet) with the plugin, over a synthetic LongMemEval-S history:

> **Question (asked on 2023/03/26):** How many days passed between the day I repotted the previous spider
> plant and the day I gave my neighbor, Mrs. Johnson, a few cuttings from my spider plant?
>
> `conversation_search {"query": "spider plant repotted", "max_results": 10}`<br>
> `conversation_search {"query": "Mrs. Johnson spider plant cuttings neighbor", "max_results": 10}`
>
> **Answer:** 14 days. You repotted the previous spider plant on March 4, 2023, and gave Mrs. Johnson the
> cuttings on March 18, 2023. I took both dates from the conversations where you said "today".

One of four recorded questions, picked from ones the benchmark answered correctly, so it shows how the plugin
works, not how often. All four are in [docs/DEMO.md](docs/DEMO.md).

## Install

Needs Claude Code, `git` and `python3` 3.10+. Developed on macOS; Linux is untested; Windows is not supported
(the hooks use Unix file locking).

```sh
claude plugin marketplace add ajwallacemusic/unified-memory
claude plugin install unified-memory@unified-memory
```

Then run `/unified-memory:setup` in a Claude Code session. It creates the profile as a git repository
(suggested `~/claude-profile`, not under `~/.claude`) and, with your OK, adds one import line to
`~/.claude/CLAUDE.md` so every session reads it. No API key is needed; model calls go through `claude -p`.

Run `/unified-memory:compile` to update the profile. Other commands: `status`, `answer <text>`, `undo`,
`erase <value>`, and `bridge` (optional: mirrors the profile into claude.ai account memory).

Search needs no command: Claude Code and desktop sessions are indexed automatically. For claude.ai chats,
import an export from a clone of this repository:

```sh
python3 -m um.cli search import-export PATH-TO-EXPORT
```

## How it works

- **Origin comes from structure, not a model:** each piece of a transcript is typed by you, written by the
  assistant, or tool output.
- **A model proposes, code decides.** Every change must quote its evidence, and tool output can add a line
  but never replace or remove one. In a synthetic replay, 0 of 90 false claims planted in tool output got
  through, against 66 of 90 with no checks; a second seed let up to 6 through.
- **Claude Code reads a generated index:** the core profile lines plus one line per other file.
- **Search is BM25 in one local SQLite file.** No embeddings, model calls or network. It returns dated quotes
  and never writes the profile.
- **A write-time hook** blocks direct writes to memory files in any turn that has taken in tool output.

More in [docs/DESIGN.md](docs/DESIGN.md).

## Limits

- **Small samples** (45 to 100 items), most conditions run once.
- **Claude models built and ran everything; Haiku 5.5 is the main judge.** An OpenAI judge re-scored 1,100
  saved answers and agreed on 91 to 96%, with no ranking changes ([RESULTS.md §8.1](docs/RESULTS.md)).
- **Little human evaluation.** Our benches use model-written labels; the author checked 30 and agreed with all.
- **Search is measured on benchmark chats,** not real ones: four live sessions on the author's index all
  called search, which is not a measured call rate.
- **The first search run predates 11 code-review fixes,** one to ranking. Three later runs scored 77, 77 and 75.
- **The checked compile is shown to help only on synthetic and benchmark histories,** not real stores.

## Documents

- [docs/RESULTS.md](docs/RESULTS.md): every number, its source file and caveats.
- [docs/DESIGN.md](docs/DESIGN.md): the design, and what was dropped.
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md): the commands behind each number.
- [docs/DEMO.md](docs/DEMO.md): four recorded questions.

License: MIT (see [LICENSE](LICENSE)).
