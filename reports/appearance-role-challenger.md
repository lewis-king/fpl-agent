# Preseason role appearance challenger

**Built:** 2026-08-07T13:55:42.233357+00:00  
**Production changed:** no

The challenger adds longer-horizon role and minute stability to the minute classifier. Every rolling feature uses outcomes strictly before the predicted row; there are no player-specific boosts. Explicit season-boundary interactions were rejected in feature ablation rather than retained after they regressed the first forward goalkeeper slice.

| Position | Statistical gate |
| --- | --- |
| GK | PASS |
| DEF | REJECT |
| MID | REJECT |
| FWD | REJECT |

| Season | Pos | Play Brier | Role Brier | Minutes MAE | Role MAE | xP MAE Δ |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024-25 | GK | 0.0454 | 0.0454 | 13.43 | 13.31 | +0.002 |
| 2024-25 | DEF | 0.0629 | 0.0626 | 22.04 | 21.48 | +0.003 |
| 2024-25 | MID | 0.0461 | 0.0463 | 21.33 | 21.40 | -0.002 |
| 2024-25 | FWD | 0.0575 | 0.0579 | 19.61 | 19.68 | -0.002 |
| 2025-26 | GK | 0.0377 | 0.0373 | 13.49 | 13.19 | +0.002 |
| 2025-26 | DEF | 0.0674 | 0.0670 | 21.00 | 20.78 | -0.000 |
| 2025-26 | MID | 0.0553 | 0.0552 | 19.56 | 19.46 | -0.000 |
| 2025-26 | FWD | 0.0431 | 0.0430 | 20.69 | 20.90 | -0.002 |

A statistical pass is only permission to run legal squad policy replay, not promotion.
