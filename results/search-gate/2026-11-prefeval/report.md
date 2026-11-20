# Conversation-search gate: PrefEval

| Condition | n | Correct | 95% Wilson | Judge failed | Mean input tokens | Tool calls (mean) | Reused |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `profile-full` | 100 | 94 (94%) | 88 to 97 | 0 | 121 | 0.00 | 0 |
| `profile-full+search` | 100 | 93 (93%) | 86 to 97 | 0 | 1,513 | 0.00 | 0 |

## Paired differences (points, 95% bootstrap interval)

- `profile-full+search` minus `profile-full`: -1.0 (-6.0 to +4.0), n = 100

## Verdicts

- G3 PASS: point -1.0, interval -6.0 to +4.0, n = 100 (pass: point at least -2.0 and the interval includes 0)
