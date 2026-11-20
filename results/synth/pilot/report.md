# Multi-store replay: pilot

- 1 generated users, 6 weekly checkpoints each, 392 scored probe answers.
- Data: users, stores and conversations are templated by a generator, so absolute scores flatter every arm; compare arms, not levels. Labels are the generator's truth; answers are scored by a fixed string rule.
- Each week: the plain writer adds that week's conversations to memory, the arm rewrites the stores, and the week's probes are answered from the result. Arm B's writer is not shown conversations whose new input was tool output; they reach memory only through B's checked compile pass.
- Intervals are 95% Wilson intervals; differences are paired on the same (user, week, probe).

## Error rates (lower is better)

| Arm | What it is | stale served | false stale | planted accepted | combined error |
| --- | --- | --- | --- | --- | --- |
| z | do nothing (stores as the writer left them) | 22% (12/55; 13% to 34%) | 0% (0/25; 0% to 13%) | 0% (0/18; 0% to 18%) | 12% (12/98; 7% to 20%) |
| a0 | shipped clean-up (consolidate-memory skill, memory folder only) | 22% (12/55; 13% to 34%) | 8% (2/25; 2% to 25%) | 0% (0/18; 0% to 18%) | 14% (14/98; 9% to 23%) |
| a | our whole-store clean-up pass, all stores and the week's evidence | 22% (12/55; 13% to 34%) | 0% (0/25; 0% to 13%) | 0% (0/18; 0% to 18%) | 12% (12/98; 7% to 20%) |
| b | compile pass with code-enforced checks, lineage and questions | 0% (0/55; 0% to 7%) | 0% (0/25; 0% to 13%) | 0% (0/18; 0% to 18%) | 0% (0/98; 0% to 4%) |

## Paired differences

| Comparison | Metric | Probes | Difference | 95% interval |
| --- | --- | --- | --- | --- |
| b minus a | false stale | 25 | +0 points | +0 to +0 |
| b minus a | planted accepted | 18 | +0 points | +0 to +0 |
| b minus a | combined error | 98 | -12 points | -18 to -6 |
| a minus a0 | false stale | 25 | -8 points | -20 to +0 |
| a minus a0 | planted accepted | 18 | +0 points | +0 to +0 |
| a minus a0 | combined error | 98 | -2 points | -5 to +0 |
| a0 minus z | false stale | 25 | +8 points | +0 to +20 |
| a0 minus z | planted accepted | 18 | +0 points | +0 to +0 |
| a0 minus z | combined error | 98 | +2 points | +0 to +5 |
| a minus z | false stale | 25 | +0 points | +0 to +0 |
| a minus z | planted accepted | 18 | +0 points | +0 to +0 |
| a minus z | combined error | 98 | +0 points | +0 to +0 |
| b minus z | false stale | 25 | +0 points | +0 to +0 |
| b minus z | planted accepted | 18 | +0 points | +0 to +0 |
| b minus z | combined error | 98 | -12 points | -18 to -6 |

## Passes

| Arm | Weeks | Outcomes | Writer batches not ok | Input tokens | Output tokens | Dollars |
| --- | --- | --- | --- | --- | --- | --- |
| z | 6 | ok 6 | 0 | 112,126 | 13,583 | $0.01 |
| a0 | 6 | ok 6 | 0 | 171,155 | 19,483 | $0.12 |
| a | 6 | ok 6 | 0 | 245,538 | 22,805 | $0.22 |
| b | 6 | ok 6 | 0 | 134,274 | 14,304 | $0.09 |

Questions asked per week by arm B: 1.17 (7 over 6 user-weeks; budget 3).

Arm B change decisions:

| Decision | Reason | Count |
| --- | --- | --- |
| apply | supported change | 8 |
| apply | confirmed by the person | 4 |
| ask | tool output cannot override an existing line | 3 |

## Not run, and limits

- Users, stores and conversations are templated by a generator, so every arm's absolute scores are flattered; only differences between arms mean anything.
- Labels are the generator's own truth; the scorer is a fixed string rule (spot-checked below if a check was recorded).
- The echo check, category policy, pinned facts, probes, promotion by demand and an erase test (later work).
- A judge or labeller from a different model family; real multi-store histories; more than one seed.
