# Matched OpenFPL-method benchmark

**Built:** 2026-08-15T20:57:26.650686+00:00  
**Gate:** PASS  
**Production authority:** none

FPLAgent MAE 0.978 vs OpenFPL-method 0.993; OpenFPL legal-policy delta -69.0.

The benchmark contains 12 position/season folds, 84,999 matched player-deadline forecasts and 114 legal event decisions.

| Model | MAE | RMSE |
|---|---:|---:|
| FPLAgent | 0.9779 | 1.9409 |
| OpenFPL method | 0.9934 | 1.9373 |

| Season | Events | OpenFPL − FPLAgent points | OpenFPL wins | Ties | Losses |
|---|---:|---:|---:|---:|---:|
| 2023-24 | 38 | +41.0 | 18 | 4 | 16 |
| 2024-25 | 38 | -103.0 | 16 | 1 | 21 |
| 2025-26 | 38 | -7.0 | 18 | 3 | 17 |

The same player-deadline rows feed the same legal £100m squad, XI, bench and captain solver.
The external model is a method reproduction pinned to the public repository commit; it is not a renamed internal baseline or a claim that released weights fit our schema.
