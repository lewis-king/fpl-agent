# Final synthesis selector: historical replay

Generated: 2026-08-15T07:36:38.291709+00:00

## Verdict

**RETAIN_INCUMBENT**. Production remains horizon-family weight **0.50** and worst-family surcharge **0.20**.

This replays the same selector shape used by the live synthesis. Candidate policies are compared in a short realised family (GW1–5) and a long realised family (GW1–8). Weights are selected by leave-one-season-out regret on 2023/24 and 2024/25, then frozen against untouched 2025/26. It calibrates the selector, not the identity of any 2026/27 player.

Grid choice: horizon 0.50, worst 0.20; untouched delta versus incumbent-selected historical policy: +0 points.

## Promotion gate

- FAIL — candidate differs from incumbent
- FAIL — strict selection score improvement
- PASS — non negative each selection fold
- FAIL — positive untouched test delta

A different weight pair receives production authority only if it improves the selection score, is no worse in either selection fold, and wins on the untouched season. Otherwise 0.50 / 0.20 is retained.

## Grid

| Horizon weight | Worst surcharge | Mean LOO regret | Worst LOO regret | Score |
|---:|---:|---:|---:|---:|
| 0.50 | 0.20 | 17.00 | 22.00 | 18.00 |
| 0.50 | 0.00 | 17.00 | 22.00 | 18.00 |
| 0.50 | 0.40 | 17.00 | 22.00 | 18.00 |
| 0.25 | 0.20 | 17.00 | 22.00 | 18.00 |
| 0.75 | 0.20 | 17.00 | 22.00 | 18.00 |
| 0.25 | 0.00 | 17.00 | 22.00 | 18.00 |
| 0.25 | 0.40 | 17.00 | 22.00 | 18.00 |
| 0.75 | 0.00 | 17.00 | 22.00 | 18.00 |
| 0.75 | 0.40 | 17.00 | 22.00 | 18.00 |

## Limits

Only three recent opening windows are available and two are used for selection. That is enough to reject unsupported tuning, not enough to estimate a universal constant. Historical player identities are never copied into the current squad.
