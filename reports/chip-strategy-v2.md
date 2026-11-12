# Joint chip strategy v2

Generated: 2026-09-09T10:57:17.566687+00:00

Historical BB/TC timing gate: **PASS**.

## What changed

- Chip choice is one event-allocation problem, so two chips can never occupy the same GW.
- A current uplift is compared with the learned value of the best later opportunity before expiry.
- Retained value decays by weeks remaining and reaches zero at expiry instead of requiring a full live forecast to GW19/GW38.
- Recent seasons dominate calibration; older relevant seasons stabilize the tails.
- WC/FH remain outcome-conservative because event-level causal counterfactuals are not yet identified reliably.

## Recency weights

- 2023-24: 17.3%
- 2024-25: 30.2%
- 2025-26: 52.5%

## Rolling-origin evidence

Expanding-window validation: each test season uses only earlier seasons. The first season is training-only.

- 2024-25: policy 34.0 actual chip points; forecast-oracle 17.0; regret +17.0.
- 2025-26: policy 17.0 actual chip points; forecast-oracle 21.0; regret -4.0.

The oracle is an offline comparator selected using deadline forecasts, not realised points. It is never available to the live policy.
