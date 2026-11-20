# LongMemEval-S sample: 2026-11-10

- Sample: 100 questions, fixed seed 20261110, by type: abstention 20, knowledge-update 40, multi-session 10, temporal-reasoning 30.
- Answering model and judge: `claude-haiku-5-5`. Effort is set to medium on both backends. The judge is from the same model family as the systems it grades.
- Labels: LongMemEval's own answer key; grading uses LongMemEval's published per-type prompts.
- Intervals are 95% Wilson intervals. Differences are paired on the same questions with a bootstrap interval.
- Accuracy is over answered questions; refusals, cut-off and empty replies are counted separately below.

## Accuracy

| Arm | What it is | Overall | abstention | knowledge-update | multi-session | temporal-reasoning |
| --- | --- | --- | --- | --- | --- | --- |
| z | do nothing (store as written) | 82% (82/100; 73% to 88%) | 100% (20/20; 84% to 100%) | 85% (34/40; 71% to 93%) | 60% (6/10; 31% to 83%) | 73% (22/30; 56% to 86%) |
| a0 | shipped clean-up (consolidate-memory skill) | 76% (76/100; 67% to 83%) | 100% (20/20; 84% to 100%) | 82% (33/40; 68% to 91%) | 60% (6/10; 31% to 83%) | 57% (17/30; 39% to 73%) |
| a | our whole-store clean-up pass | 82% (82/100; 73% to 88%) | 95% (19/20; 76% to 99%) | 90% (36/40; 77% to 96%) | 60% (6/10; 31% to 83%) | 70% (21/30; 52% to 83%) |
| full | reference: full history in the prompt | 91% (91/100; 84% to 95%) | 95% (19/20; 76% to 99%) | 92% (37/40; 80% to 97%) | 100% (10/10; 72% to 100%) | 83% (25/30; 66% to 93%) |
| files | reference: raw session files with search | 85% (85/100; 77% to 91%) | 95% (19/20; 76% to 99%) | 85% (34/40; 71% to 93%) | 80% (8/10; 49% to 94%) | 80% (24/30; 63% to 90%) |

## Difference from doing nothing (arm z)

| Arm | Questions compared | Accuracy minus z | 95% interval |
| --- | --- | --- | --- |
| a0 | 100 | -6 points | -13 to +1 |
| a | 100 | +0 points | -6 to +5 |
| full | 100 | +9 points | +1 to +17 |
| files | 100 | +3 points | -7 to +13 |

## Replies that were not answers

| Arm | Rows | refusal | max_tokens | empty | max_turns | judge failed | arm pass failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| z | 100 | 0 | 0 | 0 | 0 | 0 | 0 |
| a0 | 100 | 0 | 0 | 0 | 0 | 0 | 2 |
| a | 100 | 0 | 0 | 0 | 0 | 0 | 0 |
| full | 100 | 0 | 0 | 0 | 0 | 0 | 0 |
| files | 100 | 0 | 0 | 0 | 0 | 0 | 0 |

## Tokens, cost and backend

| Arm | Input tokens | Output tokens | API dollars | Rows by backend |
| --- | --- | --- | --- | --- |
| z | 672,286 | 44,526 | $0.06 | api 100 |
| a0 | 7,520,021 | 1,151,830 | $0.96 | api 100 |
| a | 6,524,364 | 1,097,465 | $0.92 | api 100 |
| full | 16,853,537 | 48,830 | $0.00 | subscription 100 |
| files | 1,734,159 | 64,264 | $0.15 | api 100 |

Shared memory writer (once per question, used by z, a0 and a): 83,477,100 input tokens, 3,539,754 output tokens, $5.30; 22 writer batches did not finish cleanly.

## Judge check

18 of 20 sampled verdicts matched a manual read by Claude (the session model, not the judge model; same model family).
- Both disagreements were answers containing the right value that the judge marked wrong (one stated '6 women out of 10' for a gold answer of 6; one gave the right count with a caveat). Both were on arm z.
- So the judge leans strict by roughly one in ten on this sample; no case was found where it accepted a wrong answer. Twenty rows is too few to correct the table.

## Notes on this run

- Two invocations wrote into this folder: z, a0, a and files on the API (2026-11-10 17:19 to 18:26 CST, $7.40), and full through the subscription route (non-interactive Claude Code, Haiku 5.5, no tools; $0 API).
- A0 appends a two-sentence harness note to the shipped skill text, saying where the memory folder is and today's date.
- Sessions were fed to the writer in batches of about 20,000 tokens; 22 of roughly 700 writer batches ended without a clean finish and their stores were used as left.
- The full-context rows here were produced through the subscription route before effort was pinned there, so the effort they ran at is not known. As a check, the first 20 of those questions were rerun on the API at medium effort (results/longmemeval/2026-11-10-full-api-check, $1.69): 17 correct on each backend, and the two agreed on all 20.
- Rows in this folder predate the judge_backend field. Judge calls for z, a0, a and files went to the API (the usage gate was closed); judge calls for full went through the subscription.
- Arm A's prompt says that questions may ask what was true before. That is a hint A0 does not get; it stays as run for these results and is to be reworded before the arms are rerun.
- No judge verdict in this folder was anything other than yes or no.

## Not run

- Arm B and every Arm C component (later work).
- The custom multi-store benchmark with planted claims (later work).
- STALE, Bemula, Memora, MemoryAgentBench and store-level checks.
- A second labeller or a judge from a different model family.
- Sonnet 5.5 or any model other than the one named above.
