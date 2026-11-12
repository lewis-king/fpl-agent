# Gameweek 9 prospective decision scorecard

Decision: **A-6fdc94d1d9-1**. Realized rank: **4 of 13**.

| Rank | Action | Route | Gross | Incremental cost | Decision net | Δ roll |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | A-6adab93180-1 | one_free_transfer | 68.0 | 0 | 68.0 | +8.0 |
| 2 | A-0018c0c802-1 | one_free_transfer | 67.0 | 0 | 67.0 | +7.0 |
| 3 | A-2de655f7b6-2 | paid_transfer | 71.0 | 4 | 67.0 | +7.0 |
| 4 | A-6fdc94d1d9-1 | one_free_transfer | 67.0 | 0 | 67.0 | +7.0 |
| 5 | A-1e6930d61a-2 | paid_transfer | 67.0 | 4 | 63.0 | +3.0 |
| 6 | A-8a44847855-2 | paid_transfer | 67.0 | 4 | 63.0 | +3.0 |
| 7 | A-e5126ddfc2-3 | paid_transfer | 71.0 | 8 | 63.0 | +3.0 |
| 8 | A-4444769e18-3 | paid_transfer | 69.0 | 8 | 61.0 | +1.0 |
| 9 | A-ba2087c85b-0 | roll | 60.0 | 0 | 60.0 | +0.0 |
| 10 | A-d1a09bd3f2-2 | paid_transfer | 64.0 | 4 | 60.0 | +0.0 |
| 11 | A-6b44e10e4a-1 | one_free_transfer | 57.0 | 0 | 57.0 | -3.0 |
| 12 | A-ed61e515a3-3 | paid_transfer | 64.0 | 8 | 56.0 | -4.0 |
| 13 | A-4e05ee6035-3 | paid_transfer | 61.0 | 8 | 53.0 | -7.0 |

## Selected action

- Realized net difference to roll: +7.0
- Realized opportunity cost to the best considered action: 1.0
- Projected event net points: 54.46
- Realized event net points: 67.0

## Attribution diagnostics

- Best-considered action regret: 1.0 points
- Hindsight XI/captain upper-bound regret: 20.0 points
- Captain regret within the frozen XI: 0.0 points
- Player expected-points MAE: 2.869; appearance Brier: 0.007

This is prospective process evidence, not permission to fit the next model to one noisy Gameweek. Aggregate frozen receipts before changing a forecast or policy.

## Frozen chip counterfactuals

| Chip | Parent route | Chip-only gain | Event net gain vs selected route |
| --- | --- | ---: | ---: |
| wildcard | squad rebuild | n/a | -5.0 |
| free_hit | squad rebuild | n/a | -5.0 |
| triple_captain | A-6adab93180-1 | +9.0 | +10.0 |
| bench_boost | A-6adab93180-1 | +20.0 | +26.0 |

Actual immediate uplift compares each frozen chip-and-transfer route's event net points with the selected ordinary route. Chip-only uplift compares BB/TC with its own no-chip parent, including autosub displacement. Projected policy uplift may span the full decision horizon and is not a like-for-like event forecast. Wildcard persistence and chip retention cannot be judged from one event.
