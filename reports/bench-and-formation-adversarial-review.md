# Bench spend and five-defender adversarial review

**Run:** 2026-08-03T17:38:19.974077+00:00  
**Simulations:** 25,000 base + 25,000 clean-sheet-pessimism paths · **Horizon:** GW1–5

## Verdict

The £22.5m bench is not robust enough to retain automatically: the best lean exact route (F3L) is -3.08 points from the incumbent, and the overall paired leader is C007. Five defenders fail the clean-sheet-pessimism test: the best non-five route beats the best five-defender route by 2.42 raw points. Treat 5-3-2 as model-fragile until deadline forecasts independently reconfirm it.

The £22.5m bench is not robust enough to retain automatically: the best lean exact route (F3L) is -3.08 points from the incumbent, and the overall paired leader is C007.

Five defenders fail the clean-sheet-pessimism test: the best non-five route beats the best five-defender route by 2.42 raw points. Treat 5-3-2 as model-fragile until deadline forecasts independently reconfirm it.

## What the £22.5m bench actually is

The GW1 label is misleading: two expensive outfield substitutes are planned rotation players. The current optimizer starts a player from the GW1 bench in **5 of 16** possible player-events across GW2–5. Historical top-ten GW1 substitutes started in only **24 of 160** possible player-events.

| GW1 substitute | Price | Planned starts GW2–5 | Natural no-appearance chance, all five GWs |
| --- | ---: | --- | ---: |
| Szoboszlai | £7.0m | GW2, GW3, GW4 | 0 observed; <0.012% 95% upper bound |
| Enzo | £7.0m | GW4 | 0 observed; <0.012% 95% upper bound |
| Tanaka | £5.0m | None | 0.012% |
| Verbruggen | £4.5m | GW4 | 0.004% |

Across the paired paths, autosubs add **16.84 gross points** over five weeks for the incumbent, but the best £18.5m-capped route also gets **14.14**. The marginal autosub-cover difference is therefore only **+2.70**. Planned XI rotation adds **+2.65**, and the transfer-aware policy adds **+3.54** versus holding the same 15 and choosing the best XI. These are paired model estimates, not additive causal guarantees.

The original mixed-integer objective also paid every benched player a flat **8% of xP**. That is only a search proxy: it does not know which starter misses out or whether formation allows the autosub. The component tournament itself uses exact simulated appearances and legal autosubs, and this audit additionally re-solves the problem with that proxy set to zero.

The incumbent plans **4 transfers in the four Gameweeks after GW1**. The present route therefore provides no evidence that the expensive bench is being bought to bank free transfers; its defensible case is rotation. The separate transfer-policy uplift must not be credited to bench depth.

## Exact counterfactuals under the same forecasts

| Rank | ID | Constraint | GW1 | Bench | Transfers GW2–5 | Mean | Δ B00 | 95% CI | Beat B00 |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 1 | C007 | component-evidence:component-policy:w0.05:d0.88 | 5-3-2 | £22.5m | 4 | 307.65 | +0.51 | [+0.32, +0.70] | 51.3% |
| 2 | S028 | residual-recommendation:medium-bench:Saka | 4-3-3 | £20.5m | 4 | 307.25 | +0.11 | [-0.08, +0.30] | 50.1% |
| 3 | F4 | zero-proxy-force-4DEF | 4-3-3 | £21.5m | 4 | 307.23 | +0.09 | [-0.08, +0.27] | 49.6% |
| 4 | Z00 | zero-bench-proxy | 5-2-3 | £23.0m | 4 | 307.18 | +0.04 | [-0.11, +0.19] | 50.1% |
| 5 | Z22 | zero-proxy-bench<=22.0 | 4-3-3 | £21.5m | 4 | 307.16 | +0.02 | [-0.16, +0.19] | 49.3% |
| 6 | B00 | incumbent-8pct-proxy | 5-2-3 | £23.5m | 4 | 307.14 | +0.00 | [+0.00, +0.00] | 0.0% |
| 7 | Z20 | zero-proxy-bench<=20.0 | 3-4-3 | £20.0m | 4 | 307.06 | -0.08 | [-0.26, +0.09] | 49.1% |
| 8 | F3 | zero-proxy-force-3DEF | 3-4-3 | £20.0m | 4 | 307.04 | -0.10 | [-0.27, +0.08] | 49.1% |
| 9 | F5 | zero-proxy-force-5DEF | 5-2-3 | £23.0m | 4 | 306.98 | -0.16 | [-0.31, -0.01] | 49.4% |
| 10 | F3L | zero-proxy-force-3DEF-bench<=18.5 | 3-4-3 | £18.5m | 4 | 304.06 | -3.08 | [-3.29, -2.87] | 42.2% |
| 11 | FIX | incumbent-fixed-squad-rotating-XI | 5-2-3 | £23.5m | 0 | 303.59 | -3.54 | [-3.67, -3.42] | 35.1% |
| 12 | F4L | zero-proxy-force-4DEF-bench<=18.5 | 4-3-3 | £18.5m | 4 | 303.55 | -3.59 | [-3.78, -3.40] | 40.5% |
| 13 | Z18 | zero-proxy-bench<=18.5 | 4-3-3 | £18.5m | 4 | 303.46 | -3.68 | [-3.86, -3.49] | 40.3% |
| 14 | F5L | zero-proxy-force-5DEF-bench<=18.5 | 5-2-3 | £18.0m | 4 | 301.66 | -5.48 | [-5.61, -5.34] | 31.2% |
| 15 | LOCK | incumbent-fixed-GW1-XI | 5-2-3 | £23.5m | 0 | 300.95 | -6.19 | [-6.36, -6.03] | 31.9% |

B00 is the incumbent 8%-proxy, transfer-aware solve. Z removes the proxy; Z18/Z20/Z22 also cap the full four-player GW1 bench. F3/F4/F5 force the GW1 defender count with no proxy; the L suffix also caps the bench at £18.5m. FIX holds the original 15 but rotates the XI; LOCK holds both the original 15 and the GW1 XI.

## Five defenders: historical warning and current-scoring test

The 2019/20 eventual top ten used five defenders in **2.6%** of all manager-weeks and **8.0%** of GW1–5 manager-weeks. The independent top-50 workbook records a **2.5%** legal five-defender share. That makes 5-3-2 an unusual prior, not an automatic error.

| Formation | Top-ten uses | Share | First-five uses | Mean points when used* |
| --- | ---: | ---: | ---: | ---: |
| 3-4-3 | 183 | 48.2% | 15 | 69.0 |
| 3-5-2 | 77 | 20.3% | 5 | 70.4 |
| 4-4-2 | 59 | 15.5% | 12 | 62.8 |
| 4-3-3 | 50 | 13.2% | 13 | 61.7 |
| 5-2-3 | 4 | 1.1% | 1 | 82.2 |
| 5-3-2 | 3 | 0.8% | 0 | 54.0 |
| 5-4-1 | 3 | 0.8% | 3 | 70.0 |
| 4-5-1 | 1 | 0.3% | 1 | 46.0 |

*Observational and heavily confounded by the available players, fixtures, captaincy, chips and game state; it is not a causal formation effect.

The live component model is more relevant to 2026/27 because it includes defensive-contribution points. For the incumbent GW1 five, its raw expected component decomposition is:

| Defender | Raw total | Clean sheets | Def. contributions | Goals/assists | Bonus |
| --- | ---: | ---: | ---: | ---: | ---: |
| Truffert | 2.84 | 0.56 | 0.53 | 0.67 | 0.09 |
| Collins | 3.64 | 1.14 | 0.52 | 0.57 | 0.12 |
| Tarkowski | 4.19 | 1.20 | 0.51 | 0.93 | 0.25 |
| Maguire | 3.47 | 1.13 | 0.44 | 0.56 | 0.11 |
| Senesi | 3.10 | 0.77 | 0.54 | 0.55 | 0.11 |

The 2026/27 BPS correction is now active for outfield players. Its control reproduces **380 / 380** historical match allocations exactly; CBI changes are exact and the missing tackled event proxy achieved a forward player-season rank correlation of **0.892**. Goalkeeper BPS deltas remain neutral because full save context is unavailable. The bonus column above therefore includes the promoted outfield propensity shift but remains a BPS-inspired match simulation rather than a live Opta event feed.

The adversarial fixture scenario inflates both teams’ expected goals by **15%** in every match, moving the mean team clean-sheet probability from **26.1%** to **21.5%**. It is intentionally unanchored so that the original xP cannot undo the stress.

| Stress rank | ID | GW1 | Bench | Raw stress mean | Δ B00 | 95% CI |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | Z20 | 3-4-3 | £20.0m | 296.51 | +7.55 | [+7.37, +7.74] |
| 2 | F3 | 3-4-3 | £20.0m | 296.49 | +7.54 | [+7.35, +7.72] |
| 3 | F4 | 4-3-3 | £21.5m | 295.86 | +6.91 | [+6.73, +7.09] |
| 4 | Z22 | 4-3-3 | £21.5m | 295.77 | +6.82 | [+6.63, +7.00] |
| 5 | C007 | 5-3-2 | £22.5m | 294.09 | +5.14 | [+4.94, +5.34] |
| 6 | S028 | 4-3-3 | £20.5m | 293.08 | +4.12 | [+3.93, +4.32] |
| 7 | F3L | 3-4-3 | £18.5m | 291.20 | +2.25 | [+2.04, +2.47] |
| 8 | Z00 | 5-2-3 | £23.0m | 290.36 | +1.41 | [+1.26, +1.57] |
| 9 | F5 | 5-2-3 | £23.0m | 290.09 | +1.14 | [+0.98, +1.29] |
| 10 | F4L | 4-3-3 | £18.5m | 289.72 | +0.77 | [+0.58, +0.97] |
| 11 | Z18 | 4-3-3 | £18.5m | 289.72 | +0.77 | [+0.57, +0.96] |
| 12 | B00 | 5-2-3 | £23.5m | 288.95 | +0.00 | [+0.00, +0.00] |
| 13 | FIX | 5-2-3 | £23.5m | 285.33 | -3.63 | [-3.75, -3.50] |
| 14 | F5L | 5-2-3 | £18.0m | 283.97 | -4.99 | [-5.12, -4.85] |
| 15 | LOCK | 5-2-3 | £23.5m | 280.01 | -8.94 | [-9.11, -8.77] |

## Historical bench evidence

| Sample | Initial bench price | GW1–5 stranded points | Full-season stranded points | Rank correlation |
| --- | ---: | ---: | ---: | ---: |
| 2019/20 eventual top 10 | £18.45m (range £16.5–£24.0m) | 27.1 | 214.7 | — |
| 2019/20 eventual top 50 | unavailable | unavailable | 221.5 | — |
| 2025/26 final top 100 | unavailable | 32.8 | 254.2 | +0.09 |

The old elite opening-price benchmark is £18.45m, materially below the current £22.5m. Yet only 13 of those 40 historical GW1 substitutes ever started in GW2–5; our current bench is deliberately built to rotate far more. This makes it a different strategy—not historical validation of overspending.

## Extreme failure test

The natural simulated probability that all four current GW1 substitutes make no appearance across all five weeks was **0 observed; <0.012% 95% upper bound**. I also force all four to zero minutes in every week anyway. Under that deliberately brutal counterfactual, the incumbent changes by **-22.30 points** and its advantage over the best lean route changes as shown in the machine-readable results.

## Decision rule

Do not lock the squad from price structure alone. Keep the incumbent only if it leads the zero-proxy exact alternatives in the paired evidence blend, remains competitive under inflated goal rates, and all three intended rotation players retain strong predicted minutes at the final deadline run. Otherwise promote the highest-scoring lean/non-five counterfactual and spend the released money in the XI.

This is a pre-deadline decision receipt, not a promise of realised points. Re-run it after material transfers, injuries, predicted lineups or price changes.

## Sources and limitations

- Official 2026/27 changes: https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627
- Official autosub rules: https://www.premierleague.com/en/news/2174899/
- Official transfer rules: https://www.premierleague.com/en/news/2174907
- Official 2026/27 chip rules: https://www.premierleague.com/en/news/4679879/
- Historical manager picks: local normalized Vaastav, Paul, FPL Genius, Titan and Soong datasets documented in `data/README.md`.
- Initial squad prices and subsequent picks are fully reconstructable only for the 2019/20 eventual top ten.
- All manager samples are selected after outcomes, so they describe successful routes but do not identify a causal bench-spend optimum.
- The 2019/20 formation evidence predates defensive-contribution scoring; the 2025/26 top-100 data contain bench outcomes but not weekly formations or prices.
- Bench points mix squad depth, lineup mistakes, autosub outcomes, and Bench Boost use; lower is not automatically better.
- The clean-sheet stress is a sensitivity analysis, not a calibrated alternative forecast.
- The same forecast family selects and evaluates players; paired simulations reduce Monte Carlo noise but cannot remove shared model bias.
