# Lead-specific GW1–8 forecast challenger

Generated: 2026-08-10T17:31:24.765312+00:00

## Verdict

**PASS_HISTORICAL_HOLD_SHADOW** — statistically eligible positions: GK, DEF, MID, FWD. In a fresh decision at each deadline, the challenger changed 2024/25 GW1–8 by +10 points and untouched 2025/26 GW1–8 by +10.

Unlike the incumbent future-rate freeze used by the historical horizon calibration, this model is trained on player outcomes at each forecast distance. It receives only origin-deadline player/role information and the fixture schedule archived at or before that origin.

| Position | Blend | 2024/25 top-K Δ | 2025/26 top-K Δ | Gate |
|---|---:|---:|---:|---|
| GK | 0.20 | +0.050 | +0.114 | PASS |
| DEF | 0.35 | +0.005 | +0.070 | PASS |
| MID | 0.10 | +0.010 | +0.049 | PASS |
| FWD | 0.10 | +0.016 | +0.022 | PASS |

## Boundaries

- Lead models are trained on 2023/24, tuned on 2024/25 and tested once on 2025/26.
- Future fixture rows use only the latest archived snapshot at or before the decision.
- The policy replay reoptimises the legal squad, XI, bench and captain every deadline.
- Passing this historical gate creates a bounded current-season shadow. It does not replace production until prospective receipts replicate the improvement.
