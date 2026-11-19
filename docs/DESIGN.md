# Design

How Unified Memory is built, why it is built that way, and what was tried and dropped. Numbers quoted here
are explained in [RESULTS.md](RESULTS.md).

## 1. The problem

Claude holds knowledge about a person in several stores: account memory on claude.ai (read by chat, mobile
and scheduled tasks), Claude Code's per-project auto memory and `CLAUDE.md` files, skills, and the prompts of
scheduled tasks. Each store is written separately. A fact told to one does not reach the others, a fact that
changes is updated in one and stays stale in the rest, and text that arrives in tool output can end up
recorded as if the person had said it.

## 2. Goals

1. One profile of the person that every reachable surface reads and feeds.
2. The profile stays current: stale facts retired, valid facts kept, conflicts settled or asked about.
3. What is learned on one surface reaches the others within one sync cycle, with no pasting.
4. Every fact can be traced to where it came from, undone, and erased.
5. Every component earns its place with a number against a baseline.

Not goals: changing how Claude's apps load memory (the project works only through tools they expose), reaching
sandboxed contexts such as incognito chats, running a hosted service, or shared team memory.

Things the design must not do:

- Create a second memory that can disagree with account memory.
- Create review chores. More than about three questions a week is a failure.
- Change anything silently. Every automatic change appears in a receipt and can be undone.
- Let tool or connector text gain the authority of something the person said.
- Claim an improvement without sample sizes, label authorship and what was not run.

## 3. Shape

```
 surfaces (Claude Code sessions; chat through the bridge)
      │ write as they do today                          ▲ read
      ▼                                                 │
 EVIDENCE  ──>  COMPILE  ──>  CHECKS  ──>  PROFILE (git)  ──>  index  ──>  Claude Code
 (dated,        (a model      (code         Markdown files │
  origin from    proposes)     decides)                    └──>  BRIDGE  ──>  claude.ai account memory
  structure)                                                    (optional)
```

Two tracks share one profile. The first keeps the profile correct: evidence, compile, checks. The second gets
it to and from each surface: the index for Claude Code, the bridge for account memory.

## 4. The profile

The profile is a folder of Markdown files in a local git repository. It uses the layout of Claude's account
memory, so the mirror is file for file:

```
profile.md        core facts
areas/*.md        ongoing areas of the person's life and work
topics/*.md       subjects
people/*.md       people
claude-code.md    generated index for Claude Code; never mirrored
```

Each file starts with a `name` and a one-line `description`, followed by one fact per line. Git is the history
and the undo. The folder cannot live under `~/.claude`, because a claude.ai session cannot be given a folder
there.

Bookkeeping sits beside the files and is not mirrored: the origin and citations of each line (lineage),
receipts, pending questions, held evidence, and hashes of erased lines.

## 5. Evidence and origin

The compile reads Claude Code transcripts since the last build, files the bridge pulled from account memory,
and tool-output text the memory guard held back. Evidence is dated and carries an origin. The origin is set
from the structure of the transcript, never by a model:

- `user-said`: a message the person typed.
- `assistant`: text the assistant wrote.
- `tool-output`: the result of any tool call.

Pre-existing lines with no traceable source are `legacy`. Meta messages, task notifications and subagent
reports are dropped.

Origin is the basis of authority. What the person said outranks what the assistant inferred and what predates
tracking, and all of those outrank what a tool returned.

## 6. Compile and checks

The compile is one model call. It is given every profile line with its file and recorded origin, then the new
evidence, and it proposes a list of changes: add, replace or remove. Every change must cite an evidence item
and quote it exactly. The model applies nothing.

Code then decides, change by change:

0. The change must be well formed and aim at a line that exists exactly once.
1. Each citation must name known evidence, quote text that evidence contains, and mention what the change
   asserts. A change with no citation is rejected, unless it removes an exact duplicate.
2. The change takes the highest-ranked origin among its citations.
3. Adding a line is allowed from any origin, unless the new line restates a labelled attribute that an
   existing line gives another value for. Such an add is treated as an override.
4. Tool output can never replace or remove a line, whatever that line's origin.
5. A line the person stated can be replaced or removed only on something the person said.
6. At most a capped number of changes land in one pass (the larger of 5 and 20% of the profile's lines). The
   rest are held.

A change that fails rule 4 or 5 becomes a question for the person when it carries one, and is held otherwise.
Questions are capped at three a week. An answer is stored as `user-said` evidence, so the next compile can act
on it.

Each compile writes a receipt: what was applied, held or rejected, the quote and source for each, and the
reason for anything not applied. It makes exactly one git commit. Undo reverts that commit.

**Why code and not the model.** The compile prompt tells the model about these rules, but the rules do not
depend on the model following them. In the replay benchmark, clean-up passes with no code checks did not lower
the rate of planted tool-output claims being accepted (A0 73/90 and A 67/90, against 66/90 for doing nothing).
The checked compile with the write-time hook accepted 0/90.

**Known weakness.** Rule 1's "mention" test is a word-matching heuristic made for short lines. It sometimes
rejects a valid change. The rate has not been measured.

## 7. The memory guard hook

The checks only see what goes through the compile. A session can also write memory directly, and in the
replay benchmark that path defeated the checks: when the memory writer recorded what tools reported, the
checked compile without a write-time guard accepted 90 of 90 planted claims, the same as doing nothing.

So the plugin installs a hook on the write side. Within one turn:

- A new prompt starts the turn clean.
- A web fetch, a web search, a shell command or any MCP tool call marks the turn as having taken in outside
  text.
- From then on, a write to a protected path is denied: the profile, Claude Code's memory folders and
  `~/.claude/CLAUDE.md`. The text of the attempted write is held as `tool-output` evidence, and the next
  compile decides what to do with it under the rules above.

The hook's state holds tool names only, never content. If the guard itself fails, it denies the write.

## 8. Erase

Erase removes every profile line containing a value, with its lineage, pass records, answers and evidence. It
records hashes of the erased lines so that a later pull from account memory cannot bring them back, approves
the deletion of any file it leaves empty, and marks transcripts as read so the compile does not re-learn the
value from them. On request it also rewrites the profile's git history.

Raw copies in other apps (transcripts, chat exports) belong to those apps. Erase reports where such copies
remain and does not delete them.

A review of the erase code found four ways an erased value could return through the full system (a later
pull, a file left with no facts, transcript messages not yet read, and values written with JSON escapes). Each
was fixed and pinned with a test. The fixes have not been exercised against live account memory.

## 9. How Claude Code reads the profile

Each compile regenerates `claude-code.md`, and the user's `~/.claude/CLAUDE.md` imports it with one `@path`
line. The index holds:

- the lines of `profile.md`, inline;
- one line per other profile file, with its path and description, and an instruction to read the matching
  file before answering a question about the person.

This mirrors how chat sees account memory: a core is injected and the rest is read on demand.

Two additions exist and are off by default. Each is switched on in `~/.config/unified-memory/config.json`.

**The standing list** (`"standing": true`). After a compile, a model labels each profile line as standing (a
preference, constraint, habit or rule that should shape an answer even when the prompt does not mention it)
or reference. The standing lines are then listed inline in the index.

**The prompt hook** (`"prompt_hook": true`). It scores every profile line against each prompt by word overlap
weighted by rarity, using expansion words written per line at compile time, and adds the best matches to the
prompt. It was built on the expectation that Claude Code would often answer without opening profile files.

On the recall bench that expectation did not hold (RESULTS.md section 2; one run per setup, Claude Sonnet,
labels and checks written by Claude). With the index alone, Claude Code answered 45 of 45 held-out questions.
The index plus the standing list answered 44 of 45, and so did the index plus the standing list and the
hook. On 20 implicit tasks the index passed 17 and each of the other two passed 19; hook minus index is +10
points [-10 to +30], a tie. The standing list raised mean input tokens per question session from 17.2k to
23.7k. By this project's rule that the simpler design wins a tie, both ship off.

Offline, the hook's retriever did improve: held-out recall went from 36% to 56%, and from 0% to 43% on
paraphrased questions. That gain did not carry over end to end, because a session with the index already
reads the right file.

On PrefEval, where the answering model cannot open files, the profile condition had the standing list on,
and standing lines are what put the stated preference in context.

## 10. The bridge to account memory

The bridge is a scheduled task created in a claude.ai chat and bound to the machine that holds the profile.
The split of work is deliberate:

- **Local code decides what may be pushed.** `prepare` builds an outbox: the profile files filtered by a
  category policy, plus a manifest. Each category is in one of three states: pushed, kept local, or never
  stored. A small model labels each line with a category, and because that label can be wrong, code also
  blocks card, ID and credential patterns whatever the label says. The manifest never carries the text of a
  filtered line, because the task that reads it runs in the cloud.
- **The task only copies.** It writes each prepared file to account memory with a version check, pulls
  changed memory files back into an inbox, and appends a log line. Its prompt tells it to copy, not judge,
  and to treat file contents as data.

Safeguards:

- **Propose-only first.** The task starts in a mode that writes nothing to account memory and produces a
  proposal to read. Live mode is refused until two reviewed runs in a row have something proposed and nothing
  rejected. A rejection on a live run closes the gate again.
- **Versions.** Each push expects the memory version last pulled. If a chat has edited the file since, the
  push becomes a conflict file and memory is left alone.
- **Three-way merge of pulls.** A pulled file is merged against the last text both sides agreed on. Lines a
  chat added are added, lines it removed are removed, erased lines are never re-added. With no such base
  nothing is merged, so the next push conflicts instead of overwriting the chat's edit.
- **No deletion on its own.** A memory file that is no longer in the profile is listed as a proposal. It is
  deleted only after the person approves that path.
- **Failure leaves memory as it was.** On any tool error the task stops and logs.

Limits, all from observation on one account in November 2026 and none documented as guarantees: the task must
be created from a chat with the folder attached; the first run needs one approval click on the machine; the
Claude desktop app must be open for every run; the machine must be awake. In one live run the task's model
declined to rewrite two unchanged files on its own judgement, so "copy, do not judge" did not fully hold;
`prepare` now skips files memory already holds. The memory and device tools the task uses may change or be
withdrawn.

## 11. Model calls

By default every model call goes through `claude -p` on the user's own Claude plan, with tools disabled, so no
API key is needed. The routes are `subscription` (default), `api`, and `hybrid`. The model calls are the
compile, the bridge's category labels, and the one-time clean-up when a profile is first built from existing
memory. With the standing list or the prompt hook switched on, the standing labels or expansion words are
written by a further call after each compile. The checks, the hooks, erase, undo and
`prepare` use no model.

## 12. How the design was chosen

The project started from a larger design and built it one rung at a time, keeping a rung only if it beat the
one below on a benchmark. The rungs:

| Arm | What it adds | Outcome |
| --- | --- | --- |
| Z | nothing: the stores as written | the baseline |
| A0 | Anthropic's shipped `consolidate-memory` skill, run automatically | worse than Z or tied (replay); -6 points [-13 to +1] on LongMemEval-S, a tie. Not kept. |
| A | one pass over every store in one context, writing a new version | tied Z on the replay and on LongMemEval-S. Kept only as a one-time clean-up when a profile is first built from existing memory. |
| B | A plus origin on every line, the code checks, lineage, a question budget, a change cap and the write-time hook | beat Z on both replay seeds. This is what ships. |

An earlier prototype used a retrieval-and-judge pipeline (BM25 and embedding candidates, an entailment judge)
to find contradictions between stores. A single model pass over the whole store beat it on both splits of a
small trial, so it was dropped as the adjudicator. On the test split (47 statements, 21 labelled pairs, a
fictional user) the single pass scored precision 0.95 and recall 1.00 against the prototype's 0.83 and 0.90.
On the dev split (68 statements, 22 labelled pairs) it scored 0.96 and 1.00 against 0.91 and 0.91. That is
one run per split, on hand-written statements, with labels written by the same model family that built the
prototype. The test split is published (`prototype/data/test/`, with the single pass's output in
`experiments/blind-trial/findings_test.json`). The dev split is paraphrased from real stores and is not. The
profile is small enough to fit in one context, and the design relies on that.

Tried and not needed, by the rule that the simpler design wins a tie:

- A0 and A as the recurring pass.
- The prompt hook and the standing list as defaults (section 9).

## 13. Not built

These were in the larger design and are neither built nor measured:

- **Pinned facts.** Anything the person confirms becomes a test every later build must pass.
- **Probes.** Checks the harness runs itself against an approved source, to update facts about a system.
- **Promotion by demand.** Adding the answer to a question the person has asked more than once.
- **An echo check.** Counting the same evidence once when it is cited from several stores.
- **Typed transitions** (correction, change, exception), **dependency links** between facts, and **facts by
  reference** in skills in place of embedded copies.
- **Retrieval over chat history.**
- **A digest page.** Receipts and questions are plain files and command output.

## 14. Open questions

- Whether the checked compile helps on real, messy stores. On the one set of real stores tried (data not
  published) it applied no changes. It acts only on new cited evidence, so it does not find problems that
  are already inside a store.
- What to do when questions go unanswered. With no answers the compile holds every system change it cannot
  confirm, and stale facts become its main error.
- How well the index scales. The recall bench profile has 34 files. A much larger profile may need retrieval
  after all.
- Whether the bridge's platform behaviour is stable.
- Whether any of this holds under a judge or labeller from another model family, or under human evaluation.
