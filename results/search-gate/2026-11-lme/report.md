# Conversation-search gate: LongMemEval-S

| Condition | n | Correct | 95% Wilson | Judge failed | Mean input tokens | Tool calls (mean) | Reused |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `profile` | 100 | 42 (42%) | 33 to 52 | 0 | 1,018 | 0.00 | 0 |
| `search` | 100 | 74 (74%) | 65 to 82 | 0 | 12,042 | 3.18 | 0 |
| `profile+search` | 100 | 74 (74%) | 65 to 82 | 0 | 7,311 | 1.78 | 0 |
| `full` | 100 | 91 (91%) | 84 to 95 | 0 | 167,168 | 0.00 | 20 |
| `search-1shot` | 100 | 48 (48%) | 38 to 58 | 0 | 1,270 | 1.00 | 0 |

## Paired differences (points, 95% bootstrap interval)

- `profile+search` minus `profile`: +32.0 (+22.0 to +42.0), n = 100
- `profile+search` minus `full`: -17.0 (-27.0 to -8.0), n = 100
- `search` minus `profile+search`: +0.0 (-9.0 to +9.0), n = 100
- `search-1shot` minus `search`: -26.0 (-36.0 to -16.0), n = 100

## Verdicts

- G1 PASS: point +32.0, interval +22.0 to +42.0, n = 100 (pass: lower bound above 0)
- G2 PASS: abstention `profile+search` 19 of 20 against `profile` 20 (pass: no more than 1 fewer)

## Answer-session recall (no model)

- recall@5 0.980, recall@10 0.980, over 100 questions with answer sessions

## Embeddings-gate inputs

- `full` right and `profile+search` wrong: 21; of those, no answer session retrieved: 2

## Judge check by hand

20 verdicts sampled at random (seed 20261120) from the `search` and `profile+search` rows, read against the gold
answers by Claude (Opus 5.5), not by AJ: agreement 20 of 20. One was lenient: 2133c1b5_abs (`search`) says it
cannot confirm Shinjuku but still estimates a duration; judged a correct abstention.
