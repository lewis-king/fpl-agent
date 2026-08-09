# Form persistence and mean-reversion policy replay

Generated: 2026-08-08T17:15:57.478537+00:00

## Verdict

**HOLD_SHADOW** — the lagged historical audit classifies the evidence as `strong_mean_reversion_observed`. Only 9.1% of a recent three-versus-ten-event points deviation carries into the next event after the declared controls.

Validation selected `process_reversion_expected_points` at a 10% correction. The untouched 2025-26 continuous path changed by +23 net points (+0.605/GW), with a four-event moving-block interval of -2.658 to +4.026/GW. Production is unchanged.

## Lagged form cohorts

| Quintile | Prior 3 | Prior 10 | Next | Next 3 | Next 5 | Rows |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.85 | 3.88 | 2.99 | 3.01 | 2.99 | 7440 |
| 2 | 2.23 | 3.04 | 2.83 | 2.79 | 2.76 | 7431 |
| 3 | 2.86 | 2.95 | 2.84 | 2.82 | 2.77 | 7425 |
| 4 | 3.84 | 3.13 | 3.01 | 2.99 | 2.96 | 7421 |
| 5 | 6.02 | 3.76 | 3.30 | 3.25 | 3.22 | 7414 |

## Underlying-process confirmation (xG era, MID/FWD)

| Streak | Process | Prior 3 | Prior 10 | Next | Next 5 | xGI/90 | Rows |
|---|---|---:|---:|---:|---:|---:|---:|
| cold | strong_process | 2.51 | 4.75 | 3.69 | 3.71 | 0.440 | 824 |
| cold | weak_process | 1.78 | 3.77 | 2.87 | 2.82 | 0.168 | 652 |
| hot | strong_process | 7.07 | 4.56 | 4.13 | 3.91 | 0.511 | 993 |
| hot | weak_process | 5.63 | 3.51 | 3.05 | 3.00 | 0.178 | 476 |

## Sequential policy paths

| Season | Policy | Gross | Cost | Net | Transfers | Rolls | Short exits |
|---|---|---:|---:|---:|---:|---:|---:|
| 2024-25 | incumbent_xp | 2246 | 24 | 2222 | 44 | 6 | 10 |
| 2024-25 | selected_reversion | 2331 | 20 | 2311 | 43 | 4 | 9 |
| 2024-25 | naive_form | 1997 | 228 | 1769 | 95 | 0 | 11 |
| 2025-26 | incumbent_xp | 2031 | 24 | 2007 | 44 | 4 | 4 |
| 2025-26 | selected_reversion | 2046 | 16 | 2030 | 42 | 7 | 7 |
| 2025-26 | naive_form | 1918 | 212 | 1706 | 91 | 0 | 8 |

## Promotion contract

- Every form feature is lagged before the evaluated deadline; current-event outcomes are labels only.
- Correction type and strength are selected on 2024/25 continuous net points only. The 2025/26 path is untouched until the final gate.
- The replay carries the legal squad, bank, purchase/selling prices, free transfers, hits, XI, bench and captain through all 38 events.
- Naive recent-points chasing is retained as a behavioural comparator, not a candidate.
- Even a passing historical challenger remains shadow-only until prospective 2026/27 receipts confirm it; this command cannot change production forecasts or decisions.
