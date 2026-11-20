# LongMemEval-S sample: 2026-11-10-full-api-check

- Sample: 20 questions, fixed seed 20261110, by type: abstention 4, knowledge-update 10, multi-session 2, temporal-reasoning 4.
- Answering model and judge: `claude-haiku-5-5`. Effort is set to medium on both backends. The judge is from the same model family as the systems it grades.
- Labels: LongMemEval's own answer key; grading uses LongMemEval's published per-type prompts.
- Intervals are 95% Wilson intervals. Differences are paired on the same questions with a bootstrap interval.
- Accuracy is over answered questions; refusals, cut-off and empty replies are counted separately below.

## Accuracy

| Arm | What it is | Overall | abstention | knowledge-update | multi-session | temporal-reasoning |
| --- | --- | --- | --- | --- | --- | --- |
| full | reference: full history in the prompt | 85% (17/20; 64% to 95%) | 75% (3/4; 30% to 95%) | 90% (9/10; 60% to 98%) | 100% (2/2; 34% to 100%) | 75% (3/4; 30% to 95%) |

## Difference from doing nothing (arm z)

Arm z was not run, so there is nothing to compare against.

## Replies that were not answers

| Arm | Rows | refusal | max_tokens | empty | max_turns | judge failed | arm pass failed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full | 20 | 0 | 0 | 0 | 0 | 0 | 0 |

## Tokens, cost and backend

| Arm | Input tokens | Output tokens | API dollars | Rows by backend |
| --- | --- | --- | --- | --- |
| full | 3,347,945 | 8,501 | $1.69 | api 20 |

Judge calls by backend: api 20.

Invocation 1: arms full; API cost $1.69.

## Not run

- Arm B and every Arm C component (later work).
- The custom multi-store benchmark with planted claims (later work).
- STALE, Bemula, Memora, MemoryAgentBench and store-level checks.
- A second labeller or a judge from a different model family.
- Sonnet 5.5 or any model other than the one named above.
