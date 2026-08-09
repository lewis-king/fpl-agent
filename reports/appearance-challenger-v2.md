# Four-class appearance challenger

**Built:** 2026-08-07T10:37:12.855997+00:00  
**Candidate rows:** 6,872  
**Production calibration changed:** no

The challenger calibrates DNP, 1–59, 60–89 and 90+ probabilities under two strict season-forward tests. The current champion P(play) is retained as the raw anchor, so this experiment measures calibration rather than a silently different classifier.

## Position decisions

| Position | Selected method | Gate |
| --- | --- | --- |
| GK | none | REJECT |
| DEF | none | REJECT |
| MID | none | REJECT |
| FWD | none | REJECT |

## Forward slices

| Season | Pos | Method | Play Brier | Multi log loss | Minutes MAE | xP MAE |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2024-25 | GK | play_logistic | 0.0458 | 0.2584 | 12.48 | 2.482 |
| 2024-25 | GK | temperature | 0.0456 | 0.2604 | 14.38 | 2.447 |
| 2024-25 | GK | two_stage_temperature | 0.0458 | 0.2597 | 13.19 | 2.482 |
| 2024-25 | DEF | play_logistic | 0.0605 | 0.7194 | 19.82 | 2.810 |
| 2024-25 | DEF | temperature | 0.0618 | 0.7256 | 19.99 | 2.790 |
| 2024-25 | DEF | two_stage_temperature | 0.0605 | 0.7185 | 19.21 | 2.810 |
| 2024-25 | MID | play_logistic | 0.0454 | 1.0169 | 20.40 | 3.082 |
| 2024-25 | MID | temperature | 0.0455 | 1.0296 | 19.73 | 3.077 |
| 2024-25 | MID | two_stage_temperature | 0.0454 | 1.0277 | 19.70 | 3.082 |
| 2024-25 | FWD | play_logistic | 0.0566 | 1.0776 | 18.78 | 3.263 |
| 2024-25 | FWD | temperature | 0.0572 | 1.0857 | 18.85 | 3.254 |
| 2024-25 | FWD | two_stage_temperature | 0.0566 | 1.0788 | 18.62 | 3.263 |
| 2025-26 | GK | play_logistic | 0.0374 | 0.2146 | 12.57 | 2.458 |
| 2025-26 | GK | temperature | 0.0367 | 0.2124 | 12.12 | 2.463 |
| 2025-26 | GK | two_stage_temperature | 0.0374 | 0.2138 | 12.45 | 2.458 |
| 2025-26 | DEF | play_logistic | 0.0679 | 0.7500 | 19.21 | 2.837 |
| 2025-26 | DEF | temperature | 0.0671 | 0.7451 | 19.34 | 2.828 |
| 2025-26 | DEF | two_stage_temperature | 0.0679 | 0.7489 | 18.90 | 2.837 |
| 2025-26 | MID | play_logistic | 0.0556 | 0.9899 | 18.97 | 2.885 |
| 2025-26 | MID | temperature | 0.0554 | 0.9855 | 19.94 | 2.847 |
| 2025-26 | MID | two_stage_temperature | 0.0556 | 0.9910 | 19.66 | 2.885 |
| 2025-26 | FWD | play_logistic | 0.0413 | 1.0527 | 20.26 | 2.926 |
| 2025-26 | FWD | temperature | 0.0431 | 1.0616 | 21.08 | 2.882 |
| 2025-26 | FWD | two_stage_temperature | 0.0413 | 1.0547 | 20.75 | 2.926 |

No calibrator is copied into the production artifact by this audit. A passing position must still survive frozen squad, XI, bench and captain replay before promotion.
