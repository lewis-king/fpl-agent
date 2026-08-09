# Price-change and early-transfer policy

**Status:** prospective shadow, zero decision authority  
**Updated:** 8 August 2026

FPLAgent now measures whether waiting until the deadline could make an already-selected transfer
route unaffordable. It does **not** recommend an early transfer yet. Price is useful only when it
preserves a points-winning route; increasing team value is not an objective by itself.

## What is implemented

The market telemetry daemon captures the public FPL player market state every 15 minutes and keeps
each observation immutable. The current feature artifact contains:

- official price-change progress, current price and ownership;
- interval transfers in/out, net and gross transfer velocity;
- ownership-normalised velocity and transfer acceleration;
- hours until the next UK midnight update; and
- status, chance of playing and current player news.

The outcome builder pairs the final observation before UK midnight with the first observation after
it, allowing no more than four hours between the pair. It records the actual £0.1m move and scores
the official `price_change_percent` threshold separately for rises and falls. The percentage is
treated as progress towards the official threshold, not as a calibrated probability.

The weekly decision engine then evaluates the selected transfer route under a one-step threshold
stress:

1. add £0.1m if an incoming player is at or beyond the rise threshold before the next update;
2. apply the exact FPL half-profit selling-price calculation if the outgoing player is at or beyond
   the fall threshold;
3. recompute the route's bank after both stresses; and
4. flag whether waiting could price out the route.

This calculation uses all transfers in the selected action and is attached to the immutable weekly
decision receipt with feature and receipt hashes. Missing, mismatched or more-than-45-minute-old
market evidence fails closed. A deadline before the next midnight update correctly produces no
price stress.

Even a stable, fully available incoming player and a route that becomes unaffordable can currently
produce only `shadow_preference: move_now_candidate`. The operational recommendation remains
`wait`, and `decision_authority` remains `false`.

## Why the apparent historical shortcut was rejected

We audited adjacent weekly player snapshots from the public historical repository. They supplied
26,945 adjacent player-week pairs in 2023/24, 21,965 in 2024/25 and 5,033 in 2025/26, and a simple
price-direction model appeared strong.

That result is invalid for an early-transfer decision. The next available snapshots were typically
3.6–5.1 days after the decision deadline, so their price labels include transfers made after the
deadline. The model would answer “did this player cost more at a later weekly snapshot?”, not “will
this player change at tonight's price update using only information available now?”. Those rows are
not used for training, calibration or promotion.

This rejection is deliberate evidence hygiene: a weaker honest prospective sample is preferable to
a large leaked sample that creates false confidence.

## Frozen prospective promotion gates

The 2026/27 stream starts with the new official predictor and scores every sufficiently tight
midnight pair. The first calibration gate requires:

- at least 14 independently observed price-change nights;
- at least 30 threshold predictions for rises and 30 for falls; and
- at least 75% precision in each direction.

Passing this only validates the official indicator at its declared threshold. It does not authorize
early moves. A second policy replay must compare `move now` with `wait` and measure:

- route feasibility after actual price changes;
- information arriving after the early move, including injuries and predicted line-ups;
- unnecessary transfers and hits caused by moving early;
- exact bank and selling-value effects; and
- realised net FPL points, with team value reported only as a diagnostic.

The policy can be promoted only if the net-points benefit is positive with a defensible downside
bound and no material increase in invalidated transfers. Until then, the app should explain the
affordability risk while advising the manager to wait for more information.

## Current state

Preseason prices are locked until the GW1 deadline, so the present market stream correctly contains
zero price pressure. The outcome receipt is `not_ready` with zero midnight pairs. Collection and
calibration will begin automatically once post-GW1 price changes are active.

Implementation:

- `src/fplagent_data/market_telemetry.py`
- `src/fplagent_engine/early_transfer.py`
- `src/fplagent_web/market_telemetry_scheduler.py`
- `tests/test_data_market_telemetry.py`
- `tests/test_engine_early_transfer.py`

