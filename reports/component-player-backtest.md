# Season-forward player-component backtest

Generated: 2026-08-07T16:36:56.171644+00:00

## Verdict

**PASS** — validation selected raw weight 0.10; on the untouched 2025/26 test this produced 4.131 top-k actual points versus 4.126 for incumbent xP.

## Season-forward results

| Season | Forecast | MAE | Event Spearman | Top-k actual | Bias |
|---|---|---:|---:|---:|---:|
| 2024-25 | component | 1.022 | 0.717 | 3.908 | +0.120 |
| 2024-25 | market_component | 1.021 | 0.717 | 4.063 | +0.120 |
| 2024-25 | xp | 0.988 | 0.707 | 3.946 | -0.004 |
| 2025-26 | component | 0.979 | 0.724 | 4.134 | +0.010 |
| 2025-26 | market_component | 0.977 | 0.725 | 4.180 | +0.013 |
| 2025-26 | xp | 0.980 | 0.722 | 4.126 | -0.031 |

## Blend selection

The raw/xP blend weight was chosen only on 2024/25 top-k realised points, then frozen for 2025/26. This avoids choosing a compromise after seeing the test season.

| Raw weight | 2024/25 top-k actual | 2025/26 top-k actual |
|---:|---:|---:|
| 0.00 | 3.946 | 4.126 |
| 0.05 | 3.960 | 4.131 |
| 0.10 | 3.986 | 4.131 |
| 0.15 | 3.954 | 4.130 |
| 0.20 | 3.963 | 4.122 |
| 0.25 | 3.967 | 4.110 |
| 0.30 | 3.946 | 4.122 |
| 0.35 | 3.970 | 4.104 |
| 0.40 | 3.971 | 4.109 |
| 0.45 | 3.981 | 4.119 |
| 0.50 | 3.957 | 4.144 |
| 0.55 | 3.958 | 4.127 |
| 0.60 | 3.939 | 4.134 |
| 0.65 | 3.929 | 4.139 |
| 0.70 | 3.951 | 4.141 |
| 0.75 | 3.955 | 4.156 |
| 0.80 | 3.941 | 4.145 |
| 0.85 | 3.951 | 4.143 |
| 0.90 | 3.942 | 4.118 |
| 0.95 | 3.917 | 4.147 |
| 1.00 | 3.908 | 4.134 |

## Pre-closing market challenger

Validation selected market-component weight 0.90. Its untouched 2025/26 top-k actual score was 4.136, versus 4.126 for incumbent xP. It remains shadow-only pending an exact legal policy replay and a current deadline-safe feed.

## Scope and limitations

This is a deadline-safe expected-value reconstruction, not a replay using known match outcomes. Team goal rates, minutes classes and player event components are independently fit before each test season. Goals and assists are normalized to predicted team totals; clean sheets and concessions come from opponent Poisson rates. Goal timing, exact BPS ties and defensive-contribution micro-events remain approximations.
