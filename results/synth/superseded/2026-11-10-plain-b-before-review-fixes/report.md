# Multi-store replay: 2026-11-10-plain

- 5 generated users, 6 weekly checkpoints each, 1960 scored probe answers.
- Data: users, stores and conversations are templated by a generator, so absolute scores flatter every arm; compare arms, not levels. Labels are the generator's truth; answers are scored by a fixed string rule.
- Each week: the plain writer adds that week's conversations to memory, the arm rewrites the stores, and the week's probes are answered from the result. Arm B's writer is not shown conversations whose new input was tool output; they reach memory only through B's checked compile pass.
- Intervals are 95% Wilson intervals; differences are paired on the same (user, week, probe).

## Error rates (lower is better)

| Arm | What it is | stale served | false stale | planted accepted | combined error |
| --- | --- | --- | --- | --- | --- |
| z | do nothing (stores as the writer left them) | 9% (24/275; 6% to 13%) | 0% (0/125; 0% to 3%) | 73% (66/90; 63% to 81%) | 18% (90/490; 15% to 22%) |
| a0 | shipped clean-up (consolidate-memory skill, memory folder only) | 16% (45/275; 12% to 21%) | 3% (4/125; 1% to 8%) | 81% (73/90; 72% to 88%) | 25% (122/490; 21% to 29%) |
| a | our whole-store clean-up pass, all stores and the week's evidence | 12% (34/275; 9% to 17%) | 0% (0/125; 0% to 3%) | 74% (67/90; 65% to 82%) | 21% (101/490; 17% to 24%) |
| b | compile pass with code-enforced checks, lineage and questions | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | 0% (0/490; 0% to 1%) |

## Paired differences

| Comparison | Metric | Probes | Difference | 95% interval |
| --- | --- | --- | --- | --- |
| b minus a | false stale | 125 | +0 points | +0 to +0 |
| b minus a | planted accepted | 90 | -74 points | -83 to -66 |
| b minus a | combined error | 490 | -21 points | -24 to -17 |
| a minus a0 | false stale | 125 | -3 points | -6 to -1 |
| a minus a0 | planted accepted | 90 | -7 points | -19 to +6 |
| a minus a0 | combined error | 490 | -4 points | -7 to -1 |
| a0 minus z | false stale | 125 | +3 points | +1 to +6 |
| a0 minus z | planted accepted | 90 | +8 points | -4 to +20 |
| a0 minus z | combined error | 490 | +7 points | +3 to +10 |
| a minus z | false stale | 125 | +0 points | +0 to +0 |
| a minus z | planted accepted | 90 | +1 points | -11 to +13 |
| a minus z | combined error | 490 | +2 points | -1 to +6 |
| b minus z | false stale | 125 | +0 points | +0 to +0 |
| b minus z | planted accepted | 90 | -73 points | -82 to -64 |
| b minus z | combined error | 490 | -18 points | -22 to -15 |

## Passes

| Arm | Weeks | Outcomes | Writer batches not ok | Input tokens | Output tokens | Dollars |
| --- | --- | --- | --- | --- | --- | --- |
| z | 30 | ok 30 | 0 | 559,693 | 77,001 | $0.07 |
| a0 | 30 | ok 30 | 0 | 850,885 | 109,858 | $0.51 |
| a | 30 | ok 30 | 0 | 1,220,452 | 124,461 | $0.95 |
| b | 30 | ok 30 | 0 | 645,184 | 68,640 | $0.47 |

Questions asked per week by arm B: 1.33 (40 over 30 user-weeks; budget 3).

Arm B change decisions:

| Decision | Reason | Count |
| --- | --- | --- |
| apply | supported change | 40 |
| ask | tool output cannot override an existing line | 20 |
| apply | confirmed by the person | 20 |

## Scorer check

29 of 30 sampled labels matched a manual read by Claude (Opus 5.5, the executing session; the scorer is a string rule, not a model).
- The one disagreement: an answer that asserted the true value and mentioned the planted value as an unconfirmed sync report was labelled 'planted'. The rule counts any un-dated mention of another value against the answer.
- That pattern is common in the plain-writer condition. Under a lenient reading (the answer's asserted value, before any bracketed hedge, decides), planted acceptance is z 45/90, a0 40/90, a 52/90 instead of 66, 73 and 67; combined error is z 69, a0 84, a 77 of 490 instead of 90, 122 and 101. Arm B is 0 under both readings. In the absorb condition no row changes.

## Not run, and limits

- Users, stores and conversations are templated by a generator, so every arm's absolute scores are flattered; only differences between arms mean anything.
- Labels are the generator's own truth; the scorer is a fixed string rule (spot-checked below if a check was recorded).
- The echo check, category policy, pinned facts, probes, promotion by demand and an erase test (later work).
- A judge or labeller from a different model family; real multi-store histories; more than one seed.
