# GW1 decision synthesis: how far should we look ahead?

**Built:** 2026-08-21T16:56:39.234760+00:00<br>
**Decision:** select **R-5954bed386** · 4-4-2 · Bruno Fernandes captain · £23.0m bench<br>
**Status:** current_evidence_provisional_until_deadline

## Bottom line

Five gameweeks on their own are too short. Eight equally trusted gameweeks are too confident about information we do not yet possess. The working outset is therefore GW1–8 with explicit decay, plus separate GW1–3, GW1–5, GW6–8, fixed-squad and forced-GW2-bank views. That horizon audit is then balanced against the original component-model and scoring-environment stress family.

The longer-horizon audit prefers **R-01afc86b1b** by +0.000 decayed points over GW1–8. That is a real result, but not a large enough one to ignore model risk. The challenger is 0.59 points off the best squad in the open-transfer high-goal stress. The selected squad is 1.34 points off the central eight-week optimum and has the lowest declared synthesis regret across the jointly tested field.

## The decision in numbers

| Squad | Five-week robust regret | Eight-week horizon regret | Worst family | Synthesis |
|---|---:|---:|---:|---:|
| Selected R-5954bed386 | 3.058 | 1.695 | 3.058 | 2.513 |
| Horizon leader R-01afc86b1b | 0.383 | 0.552 | 0.552 | 0.484 |

With the declared family weights, the selected squad ranks first of 51 jointly tested squads. The exact weight-sensitivity envelope keeps it champion while horizon-family weight is between 0.0% and 100.0%. Outside that interval a different finalist becomes preferable; the receipt records every switch.

## Why eight weeks, but decayed

The central decay is 0.88 per gameweek: GW1 receives weight 1.00 and GW8 receives 0.41. Alternative eight-week views use 0.70, 0.80 and 0.94 decay, while a separate GW6–8 scenario gives those late fixtures equal weight. The answer therefore cannot depend on one convenient decay constant.

The historical evidence does not support either extreme:

- In the public 2019/20 elite top-ten trail, the median manager still held 13 of the original 15 players in GW3, but only 6.5 by GW6 and 5.5 by GW8.
- That drop is not pure planned transfer activity: two of ten managers wildcarded in GW2 and four wildcarded in GW4.
- In the richer 2025/26 top-100 decision trail, 61 managers rolled in GW2, then only 22 rolled in GW3 and 19 in GW4. The observable pattern is early optionality followed by adaptation—not selecting a rigid eight-week XI on day one.

**Evidence limitation:** The 2019/20 cohort contains only ten elite managers and unusually early wildcard use; the 2025/26 top-100 trail is richer but transfer rows include wildcard restructures. These data inform decay and adaptability, not a causal optimal horizon.

## Is the squad tied to an easy opening run?

The selected squad is 2.46 points off the best candidate when GW1–5 are discarded and only GW6–8 count. It is 1.34 points off the best when a GW2 transfer is forbidden, and 1.36 points off the best fixed-squad candidate. These values expose, rather than hide, its dependence on the opening schedule.

## What the horizon test still cannot know

The transfer optimiser respects the live free-transfer bank and maximum carry, and it never spends points on hits. It does not model future price changes. Its open path is the best sequence under today's forecasts—not a claim to know the injuries, roles and form evidence that will arrive after GW1. Fixed-squad and forced-bank scenarios are included precisely so that this imperfect future execution cannot manufacture the winner. Every future transfer is labelled scenario-only and must clear the live role gate in a fresh weekly optimisation before it can become actionable.

## Current GW1 team

- **GK:** Donnarumma
- **DEF:** Lacroix (V), Tarkowski, Maguire, N.Williams
- **MID:** Szoboszlai, Semenyo, Bruno Fernandes (C), Mbeumo
- **FWD:** Igor Thiago, Calvert-Lewin
- **Bench:** Richarlison, Truffert, Gakpo, Verbruggen
- **Budget:** £100.0m spent; £0.0m bank

## What changed because of this review

The five-week winner was not accepted on faith. We added 128 horizon-optimizer squads plus 32 protected legal neighbours, carried all robust finalists forward, and evaluated the combined field in 5,000 selection worlds, and sent 48 through 25,000 untouched GW1–8 worlds. Every finalist received fixed, open-transfer and forced-GW2-bank policies. 8 newly generated horizon squads reached the deep final.

The best new horizon-only finalist was R-c13f51ae3a with horizon robust regret 1.246. The final choice comes from the common field because only those squads have measured regret in both independent audit families.

## Decision rule

This is not a lock. Refresh availability, price, forecast and fixture inputs and rerun both audit families plus this synthesis immediately before the GW1 deadline.

Source machine receipts: `data/model/gw1_decision_synthesis_v1/results.json`, `data/model/robust_search_v2_global/results.json`, and `data/model/horizon_audit_v1/results.json`.
