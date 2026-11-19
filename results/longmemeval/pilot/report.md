# LongMemEval-S sample: pilot

- Sample: 5 questions, fixed seed 20261110, by type: abstention 1, knowledge-update 2, temporal-reasoning 2.
- Answering model and judge: `claude-haiku-5-5` at effort medium. The judge is from the same model family as the systems it grades.
- Labels: LongMemEval's own answer key; grading uses LongMemEval's published per-type prompts.
- Intervals are 95% Wilson intervals. Differences are paired on the same questions with a bootstrap interval.
- Accuracy is over answered questions; refusals, cut-off and empty replies are counted separately below.

## Accuracy

| Arm | What it is | Overall | abstention | knowledge-update | temporal-reasoning |
| --- | --- | --- | --- | --- | --- |
| z | do nothing (store as written) | 100% (5/5; 57% to 100%) | 100% (1/1; 21% to 100%) | 100% (2/2; 34% to 100%) | 100% (2/2; 34% to 100%) |
| a0 | shipped clean-up (consolidate-memory skill) | 80% (4/5; 38% to 96%) | 100% (1/1; 21% to 100%) | 100% (2/2; 34% to 100%) | 50% (1/2; 9% to 91%) |
| a | our whole-store clean-up pass | 100% (5/5; 57% to 100%) | 100% (1/1; 21% to 100%) | 100% (2/2; 34% to 100%) | 100% (2/2; 34% to 100%) |
| full | reference: full history in the prompt | 100% (4/4; 51% to 100%) | 100% (1/1; 21% to 100%) | 100% (1/1; 21% to 100%) | 100% (2/2; 34% to 100%) |
| files | reference: raw session files with search | 75% (3/4; 30% to 95%) | 100% (1/1; 21% to 100%) | 100% (1/1; 21% to 100%) | 50% (1/2; 9% to 91%) |

## Difference from doing nothing (arm z)

| Arm | Questions compared | Accuracy minus z | 95% interval |
| --- | --- | --- | --- |
| a0 | 5 | -20 points | -60 to +0 |
| a | 5 | +0 points | +0 to +0 |
| full | 4 | +0 points | +0 to +0 |
| files | 4 | -25 points | -75 to +0 |

## Replies that were not answers

| Arm | Rows | refusal | max_tokens | empty | max_turns | arm pass failed |
| --- | --- | --- | --- | --- | --- | --- |
| z | 5 | 0 | 0 | 0 | 0 | 0 |
| a0 | 5 | 0 | 0 | 0 | 0 | 1 |
| a | 5 | 0 | 0 | 0 | 0 | 0 |
| full | 4 | 0 | 0 | 0 | 0 | 0 |
| files | 4 | 0 | 0 | 0 | 0 | 0 |

## Tokens, cost and backend

| Arm | Input tokens | Output tokens | API dollars | Rows by backend |
| --- | --- | --- | --- | --- |
| z | 37,183 | 2,326 | $0.00 | api 5 |
| a0 | 306,847 | 58,700 | $0.06 | api 5 |
| a | 290,308 | 55,079 | $0.06 | api 5 |
| full | 671,544 | 1,314 | $0.34 | api 4 |
| files | 56,338 | 2,238 | $0.01 | api 4 |

Shared memory writer (once per question, used by z, a0 and a): 4,320,965 input tokens, 188,020 output tokens, $0.53; 1 writer batches did not finish cleanly.

Plan usage reading before: {'fh': 49.0, 'sd': 16.0, 'age_s': 7207.011509895325}; after: {'fh': 49.0, 'sd': 16.0, 'age_s': 7492.94030714035}.

API spend for the most recent invocation: $0.99; ledger total $0.99 against a $1.00 cap.

Errors logged during the run: 1 (see errors.jsonl).

## Not run

- Arm B and every Arm C component (Plan 2 onwards).
- The custom multi-store benchmark with planted claims (Plan 2).
- STALE, Bemula, Memora, MemoryAgentBench and store-level checks.
- A second labeller or a judge from a different model family.
- Sonnet 5.5 or any model other than the one named above.
