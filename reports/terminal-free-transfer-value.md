# Terminal free-transfer value calibration

Generated 2026-08-07T10:00:18.514838+00:00 from `/home/lewis/Workspace/fpl-agent/data/model/forecasts/rolling-backtest.parquet`.

## Verdict

**Promoted for weekly terminal valuation.**

The curve estimates the option value of arriving at a future deadline with 0–5 free transfers. Each historical squad is selected from only the preceding deadline forecast; the opportunity is measured from the next point-in-time forecast. The 2025/26 season is held out and realised future points are never used.

| Bank | Candidate value | Marginal value | 90% bootstrap interval |
| ---: | ---: | ---: | ---: |
| 0 | 0.000 | 0.000 | 0.000–0.000 |
| 1 | 1.566 | 1.566 | 1.408–1.722 |
| 2 | 3.247 | 1.681 | 2.955–3.559 |
| 3 | 4.358 | 1.111 | 3.949–4.781 |
| 4 | 5.170 | 0.812 | 4.675–5.664 |
| 5 | 5.852 | 0.682 | 5.255–6.425 |

## Held-out calibration

- Candidate MAE: 0.942
- Zero-value baseline MAE: 3.474
- Candidate RMSE: 1.145
- Zero-value baseline RMSE: 3.835

## Promotion checks

- PASS — training coverage: 23 states across 2023-24, 2024-25
- PASS — held-out coverage: 13 states in 2025-26
- PASS — held-out MAE beats zero: candidate=0.942; zero=3.474
- PASS — held-out RMSE beats zero: candidate=1.145; zero=3.835
- PASS — no bank regresses against zero: banks 1-5 checked separately
- PASS — maximum-bank distribution remains stable: train=5.852; validation=5.124; gap=0.728; tolerance=2.562

## Interpretation limits

- This calibrates future flexibility under the forecast model; it is not a claim that observed managers used their transfers optimally.
- The runtime discounts the curve to the end of its fixed forecast horizon.
- Actual weekly decisions still compare roll and every generated route under shared residual and component simulations.
