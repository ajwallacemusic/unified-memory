# Label check

**Result (2026-11-20):** AJ read all 30 items and agreed with every one (said in the session; boxes below
not ticked one by one). 15 of 15 recall questions fair with the right answer terms; 15 of 15 Haiku verdicts matched.

Labels were written by Claude models; implicit-task verdicts by a Haiku judge. Mark one box per item.
Part A: is the question fair and are the answer terms right? Part B: does the verdict (hit = the answer acted on the stored fact) match your reading?

## Part A: recall questions

### 1. q062

Question: Which word do I keep getting wrong in my Portuguese lessons?
Answer terms: ficar
File: topics/portuguese.md

Profile lines:
    - [stated] Struggles most with nasal vowels and with the verb "ficar"

Your verdict: [ ] agree  [ ] disagree  — note:

### 2. q068

Question: What's the most reliable way to get hold of my mother?
Answer terms: landline
File: people/parents.md

Profile lines:
    - [stated] Mom doesn't text: call the landline or send email

Your verdict: [ ] agree  [ ] disagree  — note:

### 3. q080

Question: What's the name of the relative who grew up in the city where our May trip ends?
Answer terms: Fernanda
File: areas/portugal-trip.md, people/partner.md

Profile lines:
    - [stated] His mother, Fernanda, grew up in Porto; he understands Portuguese but answers in English

Your verdict: [ ] agree  [ ] disagree  — note:

### 4. q028

Question: Which city were we based in until this past summer?
Answer terms: Madison
File: profile.md

Profile lines:
    - [stated] Lives in Minneapolis, MN, in the Longfellow neighborhood; moved there from Madison, WI in Aug 2026

Your verdict: [ ] agree  [ ] disagree  — note:

### 5. q004

Question: What's the name of the feature flag for the Kestrel cutover?
Answer terms: quote_router_v2
File: areas/kestrel-migration.md

Profile lines:
    - [stated] The cutover feature flag is named quote_router_v2

Your verdict: [ ] agree  [ ] disagree  — note:

### 6. q034

Question: What stone did we choose for the worktops in the kitchen?
Answer terms: soapstone
File: areas/kitchen-remodel.md

Profile lines:
    - [stated] Counters are soapstone around the sink and butcher block on the island

Your verdict: [ ] agree  [ ] disagree  — note:

### 7. q074

Question: Who will be acting as my manager on the day of the Kestrel cutover?
Answer terms: Rashid
File: areas/kestrel-migration.md, people/manager.md

Profile lines:
    - [stated] On leave from 1 to 19 March 2027; Rashid is acting manager while she is out

Your verdict: [ ] agree  [ ] disagree  — note:

### 8. q058

Question: Which flowers did I promise my daughter space for in the garden?
Answer terms: zinnia
File: topics/gardening.md

Profile lines:
    - [stated] Spring plan: Sungold and San Marzano tomatoes, pole beans, kale, and a row of zinnias for Linnea

Your verdict: [ ] agree  [ ] disagree  — note:

### 9. q048

Question: Which country's coffee do I usually buy?
Answer terms: Kenya
File: topics/coffee.md

Profile lines:
    - [stated] Prefers light-roast Kenyan beans, washed process; dislikes dark roasts

Your verdict: [ ] agree  [ ] disagree  — note:

### 10. q008

Question: What was our entry point for the Boundary Waters canoe trip?
Answer terms: Sawbill
File: areas/boundary-waters-trip.md

Profile lines:
    - [stated] Entry point was Sawbill Lake; base camp was on Cherokee Lake for two nights

Your verdict: [ ] agree  [ ] disagree  — note:

### 11. q036

Question: Which district are we sleeping in for the final leg of the Portugal vacation?
Answer terms: Cedofeita
File: areas/portugal-trip.md

Profile lines:
    - [stated] Last six nights are in Porto, in a flat in the Cedofeita neighborhood

Your verdict: [ ] agree  [ ] disagree  — note:

### 12. q072

Question: Who takes our pet in when we go away?
Answer terms: Ottoline
File: people/neighbors-and-sitters.md

Profile lines:
    - [stated] Dog sitter is Ottoline, who boards greyhounds at her own house for $55 a night

Your verdict: [ ] agree  [ ] disagree  — note:

### 13. q024

Question: What year did Idris and I get married?
Answer terms: 2016
File: people/partner.md

Profile lines:
    - [stated] Birthday is 27 September; wedding anniversary is 12 October (married in 2016)

Your verdict: [ ] agree  [ ] disagree  — note:

### 14. q038

Question: Which national park did I say I'd like to hike after the Boundary Waters?
Answer terms: Isle Royale
File: areas/boundary-waters-trip.md

Profile lines:
    - [stated] Wants to backpack Isle Royale next, tentatively in 2028

Your verdict: [ ] agree  [ ] disagree  — note:

### 15. q002

Question: What's my team's ticket prefix in Linear?
Answer terms: DSP
File: areas/work-quillhaven.md

Profile lines:
    - [stated] Tickets are in Linear; the team prefix is DSP

Your verdict: [ ] agree  [ ] disagree  — note:

## Part B: implicit-task verdicts

### 16. i32 (condition: standing)

Task prompt:

````
Make me a calendar for next spring for the two raised beds: when to start the tomatoes, kale and zinnias indoors, when to sow the beans, and when everything goes outside.
````

Check question: Does the calendar account for her being away from 8 to 22 May (for example, planting out after she is back, or arranging care for the seedlings)?
Stored fact: - [stated] Portugal trip runs 8 to 22 May 2027: Lisbon first, then the Douro valley, then Porto

Model answer:

````
Here's the spring 2027 calendar, built around your 15 May last frost. The Portugal trip (8–22 May) changes the usual schedule: nothing tender can go out before 15 May, and you'll be away for that whole window.

| When | What | Notes |
|---|---|---|
| **Sat 27 Feb** | Start **kale** indoors | Sow about 7 weeks before it goes out. |
| **Mid-March** | Order or build the **hardware-cloth fence** for both beds | It needs to be up before anything goes out. |
| **Sat 10 Apr** | Start **tomatoes** (Sungold and San Marzano) indoors | This is later than the usual 6–8 weeks before frost. They'll be small but not leggy when you leave. |
| **Sat 10 Apr** | Start **zinnias** indoors | They only need 4–6 weeks. |
| **Sat 17 Apr** | Harden off kale for a week, then **plant it out** (~24 Apr) | Kale tolerates frost. Plant it behind the fence. |
| **Thu 6 May** | Last watering and feeding check, and **set up the seedlings for your absence** | Move the tomatoes and zinnias to a bright spot and use bottom-watering trays. |
| **8–22 May** | Portugal | Seedlings stay indoors the whole time. |
| **Sun 23 May** | Seedlings back from Portugal. **Start hardening off tomatoes and zinnias** | Put them out for [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 17. i26 (condition: full)

Task prompt:

````
Callum and Yuki want to take the kids to the 7 pm showing of the new animated film on Thursday. Draft my reply and sort out the logistics.
````

Check question: Does the reply raise that a 7 pm showing runs past Linnea's bedtime (declining, or proposing an earlier showing)?
Stored fact: - [stated] Bedtime is 7:45, with reading until 8:15

Model answer:

````
Two things to settle before you send this.

**Which Thursday?** Today is Thursday 19 Nov, so "Thursday" could mean tonight or next week. Next Thursday is 26 Nov, which is Thanksgiving, and Greta arrives the day before. I've left the date open in the draft.

**Bedtime.** Linnea's bedtime is 7:45, so a 7 pm showing will run well past it. It's a school night, and she has school the next day (9:10 start). It's your call whether that's fine as a one-off.

**Logistics**
- **Calendar:** Nothing on your side conflicts. Chess club is Tuesday, cello is Wednesday, and Thursday afternoon is your focus block. The dog's 8 pm walk would fall to Idris, or move earlier.
- **Dinner:** The film starts at 7, so she'd need to eat before. Either feed her at home around 5:30, or ask whether Callum and Yuki are doing a quick dinner first.
- **Transport:** Emeka is in her grade, so it's natural for Callum and Yuki to drive. Ask what time they'd drop her home. If the film ends around 8:45, expect her back about 9.
- **Idris:** Run it past him, since it affects bedtime and the school morning. Also check whether he wants to come.
- **Cost:** The ticket is well under your $200 "talk it through" threshold, so n [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 18. i28 (condition: none)

Task prompt:

````
The orchestra added an extra rehearsal on Wednesday 9 December, 7 to 9, and Idris has conferences that evening. Line up someone to be with Linnea: draft the message.
````

Check question: Does the response recognise that the usual babysitter is not available on Wednesdays and ask someone else (such as Renata) instead?
Stored fact: - [stated] Babysitter is Saskia, a college student; $18 an hour; never free on Wednesdays

Model answer:

````
Here's a draft. I don't know who you'd send it to or how old Linnea is, so I've left a few placeholders.

**Draft (text or group chat):**

> Hi [name]! Could you do us a favour? The orchestra added an extra rehearsal on Wednesday 9 December, 7 to 9pm, and Idris has conferences that evening, so we need someone to be with Linnea while we're both out. Would you be free to come over then? Happy to work around dinner and bedtime, and I'll leave everything you need. If it doesn't work, no worries at all. I just wanted to ask early so I have time to find someone else.

**Shorter version:**

> Hi [name]! Are you free Wed 9 Dec, 7 to 9pm? The orchestra added a rehearsal and Idris has conferences, so we need someone with Linnea. Let me know either way, thanks!

A few things you could add:
- **Where:** whether they'd come to you or Linnea would go to them.
- **Routine:** dinner, bedtime or homework, if any of it falls in that window.
- **Return favour or payment:** if you want to offer one.
- **Backup:** a second person to ask if the first can't do it.

Tell me who you're sending it to and I'll tailor the tone, for example for a grandparent, a friend or a sitter.
````

Haiku verdict: miss

Your verdict: [ ] agree  [ ] disagree  — note:

### 19. i18 (condition: full)

Task prompt:

````
Thabo wants an hour to go through the changes to the event schema. He offered Thursday at 1:30 or Thursday at 3:00. Write my reply.
````

Check question: Does the reply turn down both Thursday-afternoon times, or ask for a time outside Thursday afternoon, rather than accepting one of them?
Stored fact: - [stated] Thursday afternoons are a no-meeting focus block

Model answer:

````
Both of Thabo's slots fall in your Thursday-afternoon focus block, so this draft declines them and offers other times. I don't know which Thursday he means, but if it's 26 November, that's Thanksgiving.

---

Hi Thabo,

Thanks for offering times. Thursday afternoons are my no-meeting focus block, so neither 1:30 nor 3:00 works. Could we do one of these instead?

- Tuesday, 9:30 to 10:30
- Wednesday, 10:00 to 11:00
- Friday, 10:00 to 11:00

If you'd rather split it, two 50-minute sessions would also work. To make the time count, could you send a short agenda or a list of the schema changes you want to cover? Your pipelines consume `quotes.requested`, so I'd like to know which fields or event shapes worry you most.

Thanks,
Wren

---

I picked the example slots to avoid Monday and Wednesday afternoons (school pickup), lunch, and anything before 9:30. Adjust them if your week looks different. Tell me if you'd rather keep it to a single Thursday-morning option, and I'll rewrite it.
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 20. i16 (condition: full)

Task prompt:

````
Propose three slots next week for a 50-minute session with Tomasz and Devika to walk through the cutover-day checks, and write the invite.
````

Check question: Do all the proposed slots finish by 11:00 am Central, the end of Tomasz's overlap from Warsaw?
Stored fact: - [stated] Tomasz: platform team, owns the deploy pipeline; based in Warsaw, so overlap ends at 11 am Central

Model answer:

````
**Proposed slots (US Central, 50 minutes each)**

1. **Mon 23 Nov, 10:00-10:50.** This is the cleanest option for everyone.
2. **Wed 25 Nov, 9:30-10:20.** It's the day before Thanksgiving, so Devika or Tomasz may be out. Tomasz is in Warsaw, where it's a normal working day.
3. **Tue 24 Nov, 10:10-11:00.** It starts just after the 10:00 on-call handoff. If the handoff runs long, this one slips, and it ends right at Tomasz's 11:00 cutoff.

All three start after 9:30 and end by 11:00, when Tomasz's overlap closes. They also avoid your lunch block, your Thursday focus time, and the Thursday 11:00 one-on-one with Oksana. I can't see anyone's calendar from here, so check availability before sending.

---

**Invite draft**

**Title:** Kestrel cutover-day checks: walkthrough

**Duration:** 50 min

**Invitees:** Tomasz, Devika

**Description:**

Hi Tomasz, Devika,

I'd like to walk through the cutover-day checks for Kestrel (target cutover 9 March 2027) so we can agree on the sequence and owners well before the date. Slot options are in the message with this invite. Please accept whichever works, or tell me if none do.

**Agenda**
1. Pre-flip checks (10 min): dual-write consistency, and the [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 21. i30 (condition: index)

Task prompt:

````
Build me a 16-week plan for the June half. Lay it out week by week, with the days I run.
````

Check question: Does the plan put the runs on Tuesday, Thursday, Saturday (the long run) and Sunday (easy), four days a week?
Stored fact: - [stated] Runs four days a week: Tuesday, Thursday, a Saturday long run and an easy Sunday

Model answer:

````
Here's the plan. Race day is Saturday 19 June 2027 in Duluth, so week 1 starts Monday 1 March 2027. It uses your four days: Tuesday, Thursday, Saturday long run and easy Sunday. Today is 19 November, so you have about three months of base-building before it starts. The target is under 1:55, which is about 8:47 per mile. That's roughly 1:45 faster per mile than your 1:58:40 best.

**Two things shaped it:**
- **Portugal, 8 to 22 May (weeks 10 to 12):** the plan bends around travel days and the hilly Douro leg.
- **Your left knee:** long runs build gradually past 10 miles, and the knee work stays at three times a week throughout.

Weeks run Monday to Sunday. Distances are in miles.

| Wk | Starts | Tue | Thu | Sat (long) | Sun | Total |
|---|---|---|---|---|---|---|
| 1 | 1 Mar | 4 easy | 4 easy + 4 strides | 8 | 3 easy | 19 |
| 2 | 8 Mar | 4 easy | 4 with 15 min tempo | 9 | 3 easy | 20 |
| 3 | 15 Mar | 4.5 easy | 5 with 2 mi tempo | 10 | 3 easy | 22.5 |
| 4 | 22 Mar | 4 easy | 4 easy + strides | 7 (cutback) | 3 easy | 18 |
| 5 | 29 Mar | 5 easy | 5 with 5×800 | 10 | 3.5 easy | 23.5 |
| 6 | 5 Apr | 5 easy | 5 with 3 mi tempo | 11 | 3.5 easy | 24.5 |
| 7 | 12 Apr | 5 easy | 6 with 3×1  [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 22. i30 (condition: none)

Task prompt:

````
Build me a 16-week plan for the June half. Lay it out week by week, with the days I run.
````

Check question: Does the plan put the runs on Tuesday, Thursday, Saturday (the long run) and Sunday (easy), four days a week?
Stored fact: - [stated] Runs four days a week: Tuesday, Thursday, a Saturday long run and an easy Sunday

Model answer:

````
# 16-Week Half Marathon Plan (June 2027)

I don't know your race date, current mileage, or which days you prefer, so I made some assumptions. Tell me the real values and I'll adjust.

**Assumptions:**
- You can already run about 12–15 miles a week comfortably.
- You want 4 run days a week: **Tue, Thu, Sat, Sun**. Mon, Wed and Fri are rest or cross-training.
- The race is on a Sunday. Count back 16 weeks from race day to find your start date. For example, a race on Sun June 13, 2027 means Week 1 starts Mon Feb 22.
- Distances are in miles. "Easy" means conversational pace. "Tempo" means comfortably hard, about 10K to 15K effort. "HM pace" means goal race pace.

| Wk | Tue | Thu | Sat | Sun (long) | Total |
|---|---|---|---|---|---|
| 1 | 3 easy | 3 easy | 3 easy | 5 | 14 |
| 2 | 3 easy + 4 strides | 3 easy | 3 easy | 6 | 15 |
| 3 | 3.5 easy | 3.5 with 10 min tempo | 3 easy | 7 | 17 |
| **4 (recovery)** | 3 easy | 3 easy | 3 easy | 5 | 14 |
| 5 | 4 easy + strides | 4 with 15 min tempo | 3 easy | 8 | 19 |
| 6 | 4 easy | 4 with 20 min tempo | 3 easy | 9 | 20 |
| 7 | 4 easy | 5 with 4×3 min hard (2 min jog between) | 3 easy | 10 | 22 |
| **8 (recovery)** | 3 easy | 4 easy | 3 easy | 7 | [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 23. i12 (condition: standing)

Task prompt:

````
Put a 60-second cache in front of the surcharge lookup in the new quote service, keyed by lane and date. Write the Go code and tell me what has to be provisioned.
````

Check question: Does the response use Valkey as the cache (naming Valkey or a Valkey client), not Redis, Memcached or an in-process map?
Stored fact: - [stated] Cache is Valkey, replacing an old Memcached cluster

Model answer:

````
There's no Go code in this directory, only `CLAUDE.md`. I couldn't see the real surcharge lookup or its types, so this is a self-contained decorator. You'll need to adapt the `Surcharge` type and the `Lookup` signature to match the service. I've also not compiled or run any of it.

## `surcharge/cached.go`

```go
package surcharge

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"golang.org/x/sync/singleflight"
)

const (
	TTL       = 60 * time.Second
	keyPrefix = "surcharge:v1:" // bump the version if Surcharge's shape changes
)

// Surcharge is a placeholder; use the service's real type. Keep money as
// integer minor units or a string decimal so a cache round trip never rounds.
type Surcharge struct {
	LaneID    string `json:"lane_id"`
	Date      string `json:"date"` // YYYY-MM-DD
	AmountMin int64  `json:"amount_minor"`
	Currency  string `json:"currency"`
}

// Lookup is the existing, uncached surcharge lookup.
type Lookup interface {
	Surcharge(ctx context.Context, lane string, date time.Time) (Surcharge, error)
}

// Store is the small slice of the Valkey client we need.
// Get returns (nil, nil) on a miss.
type Store interface {
	Get(ctx context.Context, key [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 24. i04 (condition: standing)

Task prompt:

````
Add a surcharge_overrides table to the new Go quote service and the data-access code for it: create, get by lane, list active. Show me the files.
````

Check question: Does the response write the queries as hand-written SQL with sqlc generating the Go code (no ORM such as GORM or ent, and no hand-rolled row scanning)?
Stored fact: - [stated] Writes SQL by hand and generates the Go code with sqlc; does not want an ORM

Model answer:

````
I couldn't write any files because the Write tool is disabled in this session, so nothing is on disk. The working directory only held `CLAUDE.md`, so I had no existing service layout to follow. Here is what I would have created, using your sqlc and no-ORM preferences. The Postgres 16 target and the rounding note come from your Kestrel notes.

**`db/migrations/0001_create_surcharge_overrides.sql`**
```sql
-- +goose Up
CREATE TABLE surcharge_overrides (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lane_id        TEXT           NOT NULL,
    surcharge_type TEXT           NOT NULL,
    -- NUMERIC, not float: shadow traffic already showed rounding mismatches.
    amount         NUMERIC(12, 4) NOT NULL CHECK (amount >= 0),
    reason         TEXT           NOT NULL DEFAULT '',
    active_from    TIMESTAMPTZ    NOT NULL DEFAULT now(),
    active_until   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CHECK (active_until IS NULL OR active_until > active_from)
);

CREATE INDEX surcharge_overrides_lane_idx
    ON surcharge_overrides (lane_id, active_from DESC);

-- +goose Down
DROP TABLE surcharge_overrides;
```

**`db/queries/surcharge_o [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 25. i02 (condition: full)

Task prompt:

````
Write the commit message for what's staged: I swapped the per-process LRU in the quote handler for the shared cache client and deleted the eviction goroutine that nothing uses any more.
````

Check question: Is the subject line in Conventional Commits form (a type prefix such as refactor: or refactor(quote):) and under 60 characters?
Stored fact: - [stated] Commit messages follow Conventional Commits, subject line under 60 characters

Model answer:

````
```
refactor(quotes): use shared cache client in quote handler

Replace the per-process LRU with the shared cache client and
remove the unused eviction goroutine.
```

The subject line is 56 characters, under your 60-character limit. If this touches production, the PR description will need a rollback note.
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 26. i14 (condition: index)

Task prompt:

````
The go/no-go for the rate-quote switch-over needs my manager's written sign-off on Monday 8 March 2027. Draft the request I'll send that morning.
````

Check question: Is the request addressed to Rashid as acting manager, or does the response note that Oksana is on leave on that date?
Stored fact: - [stated] On leave from 1 to 19 March 2027; Rashid is acting manager while she is out

Model answer:

````
Oksana is on leave from 1 to 19 March 2027, so the sign-off has to come from Rashid, who is acting manager. I've addressed the draft to him. Oksana likes decisions as a one-page memo with the recommendation at the top, so I wrote it that way.

---

**To:** Rashid
**Subject:** Sign-off needed today: Kestrel (rate-quote) cutover go/no-go, planned for Tue 9 March

Hi Rashid,

Since Oksana is out, I need your written sign-off on the Kestrel cutover. Please reply to this email with "approved" or "not approved" by [time], so we can go ahead tomorrow, 9 March, as planned.

**Recommendation:** Go. Flip `quote_router_v2` on tomorrow, moving rate quotes from the Python monolith to the new Go service.

**Why**
- **Latency:** The p99 target is 120 ms, and the old path sits around 410 ms. Current p99 on Kestrel: [X ms].
- **Correctness:** Shadow traffic showed a 0.3% mismatch rate on 27 Oct. It came from rounding: the old code used banker's rounding and the new code rounded half up. [Status: fixed on DATE, and the latest shadow run shows X% mismatch.]
- **Data:** The Postgres 16 dual-write has been running since October. [Any divergence between MySQL 5.7 and Postgres 16: none / details.]
- **Ca [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 27. i14 (condition: none)

Task prompt:

````
The go/no-go for the rate-quote switch-over needs my manager's written sign-off on Monday 8 March 2027. Draft the request I'll send that morning.
````

Check question: Is the request addressed to Rashid as acting manager, or does the response note that Oksana is on leave on that date?
Stored fact: - [stated] On leave from 1 to 19 March 2027; Rashid is acting manager while she is out

Model answer:

````
**Subject:** Written sign-off needed today: go/no-go for rate-quote switch-over

Hi [Manager's name],

I need your written sign-off today (Monday 8 March 2027) on the go/no-go decision for the rate-quote switch-over.

**Decision requested:** Approve or decline proceeding with the switch-over from [current rate-quote system/process] to [new system/process].

**Proposed cutover:** [date/time window]

**Where we stand:**
- [Testing/validation status, e.g. quote parity checks passed on X of Y scenarios]
- [Open issues and severity, or "no open blockers"]
- [Readiness of the teams and stakeholders affected]

**Rollback plan:** [one line: how we revert, who triggers it, and how long it takes]

**Recommendation:** [Go / No-go], because [one-sentence rationale].

**What I need from you:** A reply to this email by [time] confirming either "Approved to proceed" or "Not approved", plus any conditions. Your reply will serve as the written record.

If you'd like to talk through any of it first, I'm available at [time/contact].

Thanks,
[Your name]

---

I left placeholders for the things I don't know: the manager's name, the systems involved, the cutover window, test status, the rollback plan,  [...truncated]
````

Haiku verdict: miss

Your verdict: [ ] agree  [ ] disagree  — note:

### 28. i26 (condition: index)

Task prompt:

````
Callum and Yuki want to take the kids to the 7 pm showing of the new animated film on Thursday. Draft my reply and sort out the logistics.
````

Check question: Does the reply raise that a 7 pm showing runs past Linnea's bedtime (declining, or proposing an earlier showing)?
Stored fact: - [stated] Bedtime is 7:45, with reading until 8:15

Model answer:

````
Here's a draft reply and the logistics. I haven't sent anything, and I can't see Callum and Yuki's original message.

**Draft reply**

> Hi Callum and Yuki, Linnea would love that, and thanks for thinking of her! Thursday at 7 is a little late for her on a school night. Her bedtime is 7:45, so I'd want to know the runtime first. If the film runs long, we may skip it or have her ride with you and come home right after. What's the runtime, and where is it playing? Happy to drive or carpool.

If you'd rather commit, swap the middle for "We're in, and I'll bring her straight home afterward."

**Logistics**

- **Which Thursday?** Today is Thursday 19 November, so "Thursday" probably means 26 November, which is Thanksgiving. Check that the theater is open and that the family doesn't already have plans.
- **Your calendar:** Thursday afternoons are your no-meeting focus block, so 7 pm doesn't conflict with work. Nothing else on file clashes with that evening.
- **Bedtime:** Linnea's bedtime is 7:45, with reading until 8:15. A 7 pm start probably means she gets home around 9 or later. That's the main thing to decide. Emeka is in her grade, so he faces the same late night.
- **Idris:** Nothi [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

### 29. i10 (condition: index)

Task prompt:

````
Rashid wants me at the architecture workshops in Chicago from 22 to 24 June 2027, all day and in person. Draft a reply saying I'm in.
````

Check question: Does the response point out that she is on call that week (the week she took from Devika), before or instead of simply accepting?
Stored fact: - [stated] Swapped the on-call week of 10 May 2027 with Devika and took her week of 21 June instead (2026-11-02)

Model answer:

````
Here's a draft:

---

**Subject:** Re: Architecture workshops, Chicago, 22–24 June

Hi Rashid,

Thanks for the invite. I'm in for the architecture workshops in Chicago, 22–24 June, all day and in person. I've put the dates on my calendar.

If there's an agenda or pre-reading, send it over when you have it. I'd like to come prepared, especially for any sessions that touch the Kestrel work.

Thanks,
Wren

---

I left out two things:
- **Dates:** 22–24 June 2027 is Tuesday to Thursday. That covers a Thursday afternoon, which is normally your focus block, and a Wednesday, which is normally your school pickup day. School is probably out by then, but check with Idris if the pickup is still needed.
- **Kestrel:** I assumed the Kestrel line fits, since you own that project. I can cut it if you'd rather keep the reply short.
````

Haiku verdict: miss

Your verdict: [ ] agree  [ ] disagree  — note:

### 30. i16 (condition: hook)

Task prompt:

````
Propose three slots next week for a 50-minute session with Tomasz and Devika to walk through the cutover-day checks, and write the invite.
````

Check question: Do all the proposed slots finish by 11:00 am Central, the end of Tomasz's overlap from Warsaw?
Stored fact: - [stated] Tomasz: platform team, owns the deploy pipeline; based in Warsaw, so overlap ends at 11 am Central

Model answer:

````
Next week has two constraints. Thursday 26 Nov is Thanksgiving, and Tomasz's overlap with US Central ends at 11:00. So I kept every slot in the morning, Monday or Wednesday, and clear of the Tuesday 10:00 on-call handoff.

**Proposed slots (US Central, 50 minutes)**
1. **Mon 23 Nov, 10:00–10:50** (17:00–17:50 for Tomasz in Warsaw)
2. **Wed 25 Nov, 9:30–10:20**
3. **Wed 25 Nov, 10:00–10:50**

I can't see anyone's calendar, so check these against Devika's and Tomasz's before sending.

---

**Invite**

**Title:** Cutover-day checks walkthrough

**Attendees:** Tomasz, Devika

**Duration:** 50 minutes

**Time:** Mon 23 Nov 10:00 CT, with Wed 25 Nov 9:30 CT and Wed 25 Nov 10:00 CT as alternates. Please reply with which one works.

**Description:**
Hi Tomasz and Devika,

I'd like to walk through the cutover-day checks together so we agree on them before the day. Tomasz, I want your view on the deploy pipeline. Devika, I want your view on the Kafka side and a review of the list.

**Agenda**
1. (5 min) Scope: what "cutover day" covers and the order of events
2. (15 min) Pre-cutover checks: pipeline readiness, config, and a go/no-go gate
3. (15 min) During and after cutover: Kafka consumer l [...truncated]
````

Haiku verdict: hit

Your verdict: [ ] agree  [ ] disagree  — note:

