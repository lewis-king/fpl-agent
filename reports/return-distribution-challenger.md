# Distribution-aware player-return challenger

Generated: 2026-08-07T20:49:55.371461+00:00

## Verdict

**HOLD_SHADOW** — validation selected a 25% return-distribution blend. The untouched 2025/26 continuous transfer path changed by +94 net points (+2.474/GW), with a four-GW moving-block 95% interval of -0.211 to +5.132/GW.

The candidate predicts three directly decision-relevant outcome bands—under five points, a 5–9 point return and a 10+ haul—then reconstructs expectation using class means learned only from seasons before the test deadline. It is an independent signal blended with the existing appearance × conditional-points xP model.

## Why this target

The incumbent ranks the broad player pool well, but discrimination compresses after the optimiser has already selected 15 good options. That leaves material XI and captain headroom even when squad selection is sound.

| Season | Captain actual | Best starter actual | Captain headroom | Starter mean | Bench mean |
|---|---:|---:|---:|---:|---:|
| 2023-24 | 6.37 | 12.68 | 6.32 | 4.72 | 3.26 |
| 2024-25 | 7.74 | 14.89 | 7.16 | 5.04 | 2.71 |
| 2025-26 | 6.05 | 11.89 | 5.84 | 4.64 | 3.60 |

## Validation-only blend selection

| Weight | Gross | Hits cost | Net | Transfers | Rolls |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 2246 | 24 | 2222 | 44 | 6 |
| 0.25 | 2333 | 12 | 2321 | 41 | 8 |
| 0.50 | 2226 | 4 | 2222 | 39 | 8 |
| 0.75 | 2190 | 16 | 2174 | 42 | 4 |
| 1.00 | 2316 | 8 | 2308 | 40 | 7 |

## Continuous season paths

| Season | Policy | Gross | Hits cost | Net | Transfers | Rolls |
|---|---|---:|---:|---:|---:|---:|
| 2024-25 | incumbent_xp | 2246 | 24 | 2222 | 44 | 6 |
| 2024-25 | return_distribution_challenger | 2333 | 12 | 2321 | 41 | 8 |
| 2025-26 | incumbent_xp | 2031 | 24 | 2007 | 44 | 4 |
| 2025-26 | return_distribution_challenger | 2121 | 20 | 2101 | 43 | 4 |

## Independent legal squad replay

| Season | Incumbent | Challenger | Delta/GW | Same squad | Same captain |
|---|---:|---:|---:|---:|---:|
| 2023-24 | 2294 | 2335 | +1.079 | 26.3% | 92.1% |
| 2024-25 | 2478 | 2572 | +2.474 | 18.4% | 86.8% |
| 2025-26 | 2239 | 2299 | +1.579 | 15.8% | 86.8% |

## Promotion contract

- Architecture and calibration are season-forward: each OOF forecast trains before its prior-season validation block and never sees its test season.
- The blend weight is selected on the 2024/25 continuous transfer path only. The 2025/26 path is untouched until the final gate.
- Promotion requires positive validation, positive frozen sequential and independent totals, and a moving-block downside bound above -0.10 points/GW.
- A failed challenger remains a research artifact and cannot alter the live forecast, squad, lineup, captain or transfer policy.
