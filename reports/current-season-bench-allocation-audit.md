# Current-season bench allocation audit

**Built:** 2026-08-15T16:53:35.937118+00:00
**Verdict:** SUPPORTED_AS_ROTATION_SQUAD_NOT_AS_A_DEEP_BENCH_RULE
**Active decision:** R-083607ec8c · 3-4-3 · Bruno Fernandes captain · £20.5m bench

## Answer

The active squad survives the expanded targeted holdout, but the evidence supports a rotation structure rather than a general instruction to buy a high-priced bench. Its persistent four-cheapest allocation is inside the recent elite reference band, and most of its visible GW1 bench is scheduled to enter the XI.

The visible GW1 bench costs **£20.5m**, but the four cheapest players in the 15 cost **£20.0m**. The remaining £0.5m is caused by which owned players happen to sit out GW1, not by extra persistent reserve investment.

Of the four GW1 substitutes, **3/4** are planned to start later and they supply **8** planned starts across GW2–5.

## Fresh-selector stability

The fresh targeted winner was **R-1ca68907f5** · 4-4-2 · Bruno Fernandes captain · £20.5m bench; the active squad ranked **2**. The active-minus-winner composite-regret gap was **+0.054 points**, against a predeclared practical-equivalence bound of 0.250.

The active squad's worst family regret was **0.974**, versus **1.238** for the fresh winner. Classification: **practically_equivalent_lower_worst_family_regret**. Equivalence can retain an original selector winner only when its fresh deficit is immaterial and its worst-family result is no worse; it cannot rescue a dominated squad.

## What the GW1 bench becomes

| Player | Price | Planned starts after GW1 | Premium above position floor |
|---|---:|---|---:|
| N.Williams | £5.0m | GW3, GW4, GW5 | £1.0m |
| Hill | £5.5m | GW2, GW3, GW4, GW5 | £1.5m |
| Groß | £5.5m | None | £1.0m |
| Verbruggen | £4.5m | GW4 | £0.5m |

## Matched historical-band challenge

The targeted holdout sent **38** candidates through fresh five- and eight-week simulations, including 8 candidates at or below £18.5m and the strongest selection-screen candidates up to £20m.

The best ≤£20m challenger is **R-93d7c65948** · 3-5-2 · Bruno Fernandes captain · £20.0m bench. It shares **13/15 players** with the active decision.

| Scenario | Active minus ≤£20m | 95% interval |
|---|---:|---:|
| base evidence open | +0.34 | +0.18 to +0.50 |
| base raw open | +1.01 | +0.85 to +1.17 |
| high goal open | +1.02 | +0.86 to +1.19 |
| gw1 3 open d088 | +0.43 | +0.33 to +0.53 |
| gw1 5 open d088 | +0.24 | +0.12 to +0.37 |
| gw1 8 open d088 | +0.37 | +0.23 to +0.51 |
| gw6 8 open equal | +0.26 | +0.14 to +0.38 |
| gw1 8 fixed d088 | +1.19 | +1.06 to +1.32 |

## Why the preferred spend changes

The cross-family result is not monotonic proof that more bench money is better. The preferred nominal bench rises as more trust is placed in today's long-horizon rotation forecast:

| Horizon-family weight | Winner | Nominal GW1 bench |
|---:|---|---:|
| 0.0%–59.2% | R-083607ec8c | £20.5m |
| 59.2%–60.8% | R-5aac936d2a | £21.0m |
| 60.8%–100.0% | R-1ca68907f5 | £20.5m |

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
| at least 24 targeted historical band candidates | PASS |

Publish the active squad only while this receipt remains checksum-current. If availability, price, role, fixture or forecast evidence changes, rebuild both audit families, regenerate the synthesis, and rerun this targeted gate. A high nominal GW1 bench price is never itself a positive feature.

## Limitations

- The same forecast family helps select and score candidates; paired holdouts remove Monte Carlo noise, not shared model bias.
- The high-goal run is an adversarial sensitivity test, not an alternative calibrated forecast.
- Planned rotations are valuable only if deadline availability and role forecasts remain current.
- This audit tests the strongest available targeted lean field; it does not mathematically enumerate every legal 15-player squad.

Machine receipt: `data/model/bench_allocation_audit_v2/results.json`. Active decision: `data/model/gw1_decision_synthesis_v1/results.json`.
