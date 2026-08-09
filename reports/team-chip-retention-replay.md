# Bench Boost and Triple Captain retained-value replay

Generated: 2026-08-08T19:43:58.979351+00:00

**REJECT**

Selection uplift: +40 points. Untouched test uplift: +24; four-GW block interval +0.000 to +1.737 points/GW.

Forecast-oracle test uplift: +22; frozen-policy delta: +2. Four-GW oracle-regret interval: -0.474 to +0.711 points/GW.

Failed gates: oracle_regret_block_lower_bound_above_minus_point_two_five.

The trigger pair is selected on 2023/24 only and tested on 2024/25. Every opportunity uses the forecast and schedule visible at that deadline; realised uplift is used only for scoring after the trigger is frozen.

The forecast oracle is an offline retained-timing upper bound: within each half it selects the best forecast-visible Bench Boost and Triple Captain opportunities at distinct deadlines. It never enters the live policy.

The replay isolates BB/TC on the ordinary transfer path. Joint competition with Wildcard and Free Hit and prospective 2026/27 evidence are still required for live authority.
