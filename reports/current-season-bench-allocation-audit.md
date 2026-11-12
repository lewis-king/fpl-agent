# Current-season bench allocation audit

**Built:** 2026-08-19T16:01:25.483245+00:00
**Verdict:** SUPPORTED_AS_ROTATION_SQUAD_NOT_AS_A_DEEP_BENCH_RULE
**Active decision:** R-01afc86b1b · 3-4-3 · Bruno Fernandes captain · £20.0m bench

## Answer

The active squad survives the expanded targeted holdout, but the evidence supports a rotation structure rather than a general instruction to buy a high-priced bench. Its persistent four-cheapest allocation is inside the recent elite reference band, and most of its visible GW1 bench is scheduled to enter the XI.

The visible GW1 bench costs **£20.0m**, but the four cheapest players in the 15 cost **£19.5m**. The remaining £0.5m is caused by which owned players happen to sit out GW1, not by extra persistent reserve investment.

Of the four GW1 substitutes, **3/4** are planned to start later and they supply **8** planned starts across GW2–5.

## Fresh-selector stability

The fresh targeted winner was **R-01afc86b1b** · 3-4-3 · Bruno Fernandes captain · £20.0m bench; the active squad ranked **1**. The active-minus-winner composite-regret gap was **+0.000 points**, against a predeclared practical-equivalence bound of 0.250.

The active squad's worst family regret was **1.264**, versus **1.264** for the fresh winner. Classification: **exact_fresh_holdout_winner**. Equivalence can retain an original selector winner only when its fresh deficit is immaterial and its worst-family result is no worse; it cannot rescue a dominated squad.

## What the GW1 bench becomes

| Player | Price | Planned starts after GW1 | Premium above position floor |
|---|---:|---|---:|
| Truffert | £5.5m | GW2, GW3, GW4, GW5 | £1.5m |
| Milenković | £5.5m | GW3, GW4, GW5 | £1.5m |
| McAteer | £4.5m | None | £0.0m |
| Verbruggen | £4.5m | GW4 | £0.5m |

## Matched historical-band challenge

The targeted holdout sent **68** candidates through fresh five- and eight-week simulations, including 39 candidates at or below £18.5m and the strongest selection-screen candidates up to £20m.

The best ≤£20m challenger is **R-01afc86b1b** · 3-4-3 · Bruno Fernandes captain · £20.0m bench. It shares **15/15 players** with the active decision.

| Scenario | Active minus ≤£20m | 95% interval |
|---|---:|---:|
| base evidence open | +0.00 | +0.00 to +0.00 |
| base raw open | +0.00 | +0.00 to +0.00 |
| high goal open | +0.00 | +0.00 to +0.00 |
| gw1 3 open d088 | +0.00 | +0.00 to +0.00 |
| gw1 5 open d088 | +0.00 | +0.00 to +0.00 |
| gw1 8 open d088 | +0.00 | +0.00 to +0.00 |
| gw6 8 open equal | +0.00 | +0.00 to +0.00 |
| gw1 8 fixed d088 | +0.00 | +0.00 to +0.00 |

## Why the preferred spend changes

The cross-family result is not monotonic proof that more bench money is better. The preferred nominal bench rises as more trust is placed in today's long-horizon rotation forecast:

| Horizon-family weight | Winner | Nominal GW1 bench |
|---:|---|---:|
| 0.0%–15.5% | R-b954c5c198 | £19.5m |
| 15.5%–100.0% | R-01afc86b1b | £20.0m |

## Recent elite context

| Season | Manager | Observation | Price |
|---|---|---|---:|
| 2019/20 | Joshua Bull | exact GW1 bench | £18.5m |
| 2023/24 | Jonas Sand Labakk | maximum possible GW1 bench from published XI | £19.0m |
| 2024/25 | Lovro Budisin | exact GW1 bench from published squad | £19.0m |
| 2025/26 | Erik Ibsen | exact GW2 Wildcard bench; GW1 failed | £21.0m |

This context is descriptive and survivorship-selected. It supplies a prior, not a causal target. The four-cheapest-spend metric is also not identical to an observed GW1 bench; it is used because it is invariant to a one-week formation choice.

## Production gate

| Check | Result |
|---|---|
| artifact lineage current | PASS |
| active decision not materially falsified | PASS |
| four cheapest spend within recent 18 5 to 21 reference | PASS |
| at least two gw1 substitutes rotate later | PASS |
| at least four planned future starts from gw1 bench | PASS |
| balanced family weight is in stable champion interval | PASS |
| complete requested historical band coverage | PASS |

Publish the active squad only while this receipt remains checksum-current. If availability, price, role, fixture or forecast evidence changes, rebuild both audit families, regenerate the synthesis, and rerun this targeted gate. A high nominal GW1 bench price is never itself a positive feature.

## Limitations

- The same forecast family helps select and score candidates; paired holdouts remove Monte Carlo noise, not shared model bias.
- The high-goal run is an adversarial sensitivity test, not an alternative calibrated forecast.
- Planned rotations are valuable only if deadline availability and role forecasts remain current.
- This audit tests the strongest available targeted lean field; it does not mathematically enumerate every legal 15-player squad.

Machine receipt: `data/model/bench_allocation_audit_v2/results.json`. Active decision: `data/model/gw1_decision_synthesis_v1/results.json`.
