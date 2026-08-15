# Attacking chance-quality challenger

Generated: 2026-08-10T15:01:54.464861+00:00

## Verdict

**REJECT** — the multi-season stability rule selected a bounded 0% blend. The untouched 2025/26 continuous path changed by +0 net points; independent legal weekly rebuilds changed by +0.

This challenger adds long-horizon xG/xA, per-90 rates, team attacking share and explicit finishing/assist surplus to the same deadline-safe features as the champion. It reuses the champion appearance probability, so this test isolates attacking quality rather than quietly changing predicted minutes.

## Season-forward forecast evidence

| Season | Pos | Incumbent top-k | Challenger top-k | Lift | MAE lift |
|---|---|---:|---:|---:|---:|
| 2023-24 | MID | 5.082 | 4.647 | -0.435 | -0.0268 |
| 2023-24 | FWD | 4.326 | 4.487 | +0.161 | -0.0214 |
| 2024-25 | MID | 4.921 | 4.804 | -0.118 | -0.0097 |
| 2024-25 | FWD | 4.546 | 4.497 | -0.049 | -0.0688 |
| 2025-26 | MID | 4.368 | 4.268 | -0.100 | +0.0132 |
| 2025-26 | FWD | 4.493 | 4.421 | -0.072 | +0.0202 |

## Continuous legal decision replay

| Weight | 2023/24 | 2024/25 | Worst | Total |
|---:|---:|---:|---:|---:|
| 0% | +0 | +0 | +0 | +0 |
| 10% | -50 | +34 | -50 | -16 |
| 20% | +67 | -41 | -41 | +26 |

- Frozen 2025/26 continuous delta: **+0 points**.
- Frozen four-GW interval: **+0.000 to +0.000/GW**.
- Independent frozen rebuild delta: **+0 points**.
- Independent squad agreement: **100.0%**; captain agreement: **100.0%**.

## Promotion gate

- FAIL — `positive_mean_top_k_lift_2023-24`
- FAIL — `nonnegative_mean_mae_lift_2023-24`
- FAIL — `positive_mean_top_k_lift_2024-25`
- FAIL — `nonnegative_mean_mae_lift_2024-25`
- FAIL — `positive_mean_top_k_lift_2025-26`
- PASS — `nonnegative_mean_mae_lift_2025-26`
- FAIL — `nonzero_bounded_weight`
- FAIL — `positive_2023_24_continuous_path`
- FAIL — `positive_2024_25_continuous_path`
- FAIL — `positive_frozen_2025_26_continuous_path`
- FAIL — `positive_frozen_independent_rebuilds`
- PASS — `pooled_out_of_selection_lower_bound_above_minus_point_one`

## Live data contract

All added inputs are available after every finalized Gameweek from the official event-live archive: player minutes, goals, assists, xG and xA. Team expected goals, opponent context, prices, availability and set-piece order already exist in the deadline feature matrix. No Understat/FBref field is required to serve this model.

A failed gate leaves the champion untouched. A pass permits only the recorded bounded MID/FWD blend, with hashes for the model, feature table and OOF forecast.
