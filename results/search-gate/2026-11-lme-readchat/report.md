# Conversation-search gate: LongMemEval-S

| Condition | n | Correct | 95% Wilson | Judge failed | Mean input tokens | Tool calls (mean) | Reused |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `search` | 100 | 79 (79%) | 70 to 86 | 0 | 16,052 | 3.59 | 0 |
| `profile+search` | 100 | 79 (79%) | 70 to 86 | 0 | 8,181 | 1.79 | 0 |

## Paired differences (points, 95% bootstrap interval)

- `search` minus `profile+search`: +0.0 (-9.0 to +9.0), n = 100

## Verdicts

- G1 n/a: a condition is missing
- G2 n/a: a condition is missing

## Answer-session recall (no model)

- recall@5 0.980, recall@10 0.980, over 100 questions with answer sessions
