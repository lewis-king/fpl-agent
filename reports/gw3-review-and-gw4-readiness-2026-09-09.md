# GW3 review and GW4 readiness

Reviewed 9 September 2026. Manager entry 2754976. No FPL account changes made.

**Update after reconnection, 08:13 BST:** GW4 successfully published and is visible in the app. The selected route is **Richarlison → Evanilson**, one free transfer, no chip, Bruno Fernandes captain and Szoboszlai vice-captain, projected **53.89 points**. The current transfer-timing advice is to wait while the route remains affordable. The run took approximately 101 seconds. The initial connection blocker described below is now resolved. The login-to-refresh wiring, live status polling and timestamp display were also fixed; see `docs/decision-refresh-lifecycle.md`.

## Bottom line

GW3 returned **43 points**, against our frozen projection of **56.85** and the official gameweek average of **51**. The same pre-deadline optimiser's no-transfer alternative would have scored **52**. Our selected transfer route therefore lost **9 points this week**. That is a genuinely poor outcome, not something to hide behind the word “robust”. It is not, on its own, evidence that a different model would consistently make better decisions.

Your actual season record is GW1 **35**, GW2 **90**, GW3 **43**: **168 total**, overall rank **6,326,509** after GW3. There are no used chips in the public history. These are actual account totals, not retrospective model scores.

The public evidence and forecasts for GW4 have been refreshed. **No GW4 transfer/chip recommendation has been published yet:** the restarted MCP is unauthenticated, and the latest private manager snapshot predates the GW3 deadline. The app correctly requires a fresh connection before treating bank, free transfers, selling prices and chip inventory as current. GW4's official deadline is **Saturday 12 September, 13:30 BST**.

## What we actually selected and played

The last archived GW3 decision was created at 16:42 BST on 4 September, before the 18:30 BST deadline. Its selected action was `A-dfba4d364b-2`:

- Gakpo → Gibbs-White.
- Lacroix → António Silva.
- Two free transfers, no hit, no chip.
- Szoboszlai captain; Gibbs-White vice-captain.

The official transfer history and submitted GW3 picks match this route and captaincy. All eleven starters played; no automatic substitutes were required.

| Player | Frozen individual xP | Actual points before captain multiplier |
| --- | ---: | ---: |
| Donnarumma | 4.08 | 7 |
| Truffert | 3.54 | 0 |
| N. Williams | 4.48 | 7 |
| António Silva | 3.58 | 1 |
| Szoboszlai (C) | 6.00 | 3 |
| Bruno Fernandes | 5.19 | 2 |
| Mbeumo | 4.51 | 8 |
| Semenyo | 5.09 | 6 |
| Gibbs-White (VC) | 5.45 | 3 |
| Igor Thiago | 5.13 | 2 |
| Calvert-Lewin | 4.08 | 1 |
| Maguire — first outfield reserve | 3.16 | 2 |
| Tarkowski — second outfield reserve | 2.65 | 3 |
| Richarlison — third outfield reserve | 0.00 | 0 |
| Verbruggen — reserve goalkeeper | 3.38 | 3 |

Raw individual forecast sums are not identical to the simulated lineup projection: the latter includes participation, automatic substitutes and captain fallback. The actual XI scored 40 before the extra 3 captain points: **43**. The bench scored 8 unused points.

## Where GW3 was lost

The most useful comparator is the **frozen no-transfer route**, not a team picked after seeing the results.

| Pre-deadline route | Actual GW3 score | Difference to selected route |
| --- | ---: | ---: |
| Selected: Gakpo/Lacroix → Gibbs-White/Silva | 43 | — |
| Keep the existing squad; play its frozen roll lineup | 52 | +9 |
| Richarlison/Mbeumo → Igor Jesus/Gibbs-White | 47 | +4 |

Relative to the frozen roll XI, Gibbs-White scored **3** where Gakpo scored **11**: an eight-point loss. Silva scored **1** where that roll XI played Maguire for **2**: another point lost. Lacroix was on the roll bench, so comparing Silva with Lacroix's individual score would give the wrong explanation.

The Richarlison-sale route was only about **0.95 modelled points behind over the five-week objective**, and marginally ahead on the immediate GW3 projection. Its realized four-point win this week belongs in the ledger. Its full GW3–7 outcome is not yet known.

Captain Szoboszlai returned 3 before doubling. Mbeumo's 8 was the highest score in the selected XI. Knowing the outcomes, captaincy alone could have added 5, and the best legal XI/captain combination within the selected 15 could have reached 52. These hindsight figures overlap; **do not add them together or call them reliably attainable gains**.

The selected action ranked **18th of 25** frozen ordinary candidates by realized GW3 points. The best considered ordinary candidate scored 65. That is an outcome ranking, not proof that its ex-ante policy was superior.

### Was this another minutes/availability failure?

Not for our GW3 XI: everyone started and played substantial minutes. Richarlison was already frozen at zero xP and did not appear. Across the 29 players in the ordinary finalist pool, there were no high-confidence non-appearances. That distinguishes this result from the earlier role problems.

There was considerable conversion/scoring variance. Gakpo registered two assists and 11 FPL points from 0.06 xG and 0.40 xA; Gibbs-White had 0.48 xG and 0.01 xA but scored 3. Those single-match underlying numbers do not establish a decisive chance-quality advantage for Gakpo. Igor Thiago had 0.50 xG, and Calvert-Lewin 0.56 xG, without corresponding FPL returns. None of this excuses the transfer outcome; it explains why simply buying last week's scorers is not a validated fix.

## Chip review, with the accounting corrected

A real diagnostic bug was found and fixed: the post-event chip scorer used the ordinary winner's squad and captain even when a frozen Bench Boost/Triple Captain candidate belonged to a **different transfer route**.

The revised scorer resolves the candidate's frozen parent, handles automatic-substitution displacement, accounts for transfer hits and squad-chip hit cancellation, and reports chip-only and combined-route gains separately. Missing parent evidence is labelled unscorable rather than guessed.

| Frozen counterfactual | Actual GW3 total | Chip-only gain on its own parent | Combined gain over our 43 |
| --- | ---: | ---: | ---: |
| Triple Captain on the selected route | 46 | +3 | +3 |
| Best frozen Bench Boost branch, with the Richarlison-sale route | 56 | +9 | +13 |
| Frozen Wildcard branch | 52 | Not separately identifiable | +9 |
| Frozen Free Hit branch | 65 | Not separately identifiable | +22 |

Bench Boost on the **squad we actually played**, without those alternative transfers, would instead have added **8**. The 13-point figure above is four points from a different transfer route plus nine chip points—not thirteen points from Bench Boost itself.

These realized immediate gains do not measure the value of retaining chips for future fixtures, nor Wildcard's longer-term benefit. They do not establish that no-chip was wrong before the deadline. The correction affects **post-event evaluation**, not the simulation that selected the original GW3 route. Original decisions/outcomes and v2 receipts were preserved; corrected results are versioned separately under `prospective_weekly_scoring_v3`.

## Evidence for and against changing the approach

### Improvements implemented in this review

1. Correct chip-to-transfer-route attribution, net costs and explicit unscorable handling, with regression cases for different benches/captains, missing parents, automatic substitutions and waived hits.
2. Versioned rescoring of GW2 and GW3, updated season/distribution scoreboards, with no replacement of frozen pre-deadline inputs.
3. Future weekly receipts now preserve expected minutes, participation bins and the estimate's provenance. Previously the archived minutes field could be null even though the optimiser used participation-bin estimates. This improves auditability; it does not secretly change forecasts or backfill old forecasts using current information.
4. The refresh contract test now follows the workspace's actual season phase rather than assuming it is always preseason.

**Validation:** 113 targeted tests passed across prospective scoring, chip strategy, weekly simulation/action selection, deadline evidence, manager-state handling and refresh coordination. Ruff passed on the touched source/test files. A dependency deprecation warning remains; no test failures remain in this targeted set.

### Changes I would prioritise next, without claiming they are already solved

1. **Adaptive future-transfer planning.** The ordinary weekly evaluator currently keeps each candidate squad fixed across its five-week horizon, reselects lineups, and adds a terminal free-transfer value. It does not fully simulate future transfer decisions conditioned on new information. That can misvalue holding an unavailable player or spending a transfer now. Compare adaptive policies on time-forward historical decisions before promotion.
2. **Transfer and liquidity continuation value.** Free-transfer option value is modelled, but that is not a complete model of future squad/bank flexibility. Price scenarios should be judged by the legal points-producing transfers they make possible or impossible, not a guessed points-per-£0.1 penalty. Richarlison remains £5.9 in today's official data, with zero projected changes, but this is not proof of a permanent price freeze.
3. **Horizon-sensitive explanation and validation.** Show one-event, short-horizon and five-week comparisons together, including why a route wins only farther out. Backtest any alternative horizon/discount setting rather than tuning it to this week's Gakpo result.
4. **Continue prospective role/distribution scoring.** Three games of lineup-source observations and two scored ordinary weekly decisions are insufficient for a best-in-world or fully calibrated claim. Role-source replay shows better lineup identification, but zero legal-policy points lift in its currently scored matched tests. Full-distribution calibration still fails several sample-size, position and tail gates. More evidence is needed, not more confident language.

No model was retuned to GW3's realized scorers. No LoRA training or FPL account writes were run.

### Historical accounting caveat

GW2's frozen route reproduces **90 gross points**, matching your public score of 90. However, that old decision also contains a four-point **already-incurred** transfer-cost field, whereas official history records zero hits. Its `realized_manager_net_points` field is therefore 86 under the archived assumptions and must **not** be presented as your actual account score. The decision-net comparison to roll remains unchanged because that archived cost was common to both. The original receipt is preserved with this discrepancy documented. GW3's frozen hit count and official score reconcile exactly.

The available GW1 weekly archive is an earlier preseason squad, not the final team actually entered. It has not been included as if it were a deployed weekly recommendation. Your actual GW1 score above comes from official history.

## GW4 refresh state and next action

- Official evidence captured **9 September, 07:33 BST**, including checked final GW3 outcomes; current-season player-event history now contains 1,890 rows.
- Direct and component forecasts regenerated for **GW4–8**.
- Delayed Betfair market data has complete fixture coverage for **GW4 and GW5**. No complete market coverage exists yet for GW6–8; do not describe those later forecasts as fully market-informed.
- RotoWire's GW4 lineup feed is usable. Fantasy Football Scout's source timestamp is stale and its observations are excluded from decision authority; this is currently single-source support, not two-source agreement.
- Richarlison remains unavailable, unselectable and **0.00 xP** in the refreshed forecasts. For context, the current direct GK forecasts favour Verbruggen (4.03) over Donnarumma (3.33); these are individual forecasts, **not a published lineup/transfer recommendation**.
- The GW3 recommendation is retained on disk. The browser hides stale weekly advice rather than presenting it as a GW4 recommendation.
- Refresh status: **needs a fresh FPL connection**, not a solver crash or a long-running optimisation. The current snapshot cannot safely establish GW4 free transfers, bank, selling prices and chips.

Open **http://127.0.0.1:5173**, connect FPL, and request the decision refresh. The frontend (5173), API (8000), MCP transport (8021) and MCP login service (8020) are running. After the new manager snapshot is captured, the normal weekly pipeline can compare rolling, transfers, hits, all 15 players' lineups/captains and legal chips, then publish only a validated GW4 result. A further near-deadline refresh remains appropriate because team news and prices can change.

## Reproducible evidence

- Official history: https://fantasy.premierleague.com/api/entry/2754976/history/
- Official GW3 picks: https://fantasy.premierleague.com/api/entry/2754976/event/3/picks/
- Official transfer history: https://fantasy.premierleague.com/api/entry/2754976/transfers/
- Official event calendar/current data: https://fantasy.premierleague.com/api/bootstrap-static/
- Frozen GW3 decision: `data/decisions/weekly/event-3/e7f0a2a5617e0c7e96c870238f6729a57b7797d4f17ae8c17b474001bbe54889.json`.
- Finalized GW3 outcomes: `data/raw/fpl/2026-27/event-outcomes/event-3/20260909T063345645695Z/event-live.json`.
- Corrected GW3 scorecard: `reports/prospective/v3/event-3-d55957a9a62d.md`.
- Immutable scored receipts: `data/model/prospective_weekly_scoring_v3/event-2/` and `event-3/`.
- Updated aggregate: `reports/prospective-season-scoreboard.md`.
- Role-source evaluation: `reports/participation-consensus-scoreboard.md`.
- Distribution evaluation: `reports/full-distribution-calibration.md`.

To rescore without using today's forecasts as yesterday's predictions:

```bash
.venv/bin/fplagent score-weekly-event --event 3
.venv/bin/fplagent prospective-scoreboard
.venv/bin/fplagent distribution-scoreboard
.venv/bin/fplagent participation-scoreboard
```

Scoring only uses the immutable decision and finalized official outcome. These diagnostic commands do not submit changes to FPL.
