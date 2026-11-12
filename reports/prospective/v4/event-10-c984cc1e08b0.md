# Gameweek 10 prospective decision scorecard

Decision: **A-6fdc94d1d9-0**. Realized rank: **2 of 13**.

| Rank | Action | Route | Gross | Incremental cost | Decision net | Δ roll |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | A-736d678c18-1 | one_free_transfer | 70.0 | 0 | 70.0 | +2.0 |
| 2 | A-6fdc94d1d9-0 | roll | 68.0 | 0 | 68.0 | +0.0 |
| 3 | A-38b6c9f5b3-1 | one_free_transfer | 63.0 | 0 | 63.0 | -5.0 |
| 4 | A-ff7367ae1c-1 | one_free_transfer | 63.0 | 0 | 63.0 | -5.0 |
| 5 | A-af1ed8c728-1 | one_free_transfer | 61.0 | 0 | 61.0 | -7.0 |
| 6 | A-2e528092fb-2 | paid_transfer | 64.0 | 4 | 60.0 | -8.0 |
| 7 | A-4325a0604c-2 | paid_transfer | 64.0 | 4 | 60.0 | -8.0 |
| 8 | A-0894e82960-2 | paid_transfer | 56.0 | 4 | 52.0 | -16.0 |
| 9 | A-7ce14bbc8d-3 | paid_transfer | 57.0 | 8 | 49.0 | -19.0 |
| 10 | A-fae9af67b5-2 | paid_transfer | 53.0 | 4 | 49.0 | -19.0 |
| 11 | A-09288b641c-3 | paid_transfer | 55.0 | 8 | 47.0 | -21.0 |
| 12 | A-d083f71e6d-3 | paid_transfer | 55.0 | 8 | 47.0 | -21.0 |
| 13 | A-772da501cc-3 | paid_transfer | 54.0 | 8 | 46.0 | -22.0 |

## Selected action

- Realized net difference to roll: +0.0
- Realized opportunity cost to the best considered action: 2.0
- Projected event net points: 54.83
- Realized event net points: 68.0

## Attribution diagnostics

- Best-considered action regret: 2.0 points
- Hindsight XI/captain upper-bound regret: 10.0 points
- Captain regret within the frozen XI: 3.0 points
- Player expected-points MAE: 2.678; appearance Brier: 0.002

This is prospective process evidence, not permission to fit the next model to one noisy Gameweek. Aggregate frozen receipts before changing a forecast or policy.

## Frozen chip counterfactuals

| Chip | Parent route | Chip-only gain | Event net gain vs selected route |
| --- | --- | ---: | ---: |
| wildcard | squad rebuild | n/a | -6.0 |
| free_hit | squad rebuild | n/a | -2.0 |
| triple_captain | A-38b6c9f5b3-1 | +8.0 | +3.0 |
| bench_boost | A-38b6c9f5b3-1 | +17.0 | +12.0 |

Actual immediate uplift compares each frozen chip-and-transfer route's event net points with the selected ordinary route. Chip-only uplift compares BB/TC with its own no-chip parent, including autosub displacement. Projected policy uplift may span the full decision horizon and is not a like-for-like event forecast. Wildcard persistence and chip retention cannot be judged from one event.
