# read_chat: 4 runs with vs 4 runs without (LongMemEval-S, profile+search)

## Rule (fixed 2026-11-20, before any of the reruns below were run)

Arms: `profile+search` WITH read_chat (current tools) and WITHOUT read_chat (the old tool set, restored in the
bench only: read_chat not offered, the old `conversation_search` description, no `read_chat offset N` header
bit). Existing single runs count as run 1 of each arm (WITHOUT = `results/search-gate/2026-11-lme/`, WITH =
`results/search-gate/2026-11-lme-readchat/`); 3 more runs each, same 100 questions (seed 20261110), same copied
stores and profiles, Haiku answers and judge, frozen params. No tool wording or instructions are changed.

Ship read_chat only if BOTH:
- (a) mean correct WITH >= mean correct WITHOUT;
- (b) mean abstentions correct WITH >= 19.0 of 20.

Otherwise do not merge. Stop if total spend would pass $60 or five-hour usage reaches 70%.

## Results

`profile+search`, n = 100 per run, Haiku 5.5 answers and judge (not LongMemEval's GPT-4o judge), no verdicts
checked by hand. Run 1 of each arm is the earlier single run; runs 2 to 4 are in `reruns/`, run one at a time.

| Run | WITHOUT correct | WITHOUT abstention | WITH correct | WITH abstention | WITH read_chat calls (questions) |
| --- | --- | --- | --- | --- | --- |
| 1 | 74 | 19 | 79 | 18 | 12 (7) |
| 2 | 77 | 20 | 80 | 18 | 18 (11) |
| 3 | 77 | 20 | 78 | 19 | 14 (10) |
| 4 | 75 | 19 | 79 | 19 | 19 (12) |
| Mean | 75.75 | 19.5 | 79.0 | 18.5 | 15.75 (10) |

- Per-question mean difference, WITH minus WITHOUT: +3.25 points (95% bootstrap over questions -1.0 to +7.75).
  13 questions are right more often WITH, 8 more often WITHOUT.
- Run-to-run noise between identical runs: WITHOUT 11 to 14 questions flip between any two runs (mean agreement
  87.5%; 23 of 100 questions not stable across the 4 runs); WITH 8 to 11 flip (mean agreement 91%; 16 unstable).
- Mean input tokens: WITHOUT about 7,300; WITH about 8,200 to 8,700. Mean tool calls about 1.8 in both.
- Abstentions lost WITH: `09ba9854_abs` in all 4 runs, each time after calling read_chat (once WITHOUT, in run 1);
  `gpt4_70e84552_abs` in runs 1 and 2. Reading the full exchange leads the model to answer from a near-miss
  instead of saying it does not know.
- Spend for the six reruns: $0.36 (the ledger stands at $45.95; that includes about $0.41 for a first attempt at
  these reruns, discarded because two runs ran at once and raced on the shared profile folder).

## Verdict

- (a) mean correct WITH 79.0 >= WITHOUT 75.75: pass.
- (b) mean abstentions WITH 18.5 >= 19.0: **fail**.

## Diagnosis of the abstention losses (2026-11-20)

The bench does not log tool outputs, so this is read from the answers and the question's own history.

- `09ba9854_abs` ("How much will I save by taking the bus from the airport to my hotel instead of a taxi?"; gold:
  not answerable, the person never said what the bus costs). The person said a taxi was quoted at about $60. The
  bus fares in the history (¥2,000-3,000, $10-20, ¥3,200 to Shinjuku) all come from the *assistant's* general
  travel advice in two sessions. Search snippets centred on the query terms usually show the person's $60 line;
  read_chat shows the whole exchange, including the assistant's fare tables, and the model then computes a saving
  from the assistant's own generic estimate as if the person had told it a bus fare. Lost in 4 of 4 WITH runs
  (each called read_chat); the WITHOUT answers that pass all say "I don't have a bus fare in your past
  conversations". Cause: full text makes assistant-supplied general information look like a fact about the person.
- `gpt4_70e84552_abs` ("fence or three cows from Peter first?"; gold: cows never mentioned). Failing answers lead
  with "You completed the fence first" and then say there is no record of the cows. The same shape was judged
  correct in WITHOUT run 1, and WITH run 2 failed without calling read_chat at all. Cause: mostly judge
  inconsistency on an answer that leads with the half it can answer; not specific to read_chat.
- No code bug found: read_chat returned real history, correctly attributed by speaker label.

read_chat is not shipped; the branch `read-chat-tool` is kept unmerged.

## Round 2: wording tuned on dev, confirmed once on test

### Dev tuning (never the 100 test questions)

Dev set (`--split dev`, `dev_gate_items`): all 10 abstention questions outside the test sample plus 10
non-abstention questions drawn with seed 20261120 from the test sample's other types (knowledge-update,
temporal-reasoning, multi-session). Profiles compiled for these on the subscription. `profile+search`, 3 runs per
arm, one at a time, Haiku answers and judge. Results in `dev/`.

| Arm | Abstention correct per run (of 10) | Mean | Non-abstention per run (of 10) | Mean | read_chat calls per run |
| --- | --- | --- | --- | --- | --- |
| legacy tools | 10, 10, 8 | 9.33 | 7, 7, 8 | 7.33 | 0 |
| v0 (round-1 wording) | 9, 10, 10 | 9.67 | 7, 6, 7 | 6.67 | 3, 2, 1 |
| v1 (new wording) | 10, 9, 10 | 9.67 | 7, 7, 6 | 6.67 | 2, 3, 2 |

The dev set does not reproduce the test-set loss (v0 already matches legacy on abstention there), and the model
calls read_chat on only 1 to 3 of 20 questions, so dev mostly shows the new wording does no harm. v1 meets the dev
bar on abstention; non-abstention is 2 question-runs of 30 below legacy, the same as v0, which is within noise at
10 questions. One iteration used of the allowed three: further iterations on a set this small would tune to noise.

### Frozen wording (v1), changed text only

`read_chat` description, inserted after "...amounts or other exact details.":

> Only what the person said is a fact about them: prices, estimates and advice the assistant gave are general
> information, not something the person told you. If the conversation does not state the thing asked, say you
> have no record of it; do not answer from a related or similar event.

Server `INSTRUCTIONS`, inserted after "...call `read_chat` with the result's session id and offset.":

> Only what the person said is a fact about them; what the assistant suggested or estimated is not. If a past
> conversation does not state the thing asked, say you have no record of it rather than answering from a related
> or similar event.

(The bench passes tool descriptions only, not the server instructions.)

### Confirmatory rule (fixed before the test run, same as round 1)

4 WITH runs on the 100 test questions with the frozen v1 wording, one at a time (`round2/with-1..4`). WITHOUT arm:
the existing 4 runs (run 1 in `2026-11-lme/`, runs 2 to 4 in `reruns/without-*`); the legacy path's tool text is
byte-identical (it uses the old description, drops read_chat and strips the offset bit; none of it reads the
changed wording). Ship read_chat if BOTH (a) mean correct WITH >= mean correct WITHOUT (75.75) and (b) mean
abstentions WITH >= 19.0 of 20. Otherwise do not merge.

### Confirmatory result

`profile+search`, 100 test questions, Haiku answers and judge, no verdicts checked by hand. WITH = v1 wording,
`round2/with-1..4`; WITHOUT = the same 4 legacy runs as round 1.

| Run | WITHOUT correct | WITHOUT abstention | WITH (v1) correct | WITH (v1) abstention | read_chat calls (questions) |
| --- | --- | --- | --- | --- | --- |
| 1 | 74 | 19 | 76 | 19 | 12 (9) |
| 2 | 77 | 20 | 76 | 19 | 14 (10) |
| 3 | 77 | 20 | 77 | 18 | 12 (8) |
| 4 | 75 | 19 | 73 | 19 | 19 (13) |
| Mean | 75.75 | 19.5 | 75.5 | 18.75 | 14.25 (10) |

- Per-question mean difference WITH minus WITHOUT: -0.25 points (95% bootstrap -4.5 to +4.0); 13 questions right
  more often WITH, 14 more often WITHOUT. Run-to-run: WITH 7 to 13 questions flip between identical runs (mean
  agreement 90%).
- Mean input tokens WITH about 8,000 to 9,000 against about 7,300.
- Abstentions lost WITH: `09ba9854_abs` in all 4 runs again, each after a read_chat call, each answer computing a
  saving from the assistant's bus-fare estimate despite the new wording; `eeda8a6d_abs` once (no read_chat call).
  The wording did not change the diagnosed behaviour.
- Round 1's +3.25 for v0 did not repeat with v1 (-0.25); with both intervals spanning zero, read_chat shows no
  measurable accuracy gain on this benchmark at n = 100.

### Verdict

- (a) mean correct WITH 75.5 >= 75.75: **fail**.
- (b) mean abstentions WITH 18.75 >= 19.0: **fail**.

Not merged. The branch keeps read_chat with the v1 wording and the bench options (`--legacy-tools`,
`--split dev`). Spend for round 2 (dev runs and the confirmatory runs): about $0.41; ledger $46.36. The abstention loss is concentrated in
one question that fails every time read_chat is used on it, so it looks like a real effect, not noise; fixing it
would mean changing tool wording, which this rule forbids doing against the test set.
