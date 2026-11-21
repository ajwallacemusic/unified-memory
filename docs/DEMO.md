# Demo: answering from past conversations

Four questions put to a headless Claude Code session (Sonnet) with the Unified Memory plugin loaded from
`--plugin-dir`, recorded on 2026-11-20. The only tools in the session were the plugin's two search tools
(`conversation_search`, `recent_chats`); the init event shows its MCP server connected and nothing else.

**The data is synthetic.** Each question comes with its own LongMemEval-S haystack (MIT licence): 45 to 51
generated chat sessions about a fictional user. Each session's search index holds only that haystack, built the
way the search gate builds it (4,000-character chunks, shipped settings). As in the gate's `profile+search`
condition, the session's `CLAUDE.md` holds a short profile compiled from the same synthetic chats.

**How the questions were picked.** Three questions from the 100-question test set that `profile+search` answered
correctly in the gate (`results/search-gate/2026-11-lme/`), one each of knowledge-update, temporal-reasoning
and multi-session, chosen for short answers, plus one abstention question it declined correctly there. Each was
run once in the recorded setup; no question was swapped after seeing an answer (the one extra run, without
the profile, is shown under question 1). Picking from questions the gate got right
favours success, so these show how the plugin works, not how often it works (for that see
[RESULTS.md](RESULTS.md)). The question text includes the date it was asked, as in the benchmark.

Raw transcripts: `results/demo/2026-11-20/` (stream-json; the account rate-limit event is removed).

---

## 1. Knowledge update: profile only, no search (pass)

> Question (asked on 2023/08/01): How many stars do I need to reach the gold level on my Starbucks Rewards app?

**Tool calls:** none. The profile line answered it:
`Has a Starbucks Rewards app account and is working toward Gold level, which needs 120 stars (2023-07-30)`

**Answer:** You need **120 stars** to reach Gold level on your Starbucks Rewards app. That's the figure you gave
me on 2023-07-30. I don't have your current star count, so I can't tell you how many more you need.

**Gold:** 120

Before the recorded run, the same question was tried once with no profile (search only; transcript
`noprofile-0f05491a.jsonl`). Search returned two older chats in which the assistant said 300 stars, and Sonnet
answered 300: wrong. The updated figure lives in the profile, which is why it is there.

## 2. Temporal reasoning: two searches (pass)

> Question (asked on 2023/03/26): How many days passed between the day I repotted the previous spider plant and
> the day I gave my neighbor, Mrs. Johnson, a few cuttings from my spider plant?

**Tool calls:**
1. `conversation_search {"query": "spider plant repotted", "max_results": 10}`
2. `conversation_search {"query": "Mrs. Johnson spider plant cuttings neighbor", "max_results": 10}`

**Top results:**
- 2023-03-04: *"By the way, I repot the previous spider plant today, and it's now enjoying its new pot..."*
- 2023-03-18: *"By the way, I gave my neighbor, Mrs. Johnson, a few cuttings from my spider plant today..."*

**Answer:** **14 days** passed between the two events. You repotted the previous spider plant on March 4, 2023.
You gave Mrs. Johnson the cuttings on March 18, 2023. I took both dates from the dates of the conversations where
you mentioned each one. In both, you said "today".

**Gold:** 14 days (15 counting the last day is also accepted)

## 3. Multi-session: one search, two sessions (pass)

> Question (asked on 2023/03/01): How many days did it take for me to receive the new remote shutter release
> after I ordered it?

**Tool call:** `conversation_search {"query": "remote shutter release ordered"}`

**Top results (two different sessions):**
- *"...I also ordered a new remote shutter release online on February 5th, after I realized I lost my old one..."*
- *"...I got a new remote shutter release that arrived on February 10th, and it's been a game-changer."*

**Answer:** It took **5 days**. You ordered the remote shutter release on February 5th and it arrived on
February 10th.

**Gold:** 5 days (6 counting the last day is also accepted)

## 4. Abstention: a false premise (partial)

> Question (asked on 2023/10/15): How long have I been living in my current apartment in Shinjuku?

The user never mentioned Shinjuku; they live in Harajuku.

**Tool call:** `conversation_search {"query": "studio apartment Tokyo moved living", "before": "2023-10-16"}`

**Top results:**
- 2023-04-11: *"...I've been enjoying the independence of my new studio apartment in Harajuku - it's been a month now..."*
- 2023-10-15: *"...By the way, I've been living in Harajuku for 3 months now..."*

**Answer:** Your most recent statement, on 2023-10-15, was that you'd been living there for 3 months. One
correction: your records say the apartment is a studio in Harajuku, not Shinjuku. Your earlier statements don't
line up with that. On 2023-04-11 you said you'd been there about a month. If that were right, you'd be at about
7 months by 2023-10-15. I'm going with the more recent figure, but one of the two is off.

**Gold:** The information provided is not enough. You mentioned living in Harajuku but not Shinjuku.

It caught the false premise and named it, but it led with a figure for the Harajuku flat instead of declining.
In the gate run (Haiku) the same condition opened with "I don't have any record of a Shinjuku apartment." This
answer was graded by reading it, not by the benchmark's judge, and it is counted here as partial, not a pass.

---

**Summary:** 3 of 4 matched the gold answer; the abstention case was partial. One run per question, Sonnet in
Claude Code, graded by reading the answers against the gold. That is a demo, not a measurement.
