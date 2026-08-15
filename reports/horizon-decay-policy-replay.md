# Horizon and decay: rolling preseason policy replay

Generated: 2026-08-15T07:36:32.710176+00:00

## Verdict

**RETAIN_INCUMBENT** — selection chose `h5-d088` (horizon 5, decay 0.88). The incumbent is `h8-d088`. On the untouched 2025-26 GW1–8 path the challenger changed realised ordinary-transfer points by +0.

This is the first outcome-based calibration of the planning horizon. It starts from a legal GW1 squad, reruns the decision at every deadline, carries squad value and the historically legal free-transfer bank, allows no hits or chips, and scores realised points with autosubs and captain fallback.

GW1–8 is the evaluation window, not one frozen eight-week plan. At every gameweek the policy discards its old projection, ingests that deadline's out-of-fold forecast and latest known fixture schedule, then optimises again from the squad and free transfers it actually carried forward.

## Selection grid

| Rank | Configuration | 2023/24 | 2024/25 | Total | Robust regret | 2025/26 test |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `h5-d088` | 451 | 530 | 981 | 7.20 | 367 |
| 2 | `h5-d094` | 451 | 523 | 974 | 10.00 | 367 |
| 3 | `h8-d088` | 451 | 519 | 970 | 11.60 | 367 |
| 4 | `h8-d080` | 451 | 519 | 970 | 11.60 | 367 |
| 5 | `h8-d100` | 463 | 508 | 971 | 13.20 | 367 |
| 6 | `h3-d080` | 451 | 508 | 959 | 18.00 | 370 |
| 7 | `h8-d094` | 451 | 508 | 959 | 18.00 | 367 |
| 8 | `h3-d070` | 451 | 501 | 952 | 22.20 | 370 |
| 9 | `h3-d088` | 447 | 495 | 942 | 27.40 | 370 |
| 10 | `h5-d080` | 451 | 491 | 942 | 28.20 | 367 |
| 11 | `h5-d100` | 420 | 511 | 931 | 33.40 | 367 |
| 12 | `h5-d070` | 451 | 480 | 931 | 34.80 | 367 |
| 13 | `h8-d070` | 451 | 480 | 931 | 34.80 | 367 |
| 14 | `h3-d100` | 424 | 493 | 917 | 38.20 | 358 |
| 15 | `h3-d094` | 410 | 495 | 905 | 45.80 | 358 |
| 16 | `h1-d100` | 410 | 489 | 899 | 48.20 | 373 |

## Challenger versus incumbent

| Season | Initial squad overlap | Same transfer actions | Challenger only | Incumbent only |
|---|---:|---:|---|---|
| 2023-24 | 15/15 | 8/8 gameweeks | — | — |
| 2024-25 | 14/15 | 8/8 gameweeks | Dean Henderson | Mark Flekken |
| 2025-26 | 15/15 | 8/8 gameweeks | — | — |

The challenger must win because its planning policy generalises, not because one opening player happened to outscore another in one selection season. Squad overlap and action agreement expose that fragility alongside the points table.

## What is and is not learned

- Horizon and decay are selected only from realised 2023/24 and 2024/25 GW1–8 ordinary-transfer paths. The 2025/26 path is untouched until the promotion gate.
- Every current-event xP is an out-of-fold, deadline-safe forecast. Future player form, prices, availability and results are never copied backwards.
- Future fixtures come from the latest archived fixture snapshot available at that deadline. Missing deadline snapshots are carried forward from an earlier snapshot, never filled from a later one.
- Because the existing out-of-fold forecast is one-event ahead, future xP freezes the current player rate and applies only a fixture/venue response recovered from the incumbent model's predictions. That response fit never sees actual points.
- This is a three-season opening-window sample. It is materially stronger than choosing 0.88 by judgment, but still too small to imply a universal football constant.
- Wildcards, hits, future price forecasts and adaptive injury scenario trees are excluded. Their absence is why a configuration must pass the untouched season before receiving production authority.

## Promotion rule

- PASS — candidate differs from incumbent
- FAIL — positive each selection season
- FAIL — selection has local parameter support
- FAIL — positive frozen test total
- PASS — frozen test block lower bound above minus point one

The production horizon may change only when every gate passes. Otherwise the result remains calibration evidence and the current 8/0.88 sensitivity portfolio stays in force.
