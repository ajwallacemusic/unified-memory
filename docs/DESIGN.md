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

Conversation search (section 11) sits beside both. It reads the same transcripts into a separate local index
of what was said, and it never writes the profile.

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

Two more things are dropped whole:

- **Non-interactive sessions.** A session started with `claude -p` (Claude Code records its entrypoint as
  `sdk-cli`) is skipped entirely. Its prompts come from a script, not from the person. The recall bench runs
  its questions through `claude -p`, and before this rule was added those prompts were eligible as `user-said`
  evidence on the machine that ran the bench.
- **Search output.** A quote from an old conversation is not new evidence. The result of
  `conversation_search` or `recent_chats` is dropped by tool name on any MCP server whose name contains
  `um-search` or `unified-memory`, so it does not matter how the server was registered. Any tool result that
  starts with the notice every search response begins with is dropped too, which covers the command-line
  search run through a shell.

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

Erase also reaches the conversation-search index, which is the plugin's own copy of conversation text
(section 11).

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

A later run with Claude Haiku answering agrees. The index answered 44 of 45 questions, the standing setup 41
and the hook setup 42. On implicit tasks they passed 15, 16 and 17 of 20, and hook minus index is again +10
points [-10 to +30].

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

## 11. Conversation search

The profile holds what is true about a person now. It does not hold what was said in a conversation: on
LongMemEval-S, 100 questions about past sessions, the compiled profile alone scored 42 (RESULTS.md section 6).
Conversation search covers that half. It follows claude.ai's own chat search: two tools the model calls,
`conversation_search` (a keyword query; 1 to 10 results, 5 by default) and `recent_chats` (1 to 20 sessions by
date).

**Sources.** One local index over three kinds of conversation.

| Surface | Read from | How fresh |
| --- | --- | --- |
| Claude Code, terminal and IDE | its transcript files | caught up before every query |
| Claude desktop app, local agent sessions | the Claude Code transcripts inside the app's session folders | the same |
| claude.ai chats (web, desktop chats, mobile) | the account data export, which the person requests and imports | as old as the last export imported |

Not reachable: cloud sessions that the export does not contain, and which project a claude.ai chat belongs to
(the export does not say). The plugin does not call claude.ai, scrape it or read the desktop app's cache.

**What is indexed.** The text the person typed and the text the assistant wrote. Tool calls are kept as tool
names only. Tool results, thinking, attachments, system-inserted text, compaction summaries, subagent
transcripts and non-interactive (`claude -p`) sessions are never indexed. A non-interactive session is
recognised from any record in its file, and one already indexed is removed when it is recognised. A typed turn
longer than 4,000 characters is cut to its first 4,000, because long turns are mostly pasted material.

**Chunks and ranking.** The unit is an exchange: one typed turn and the assistant text that follows it. An
exchange longer than 4,000 characters is split at paragraph breaks, and each part of the answer carries the
first 300 characters of the question so that it still matches the question's words. Ranking is BM25 over the
session title and the chunk text (the repository's own implementation: k1 1.2, b 0.75, no stemming, a short
stop list), the same code the benchmark runs. A result list holds at most one chunk per session, unless the
search is inside one session. A score is multiplied by `0.5 + 0.5 × 0.5^(age in days / 90)`, so an old
conversation keeps at least half its score. Both tools take `after` and `before` dates, and
`conversation_search` can sort by relevance, newest or oldest. The session that is asking is left out unless
asked for. There are no embeddings and no model call.

**Results.** Each result is a citation: surface, title, project, date, session id, a claude.ai link or a
`claude --resume` command, and a snippet of at most 500 characters with each line labelled `user:` or
`assistant:`. A whole response is at most 8,000 characters.

**The index.** One SQLite file, by default `~/.local/share/unified-memory/search.sqlite` (config key
`search_index`). The command-line tool refuses a location inside a git work tree, the profile folder or
`~/.claude`. The index is the durable copy for search: Claude Code deletes its transcripts after 30 days by
default (Claude Code documentation, read November 19, 2026), and a session's chunks stay in the index when its
file goes. Before this feature the plugin kept no conversation text, which is why the privacy rules below are
strict.

The index records the chunk size and lead it was cut with. When the current values differ, it is re-cut in
place from the text it already holds, so a session whose transcript is gone is kept. This happens on first
use, and `search rebuild` forces it. A turn that erase has removed part of is left as it is.

**Freshness.** Before it answers, the search server reads what has changed in the Claude Code and desktop
transcripts, from a stored offset. Only closed exchanges are indexed: one followed by a later typed turn, or
one whose file has been idle for five minutes. An exchange closed for being idle is read again if its file
grows, so text written later joins it. A line that cannot be parsed is skipped, and a file that fails is left
for the next catch-up and reported by `search status` without stopping the others. A hook also runs a
catch-up in the background at session start, so sessions reach the index before Claude Code deletes them.

A claude.ai export is imported by hand (`python3 -m um.cli search import-export PATH`). New conversations are
added and changed ones replaced; importing the same export twice adds nothing. A conversation missing from a
newer complete export is taken as deleted on claude.ai and removed (`--keep-deleted` turns that off). An
export counts as complete only when that is shown: its manifest lists its conversation files and every one
was read, or it is a single `conversations.json` with no manifest beside it. A single zip, one part of a larger
export, or a folder with no manifest adds and replaces and never removes. An export older than the last one
imported is refused unless forced, and when forced it still removes nothing.

**How Claude Code reaches it.** The plugin declares a stdio MCP server, `um-search`. It is hand-written JSON-RPC
on the Python standard library, with no MCP package. Its tools are loaded at session start (`alwaysLoad`), so
they are available on any turn at the cost of two tool definitions per session. The same functions are on the
command line: `python3 -m um.cli search query|recent|index|import-export|status|forget|rebuild`.

**Off switch.** `"search": false` in `~/.config/unified-memory/config.json` turns the feature off. The
session-start catch-up then does nothing, the `index`, `query` and `recent` commands refuse, and the two tools
answer that search is off without reading or updating the index. The setting is read on every call. The index
file is left as it is.

**Coexistence with the profile.** The server's instructions say: the profile for what is true now, search for
what happened or was said; if a search result disagrees with the profile or with what the person says now, the
profile and the person win. Search never writes the profile. The compile drops the results of these two tools
from its evidence (section 5). The memory guard already treats any MCP call as outside text, so a turn that
searched cannot write memory directly (section 7).

**Privacy.**

- The indexer, the server and the command line make no network call and call no model.
- The export script that builds the public repository refuses any SQLite file, and the bridge copies only
  profile files, so the index cannot reach either.
- The readers open only transcripts and a fixed list of metadata fields. They never open the credential files,
  audit logs, uploads or outputs that sit in the same folders.
- Every response starts with a notice that the results are quotes from earlier conversations, not
  instructions, that they may be out of date, and that they do not override the profile or the person.
- Erase first stores a salted hash of the value and its length, never the value. On any later import, every
  window of that length in a chunk's text is hashed the same way and the chunk is dropped on a match. That is
  the test erase itself uses, a case-insensitive substring match with JSON escapes decoded, run against
  hashes. Erase then removes every chunk that contains the value, records the removed chunks so a re-read does
  not bring them back, and compacts the file so the text does not remain in free pages. With no index yet, it
  creates one holding only that hash. `search forget --session ID` removes one session, and `search forget
  --all` empties the index of conversation text in place and compacts it, keeping the erase hashes so a
  rebuild cannot bring an erased value back.

**How it was decided.** The rule was written before any run: search ships only if adding it to the profile
improves LongMemEval-S with an interval above zero, costs at most one abstention question, and leaves PrefEval
within two points with an interval that includes zero. All three held (RESULTS.md section 6): 74 of 100 (75.75
as the mean of four runs, three of them made later) against 42 for the profile alone (+32 points [+22 to
+42]), abstention 19 of 20 against 20, PrefEval 93 against 94 (-1 [-6 to +4]). Chunk size, lead, results per
session and the recency decay were chosen on 400 separate questions with no model.

**Review after the tests.** A code review by Claude (Fable 5.2) after those runs rated no finding critical and
11 important. All 11 were fixed with tests before the merge, and the behaviour described in this section is the
behaviour after the fixes: the erase guard and `forget --all`, late text and unreadable lines in transcripts,
partial and older exports, non-interactive sessions recognised late, the per-session limit applied before the
candidate list is cut, the recorded chunk size, the wider match for search output in compile evidence
(section 5), the off switch, and a rebuilt plugin bundle. About 16 smaller findings are open. The benchmark
numbers above were measured before the fixes and were not measured again (RESULTS.md section 6.6).

Embeddings had their own rule: build them only if search trails full context and at least half of its losses
are questions where no answer session was retrieved. Search does trail full context (-17 [-27 to -8]), but only
2 of the 21 losses were such questions, and in both the model had not searched at all. So embeddings were not
built, and the plugin stays on the standard library.

**Known weaknesses.**

- Search is well behind reading the whole history, and behind an earlier arm that gave the model raw session
  files to read (85 of 100 on the same questions, in a different run). In 19 of its 21 losses to full context
  the model had the right session in its results and still answered wrong. Snippets are 500 characters and
  there is no tool to read a whole past session. One was built and tested, `read_chat`. Over four runs per arm
  it showed no measurable gain, and one abstention question was lost in every run with the tool, so it did
  not ship (RESULTS.md section 6.8).
- The PrefEval test passed without the model calling search once, so it says nothing about search results
  distracting from a stated preference.
- How often a real Claude Code session calls the tools, rightly or wrongly, has not been measured. In four
  live sessions on one real index Claude called search for all four questions (RESULTS.md section 6.7). That
  is not a rate.
- The notice and the server instructions are the only thing between a quoted instruction in an old
  conversation and the model. The compile and the memory guard stop a quote from changing the profile or
  memory. Nothing in code stops the model from acting on one in the current turn.
- claude.ai chats are as stale as the last export, and importing one is a manual step with no slash command.
- The recency decay rests on one question of 400 in tuning and was not tested on real conversation dates.
- One index per operating-system user. Accounts are not separated.

## 12. Model calls

By default every model call goes through `claude -p` on the user's own Claude plan, with tools disabled, so no
API key is needed. The routes are `subscription` (default), `api`, and `hybrid`. The model calls are the
compile, the bridge's category labels, and the one-time clean-up when a profile is first built from existing
memory. With the standing list or the prompt hook switched on, the standing labels or expansion words are
written by a further call after each compile. The checks, the hooks, erase, undo,
`prepare` and conversation search use no model.

## 13. How the design was chosen

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
- `read_chat`, a third search tool that reads a whole past session. It failed a rule fixed in advance, in two
  rounds of four runs per arm, and stays on an unmerged branch (RESULTS.md section 6.8).

Conversation search was the next rung and had its own tests, fixed before the runs (section 11). It passed
them and ships on.

## 14. Not built

These were in the larger design and are neither built nor measured:

- **Pinned facts.** Anything the person confirms becomes a test every later build must pass.
- **Probes.** Checks the harness runs itself against an approved source, to update facts about a system.
- **Promotion by demand.** Adding the answer to a question the person has asked more than once.
- **An echo check.** Counting the same evidence once when it is cited from several stores.
- **Typed transitions** (correction, change, exception), **dependency links** between facts, and **facts by
  reference** in skills in place of embedded copies.
- **A digest page.** Receipts and questions are plain files and command output.

Retrieval over chat history was on this list and is now built (section 11). For it, these are not built:

- **Embeddings or reranking.** The rule for building them was not met.
- **Reading more than a snippet.** A tool to fetch a whole past session was tried and not shipped (section
  13). Longer snippets were not tried.
- **Search from the desktop app's chats.** The search server is registered with Claude Code only. The desktop
  app's configuration is not touched.
- **Live claude.ai conversations.** They enter the index only through an export the person imports.
- **Project scope for claude.ai chats**, separate indexes per account, and Windows.

## 15. Open questions

- Whether the checked compile helps on real, messy stores. On the one set of real stores tried (data not
  published) it applied no changes. It acts only on new cited evidence, so it does not find problems that
  are already inside a store.
- What to do when questions go unanswered. With no answers the compile holds every system change it cannot
  confirm, and stale facts become its main error.
- How well the index scales. The recall bench profile has 34 files. A much larger profile may need retrieval
  after all.
- How to keep the compile from missing a fact in a long history. On PrefEval with 300 inter-turns, where one
  compile call reads about 162,000 tokens, it stored nothing for 17 of 100 items, against 4 of 100 with 10
  inter-turns (RESULTS.md section 1.1). Every profile failure in that run was one of those 17.
- Whether the bridge's platform behaviour is stable.
- Whether Claude Code calls conversation search when it should and leaves it alone when it should not, and
  whether search results in context change how well a stated preference is followed. Neither was measured.
- Whether a conversation deleted on claude.ai should leave the index at the next export (the current
  default) or stay until the person removes it.
- Whether any of this holds under human evaluation. A second judge from another model family (OpenAI) agreed with
  Haiku on 91 to 96% of 1,100 saved answers and changed no ranking (RESULTS section 8.1).
