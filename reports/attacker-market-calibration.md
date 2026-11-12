# Attacker betting-market calibration

Generated: 2026-08-16T18:58:37.573093+00:00
Verdict: **PROMOTE_FWD_ONLY**

Fixed bounded candidate; promote by position only when pooled development MAE does not worsen, pooled and per-season RMSE improve, and frozen RMSE improves without more than 0.001 MAE harm.

| Position | Candidate | Production | Development MAE Δ | Development RMSE Δ | Frozen MAE Δ | Frozen RMSE Δ |
|---|---:|---:|---:|---:|---:|---:|
| MID | 10.0% | 0.0% | +0.00067 | -0.00208 | +0.00230 | +0.00084 |
| FWD | 5.0% | 5.0% | -0.00025 | -0.00131 | +0.00033 | -0.00115 |

A zero production weight is an explicit rejection, not missing data. The market still enters the separately validated defender model. Forward authority remains deliberately small and changes only the non-appearance scoring component.
