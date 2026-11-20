# Stress test of Arm B

Rules R1 to R4 were written in the plan before any run; the verdicts below are computed by `um.synth.stress_report`, not chosen after reading the numbers. Differences are paired on (user, week, probe), with 95% bootstrap intervals.

## Runs

| Run | Seed | Writer | Oracle | Erase week | Arms | Scored probes |
| --- | --- | --- | --- | --- | --- | --- |
| s1-absorb | 20261110 | absorb | always | - | a, b, z | 1470 |
| s1-absorb-nohook | 20261110 | absorb | always | - | b-nohook | 490 |
| s1-absorb-oracle-flaky | 20261110 | absorb | flaky | - | b | 490 |
| s1-absorb-oracle-late | 20261110 | absorb | late | - | b | 490 |
| s1-absorb-oracle-never | 20261110 | absorb | never | - | b | 490 |
| s1-plain | 20261110 | plain | always | - | a, b, z | 1470 |
| s1-plain-erase | 20261110 | plain | always | 3 | a, b, z | 1470 |
| s1-plain-nohook | 20261110 | plain | always | - | b-nohook | 490 |
| s1-plain-oracle-flaky | 20261110 | plain | flaky | - | b | 490 |
| s1-plain-oracle-late | 20261110 | plain | late | - | b | 490 |
| s1-plain-oracle-never | 20261110 | plain | never | - | b | 490 |
| s2-absorb | 20261111 | absorb | always | - | a, b, b-nohook, z | 1960 |
| s2-plain | 20261111 | plain | always | - | a, b, b-nohook, z | 1960 |

## Error rates by run and arm

| Run | Arm | stale served | false stale | planted accepted | erase leaks | combined error |
| --- | --- | --- | --- | --- | --- | --- |
| s1-absorb | a | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s1-absorb | b | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 0% (0/490; 0% to 1%) |
| s1-absorb | z | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s1-absorb-nohook | b-nohook | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s1-absorb-oracle-flaky | b | 9% (25/275; 6% to 13%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 5% (25/490; 3% to 7%) |
| s1-absorb-oracle-late | b | 5% (15/275; 3% to 9%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 3% (15/490; 2% to 5%) |
| s1-absorb-oracle-never | b | 22% (60/275; 17% to 27%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 12% (60/490; 10% to 15%) |
| s1-plain | a | 12% (34/275; 9% to 17%) | 0% (0/125; 0% to 3%) | 74% (67/90; 65% to 82%) | n/a | 21% (101/490; 17% to 24%) |
| s1-plain | b | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 0% (0/490; 0% to 1%) |
| s1-plain | z | 9% (24/275; 6% to 13%) | 0% (0/125; 0% to 3%) | 73% (66/90; 63% to 81%) | n/a | 18% (90/490; 15% to 22%) |
| s1-plain-erase | a | 9% (24/260; 6% to 13%) | 0% (0/110; 0% to 3%) | 81% (73/90; 72% to 88%) | 0% (0/30; 0% to 11%) | 20% (97/490; 17% to 24%) |
| s1-plain-erase | b | 0% (0/260; 0% to 1%) | 0% (0/110; 0% to 3%) | 0% (0/90; 0% to 4%) | 0% (0/30; 0% to 11%) | 0% (0/490; 0% to 1%) |
| s1-plain-erase | z | 12% (31/260; 9% to 16%) | 0% (0/110; 0% to 3%) | 94% (85/90; 88% to 98%) | 0% (0/30; 0% to 11%) | 24% (116/490; 20% to 28%) |
| s1-plain-nohook | b-nohook | 11% (31/275; 8% to 16%) | 0% (0/125; 0% to 3%) | 83% (75/90; 74% to 90%) | n/a | 22% (106/490; 18% to 25%) |
| s1-plain-oracle-flaky | b | 9% (25/275; 6% to 13%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 5% (25/490; 3% to 7%) |
| s1-plain-oracle-late | b | 5% (15/275; 3% to 9%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 3% (15/490; 2% to 5%) |
| s1-plain-oracle-never | b | 21% (59/275; 17% to 27%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 12% (60/490; 10% to 15%) |
| s2-absorb | a | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s2-absorb | b | 0% (0/275; 0% to 1%) | 1% (1/125; 0% to 4%) | 7% (6/90; 3% to 14%) | n/a | 1% (7/490; 1% to 3%) |
| s2-absorb | b-nohook | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s2-absorb | z | 0% (0/275; 0% to 1%) | 0% (0/125; 0% to 3%) | 100% (90/90; 96% to 100%) | n/a | 18% (90/490; 15% to 22%) |
| s2-plain | a | 13% (36/275; 10% to 18%) | 0% (0/125; 0% to 3%) | 84% (76/90; 76% to 91%) | n/a | 23% (112/490; 19% to 27%) |
| s2-plain | b | 4% (12/275; 3% to 7%) | 0% (0/125; 0% to 3%) | 0% (0/90; 0% to 4%) | n/a | 2% (12/490; 1% to 4%) |
| s2-plain | b-nohook | 2% (6/275; 1% to 5%) | 0% (0/125; 0% to 3%) | 73% (66/90; 63% to 81%) | n/a | 15% (72/490; 12% to 18%) |
| s2-plain | z | 7% (19/275; 4% to 11%) | 0% (0/125; 0% to 3%) | 80% (72/90; 71% to 87%) | n/a | 19% (91/490; 15% to 22%) |

## R1: Hook or checks: **the hook is necessary**

Absorb writer, per seed: planted accepted, b-nohook minus z. Keeps its advantage only if the upper bound is below zero on both seeds; otherwise the hook is necessary.

| Comparison | Probes | Difference | 95% interval |
| --- | --- | --- | --- |
| seed 1, absorb writer: b-nohook minus z, planted accepted | 90 | +0 points | +0 to +0 |
| seed 2, absorb writer: b-nohook minus z, planted accepted | 90 | +0 points | +0 to +0 |

## R2: Silent oracle: **beats Z**

Per oracle mode and writer: combined error, b minus z. Beats Z if the upper bound is below zero, ties if the interval contains zero, worse if the lower bound is above zero. The worst cell is the verdict.

| Comparison | Probes | Difference | 95% interval | Verdict |
| --- | --- | --- | --- | --- |
| oracle never, plain writer: b minus z, combined error | 490 | -6 points | -10 to -2 | beats Z |
| oracle never, absorb writer: b minus z, combined error | 490 | -6 points | -11 to -1 | beats Z |
| oracle late, plain writer: b minus z, combined error | 490 | -15 points | -19 to -12 | beats Z |
| oracle late, absorb writer: b minus z, combined error | 490 | -15 points | -19 to -11 | beats Z |
| oracle flaky, plain writer: b minus z, combined error | 490 | -13 points | -17 to -9 | beats Z |
| oracle flaky, absorb writer: b minus z, combined error | 490 | -13 points | -17 to -9 | beats Z |

## R3: Second seed: **repeats**

Seed 20261111, both writers: combined error, b minus z. Repeats only if the upper bound is below zero in both.

| Comparison | Probes | Difference | 95% interval |
| --- | --- | --- | --- |
| seed 2, plain writer: b minus z, combined error | 490 | -16 points | -20 to -12 |
| seed 2, absorb writer: b minus z, combined error | 490 | -17 points | -20 to -14 |

## R4: Erase: **pass**

Leaks (answers stating an erased value, files still holding one) for every arm after the erase. Pass only at zero.

| Run and arm | Erased probes | Answers leaked | Files leaked |
| --- | --- | --- | --- |
| s1-plain-erase: a | 30 erased probes | 0 answers leaked | 0 files leaked |
| s1-plain-erase: b | 30 erased probes | 0 answers leaked | 0 files leaked |
| s1-plain-erase: z | 30 erased probes | 0 answers leaked | 0 files leaked |

## Limits and what was not run

- Users, stores and conversations are templated by a generator; absolute scores flatter every arm. Labels are the generator's truth; answers are scored by a fixed string rule (strict: a hedged answer counts against the arm).
- One model family (Claude) built the generator's templates, the writer, every arm, the oracle wording and the spot-check: all from one model family.
- The oracle modes are simulations: never answers, answers a week late, or answers half the time by a fixed coin.
- Two seeds of five users each; not powered as the project's experiment plan asked.
- The erase test checks this project's own erase code on what arms and answerers can read; earlier week folders are the benchmark's archive and are not scanned.
- R5 (real histories, labelled by the profile owner) is reported separately; real data never enters this report.
- Not run here: the echo check, pinned facts, probes, promotion by demand, other C components, a judge from another model family.
