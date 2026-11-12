# FPLAgent: opening three gameweeks and improvement priorities

Reviewed **9 September 2026**, using completed GW1–3 outcomes, public manager histories and league standings, the frozen decisions actually relevant to GW2/GW3, current GW4 production receipts, source code and existing historical experiments.

This is a **review, not a new recommendation run**. No forecasts, optimiser settings, published decisions, FPL account state or LLM models were changed. Public standings and player figures are a morning snapshot, not a promise that they remain unchanged.

## Executive assessment

We have a substantial decision system, but the opening results do not establish a competitive edge. More simulations of the same assumptions are not the highest-value next step. The priorities are to correct a demonstrated fallback defect, value future transfers and squad flexibility properly, complete the four-chip policy, and test player-role and squad-allocation hypotheses against genuinely forward evidence.

The most concrete new finding is independent of hindsight: **the ordinary selector checks the first-ranked action and otherwise falls straight back to rolling. It does not select the next-ranked action that passes its checks.** On the frozen GW2 candidates, Richarlison → Igor Jesus was an example of a skipped, higher-ranked-than-roll, gate-passing action. That alternative happened to score the same 90 points as rolling in GW2; this finding must not be presented as an established points loss.

## 1. Actual season performance

| Event | Our actual points | Official average | Difference | Unused bench points |
| --- | ---: | ---: | ---: | ---: |
| GW1 | 35 | 50 | -15 | 21 |
| GW2 | 90 | 81 | +9 | 18 |
| GW3 | 43 | 51 | -8 | 8 |
| Total | **168** | **182 summed weekly averages** | **-14** | **47** |

Overall rank is approximately **6.33 million**. We have used **no chips and taken no transfer hits**. The sum of rounded weekly averages is descriptive, not a matched no-chip manager benchmark. Similarly, 47 unused bench points are not 47 points that an attainable alternative policy would necessarily have scored: some bench output buys injury cover, future rotation and chip potential.

Sources: [our official history](https://fantasy.premierleague.com/api/entry/2754976/history/) and [official event/player data](https://fantasy.premierleague.com/api/bootstrap-static/).

### Frozen forecast and decision attribution

- **GW2:** predicted 57.70, realized 90. Bruno's captaincy was successful. However, Richarlison was still given approximately 93% appearance probability and did not play: that was a genuine role miss, not merely finishing variance.
- **GW3:** predicted 56.85, realized 43. Every selected starter started; the poor result was not another high-confidence non-appearance problem in our XI.
- The frozen **GW3 roll route scored 52**, against the selected route's 43. Gibbs-White scored 3 versus the sold Gakpo's 11; Silva scored 1 versus Maguire's 2 in the *roll XI*. Lacroix was on that roll bench, so comparing Silva directly with Lacroix would misattribute the difference.
- The full five-week consequences of the GW3 transfers are **not yet observable**. The Richarlison-sale alternative was only about 0.95 projected points behind over that horizon; we must finish scoring both paths rather than declare a five-week verdict after one match.
- Gakpo produced 0.46 xGI in GW3; Gibbs-White 0.49. The 11–3 FPL-points difference is not evidence of a comparably large difference in chance production that week.
- The accessible GW1 weekly archive is an earlier preseason squad, not the final submitted team. It should not be relabelled as a deployed forecast. GW1 account scoring is still available from FPL.
- An old GW2 receipt contains four already-incurred hit points that disagree with the official zero-hit history. Our actual GW2 total is **90**, not the receipt's 86 after that erroneous historical assumption. This inconsistency is already documented; frozen evidence should remain immutable with explicit corrections alongside it.

Detailed attribution and versioned scoring references: [GW3 review](gw3-review-and-gw4-readiness-2026-09-09.md), [GW2 scorecard](prospective/v3/event-2-d3ebaba78e4b.md), [GW3 scorecard](prospective/v3/event-3-d55957a9a62d.md).

## 2. What managers ahead of us are doing

I examined the current overall top three and the leader of each of our six private classic leagues, including their public completed-gameweek picks, captaincy, hits, chips and available past ranks. This is a deliberately small descriptive sample, **not an unbiased training cohort**.

### Our actual mini-leagues

| League | Our rank | Leader | Leader points | Current gap | Chips already used by leader |
| --- | ---: | --- | ---: | ---: | --- |
| Buddy Premier League | 4 | Essex Eagle | 216 | 48 | TC |
| Game's Gone Normal | 22 | Struijk My L0ngstaff | 241 | 73 | BB, FH |
| Sport AitchQ | 3 | Notpatrikshady | 222 | 54 | BB, WC |
| TEN Ten FPL | 13 | Champions Again | 244 | 76 | BB, WC |
| The Ascension | 29 | I De Zerbi to win | 259 | 91 | BB, TC |
| Formula Super Cup | 27 | Not too Xabi | 232 | 64 | WC |

Standings sources: [Buddy](https://fantasy.premierleague.com/api/leagues-classic/24942/standings/), [Game's Gone Normal](https://fantasy.premierleague.com/api/leagues-classic/637776/standings/), [Sport AitchQ](https://fantasy.premierleague.com/api/leagues-classic/712113/standings/), [TEN Ten](https://fantasy.premierleague.com/api/leagues-classic/803975/standings/), [The Ascension](https://fantasy.premierleague.com/api/leagues-classic/804132/standings/), [Formula Super Cup](https://fantasy.premierleague.com/api/leagues-classic/1232738/standings/).

All six leaders took zero hits across GW1–3. Four used Bench Boost in GW1. Five started with João Pedro; all six had Arsenal representation in their starting XI, including goalkeepers. Some also carried players who did not play. The lesson is not that their every choice was correct; it is that we should test affordable productive attackers, Arsenal/other strong-team defence, captain routes and chip-adjusted squad allocation explicitly. Today's high ranks do not establish persistent manager skill.

The overall top three have **307, 306 and 305 points**, but have already spent **three, two and three chips**, respectively. All three used GW1 Bench Boost. None took a hit. Their available previous ranks do not identify this sample as consistently elite across seasons. We cannot attribute their advantage entirely to superior forecasting, nor dismiss the entire gap as chip expenditure.

Sources: [overall standings](https://fantasy.premierleague.com/api/leagues-classic/314/standings/), histories for entries [1717192](https://fantasy.premierleague.com/api/entry/1717192/history/), [895045](https://fantasy.premierleague.com/api/entry/895045/history/), [4089628](https://fantasy.premierleague.com/api/entry/4089628/history/). Completed picks are available at `/api/entry/{entry}/event/{event}/picks/`.

We still have 35 gameweeks. The current private-league gaps correspond arithmetically to about 1.4–2.6 extra points per remaining week relative to those leaders, before considering different chip inventories. That is not a forecast of recovery, but it argues against panic hits or low-ownership gambles merely to look different.

### Historical manager evidence we actually have

- `data/processed/fpl_genius/managers.parquet`: 100 manager summaries from 2025/26, ranks 1–104, captured July 2026. These are end-season-selected summaries, not an unbiased longitudinal population.
- `data/processed/supporting/soong_manager_gameweeks.parquet`: 266 rows, seven full 2025/26 manager seasons, with chips, hits and bench points.
- `data/processed/vaastav/top_manager_gameweeks.parquet`: ten managers from **2019/20 only**. This must not be described as recent multi-season elite behaviour.
- Other stored samples include 2022/23 manager histories and 2025/26 summary leaderboards. Current-season entry IDs must be verified, not assumed to carry over from last year.

A useful next benchmark would freeze a cohort selected by **performance before this season**, then score its current decisions without replacing members with whoever happens to lead each week. Manager behaviour should propose hypotheses, not become a causal label saying an action was optimal.

## 3. Season and player signals

Arsenal and Manchester City have won all three league matches. Arsenal have conceded once, City twice. Hull have three clean sheets and seven league points. Manchester United have scored seven but conceded six; Chelsea have scored eight but conceded seven. These are only three-game samples: opponent quality, fixtures and market expectations should temper any team-strength update.

Calculated from the [official fixture results](https://fantasy.premierleague.com/api/fixtures/). Hull's clean sheets are a reason to inspect defensive process, not to assign them an elite defensive rate from three matches.

| Player | Price now | GW1–3 points | Minutes | xG + xA | Interpretation for investigation |
| --- | ---: | ---: | ---: | ---: | --- |
| Gakpo | £7.2m | 28 | 250 | 1.56 | Productive, relatively affordable, and currently playing. Review our sale and tactical role; don't mechanically project his points streak. |
| Bruno Fernandes | £12.0m | 27 | 270 | 3.05 | Highest cumulative xGI in this snapshot. His underlying involvement supports continued consideration, not automatic captaincy in every fixture. |
| Haaland | £15.5m | 24 | 270 | 2.96 | Strong full-role premium. Compare the whole affordable route into him, including captaincy, not his price or individual xP in isolation. |
| Mbeumo | £7.9m | 21 | 270 | 2.78 | Strong involvement despite net sales. Popularity changes are not a sell signal by themselves. |
| Igor Thiago | £7.9m | 4 | 262 | 2.40 | A poor FPL return with substantial chances and minutes. This is different from a player losing his job; finishing ability, penalties and alternatives still matter. |
| Isak | £9.1m | 23 | 243 | 2.35 | A legitimate productive-forward comparator, subject to current role/fixture evidence and affordability. |
| João Pedro | £7.7m | 21 | 270 | 2.03 | A particularly relevant alternative to our attacking budget allocation. |
| Ødegaard | £6.6m | 24 | 221 | 2.06 | Affordable creation and involvement; verify role/minutes before extrapolating. |
| De Cuyper | £4.8m | 21 | 243 | 1.90 | Strong attacking involvement for an FPL defender; tactical deployment deserves explicit attention. |
| Truffert | £5.5m | 5 | 270 | 0.14 | Regular minutes, but little attacking production. Review the value of this defensive allocation rather than assuming he is unlucky in the same way as Thiago. |

Player figures: [official bootstrap](https://fantasy.premierleague.com/api/bootstrap-static/). xGI is expected goals plus expected assists; it is **not** expected FPL points, does not include defensive contributions and does not eliminate conversion variance.

Additional watches: Cherki has 25 points and 1.91 xGI, but only 173 minutes; Foden has 2.47 xGI and 11 points in 195 minutes. These are examples where role/minutes and attacking process must be considered together. Hull's Tzolakis has 26 points, but the team clean-sheet streak must be regressed rather than treated as permanent.

The official expert panel already identified De Cuyper's advanced attacking deployment and Thiago's missed chances before GW3. That is useful timestamped context: a tactical-role signal is not the same thing as chasing an outcome after the match. [Pre-GW3 expert analysis, 2 September](https://www.premierleague.com/en/news/4705515).

Defensive contributions remain relevant: the rule awards two points at the match-specific threshold, not a linear reward for a high per-90 average. Historical scoring-rule differences require explicit treatment. [Current official explanation](https://www.premierleague.com/en/news/4361991/).

## 4. What is genuinely in the application today

### Strong foundations worth retaining

- Authenticated squad, bank, selling prices, transfer inventory and chip state; public player/event/fixture data captured with provenance.
- Finalized event history checked before it enters features; archived pre-deadline forecasts and post-event scoring.
- Own position-aware player models using historical points, minutes, xG/xA and adjusted team/opponent information. `ep_next`, `ep_this` and official `xP` are forbidden forecast features.
- Exact squad/transfer legality, paid-hit accounting, captain fallback and legal automatic substitutions; all 15 players considered for the XI and bench.
- Shared residual and match-component simulation worlds. The ordinary weekly weights are 50% residual, 45% xP-anchored component and 5% raw component, with a separate worst-model-regret penalty.
- A large preseason squad search and a bounded weekly transfer candidate funnel. Repeated weekly refreshes reconsider decisions using new evidence; closing the browser does not turn the server job into a browser-only computation.
- Chips have explicit inventory/expiry/collision rules, and rejected alternatives are retained for later evaluation.
- The LLM is an explanation/interface layer, not the source of points forecasts or legal decisions. No new LLM work is proposed here.

### Important qualifications from the active GW4 receipts

1. **Future transfers are not adaptive inside the ordinary valuation horizon.** Each proposed roster is held across the five-event projection, with future lineups selected from it. Running the optimiser again next deadline is useful, but is not the same as valuing those future choices today.
2. **Transfer option value currently collapses for these candidates.** Every ordinary GW2, GW3 and current GW4 candidate receives the same terminal transfer value, approximately 3.088 points. In GW4, rolling leaves two FTs next week, while using one leaves one; both are projected to reach the five-FT cap by the end of the fixed horizon. Their near-term difference in flexibility is consequently not valued by this terminal term.
3. **Wildcard and Free Hit cannot currently become operational recommendations.** BB/TC have bounded authority; WC/FH are exact but advisory branches. Current GW4 WC has about +2.23 joint projected value but fails uncertainty and historical-authority checks. That is not an instruction to Wildcard. It is evidence that “no chip” needs a more qualified explanation.
4. **The live market pipeline is not a blanket market-driven player forecast.** Current GW4/GW5 match goals have an operator-authorized, provisional 10% market-rate blend. GW6–8 use internal rates. The separate player market-feature adjustment is inactive in weekly mode. Its early return also prevents the separate attacker adjustment from running in this mode. Understat's feature challenger is currently inactive, not secretly powering the deployed player xP. These statuses are different from data availability.
5. **Lineup support is currently one eligible source.** RotoWire contributes bounded role adjustments; stale FFS observations are excluded. The prospective consensus scoreboard has three events but zero qualifying two-source team counts, not demonstrated two-source superiority.
6. **Intervals are easy to overread.** The displayed paired 95% range measures Monte Carlo uncertainty in a conditional expected gain, not the range of real football outcomes or all model error. The current weighted gain is +2.155, while its displayed residual-world interval is +2.164 to +2.307: they describe different quantities. More simulations can narrow that interval without making our football assumptions more correct.

Sources: current decision `data/decisions/2026-27-weekly-current.json`; forecast manifest `data/model/forecasts/2026-27-preseason-manifest.json`; [chip strategy documentation](../docs/chip-strategy-v2.md); [participation scoreboard](participation-consensus-scoreboard.md); [Understat experiment](understat-preseason-feature-challenger.md).

## 5. Priorities, in implementation order

### 1 — Correct selection among acceptable actions

**Evidence:** `src/fplagent_engine/weekly_decision.py:419` tests only the robust leader, then selects roll if that gate fails.

On the frozen GW2 candidates, the first two Botman routes failed the ordinary cross-world safety gate. Rank three, **Richarlison → Igor Jesus**, passed it: +0.688 weighted horizon points, +0.560 in the worst world. Roll ranked fifth, yet was selected. The skipped route's actual GW2 score was 90, equal to rolling; no realized points improvement is claimed.

**Change:** evaluate gates for every ranked ordinary candidate, choose the highest-ranked acceptable action (with roll still a candidate), and run the selected action through the full role/deadline gates. Preserve the failed leader and every rejection reason. Do not loosen legality or role checks to make a candidate pass.

**Acceptance:** regressions for rejected first and second candidates with an admissible third, no admissible transfers, paid routes, and a newly failed final role gate; replay all frozen decisions and explicitly classify changes.

### 2 — Adaptive transfers, retained cash and future affordability

**Evidence:** `weekly_actions.py:423` assigns terminal FTs assuming no subsequent transfers; `weekly_simulation.py:113` scores today's planned rosters. This can overvalue long-horizon rotation while missing the value of rolling, future repairs, or keeping room for a premium upgrade.

**Change:** begin with a bounded two-stage scenario-tree planner: choose now; next deadline observe simulated information updates and permit legal recourse. Carry squad, purchase/sale prices, bank, FTs and chip inventory. Actions must share information until it is observed; never allow a future transfer to exploit simulated match outcomes before that deadline. Use a calibrated continuation value beyond the reliable explicit tree.

Price changes should alter the legal points-producing routes available, not add an arbitrary points penalty for losing £0.1m. Preserve future ability to reach Haaland/Palmer/Isak-type price brackets where it actually matters. Compare 1/3/5-event sensitivities, and validate the discount rather than changing it to rescue a recent result.

**Acceptance:** recent full-season sequential replays with exact state accounting, plus prospective shadow decisions; benchmark against our fixed-roster planner using net points, hits, capital-constrained missed routes and solve latency. No future-price or injury leakage.

### 3 — Complete and transparently validate the four-chip policy

**Change:** extend the adaptive state planner to WC permanence, FH restoration and WC→BB interaction. Compare every current chip with the best feasible remaining allocation, including expiry. A Free Hit must not be hard-excluded merely because the week is not a blank/double: that is a strategy heuristic, not an FPL legality rule. Require a demonstrated net-points benefit before changing operational authority.

The chip calibration also needs a validation correction: `_historical_gate` in `chip_strategy.py:354` is **leave-one-season-out**, despite “rolling-origin” wording in the report. The 2023/24 fold trains on 2024/25 and 2025/26. The 2025/26 fold uses earlier seasons and remains the chronologically valid one; the older folds must not be advertised as time-forward evidence. Replace this with forward-only folds and explicit recency weighting.

**Acceptance:** exact current rules, expiry and collision tests; matched chronological paths through entire chip halves, including ordinary transfers and no-chip policies; compare net season points, not only positive chip uplift. Display “worth playing”, “worth keeping”, and “potentially worthwhile but not validated” separately.

Current rules still provide two sets of four chips, with first-half expiry and only one per GW. [Official 2026/27 chip rules](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627).

### 4 — Faster recognition of genuine role and team changes

**Change:** distinguish a scoring streak from a changed job. Use timestamped starts, substitution patterns, role/formation observations, penalty responsibility, per-minute xG/xA, team share and fresh lineup information. Examples to test include De Cuyper's advanced role, Richarlison losing selection, City rotation, and the difference between Thiago's missed chances and Truffert's limited attacking involvement. Apply opponent-adjusted shrinkage for new/promoted teams rather than taking three results literally.

The current feature matrix already contains short/long form and xG/xA; this is not a proposal to add information we already use under a new name. Explicit tactical role and calibrated change detection are the missing hypotheses. Collect a genuinely independent second role source if available, but do not duplicate stale feeds or bypass access controls.

Also audit the market provider→match-rate→player-xP→candidate funnel end to end. The market challenger must be able to propose relevant candidates, not only rescore a narrow set chosen by a non-market forecast. Keep all authority weights visible and checksum-bound.

**Acceptance:** forward tests of minutes/starts, captain-relevant and active-player forecast quality, and resulting legal decisions. Directly score old and new role policies on fresh receipts. Do not inflate xP for whichever player won last week.

### 5 — Re-test squad capital allocation and the objective

The expensive-bench question remains legitimate. The existing bench-allocation report describes an **earlier August squad**, not the current roster, so it cannot certify this week's structure. Our unused bench points alone also cannot prove overinvestment.

**Change:** compare reachable lean-bench, balanced-rotation and premium-captain routes, both through ordinary transfers and a legal Wildcard. Attribute reserve value to expected autosub use, scheduled XI rotation and chip benefit; charge the opportunity cost in the XI and captain slot. Give Haaland/Arsenal/Chelsea/cheaper-defender structures equal candidate access without forcing them to win.

Our primary goal is expected seasonal net points. The current minimax-like penalty can intentionally sacrifice the weighted expected score: on GW4 it gives up approximately **0.337 projected five-week points** to prefer Richarlison → Evanilson over Maguire → Muharemović, whose worst-world gain reverses slightly. GW3's selected route was also the weighted-mean winner, so removing risk aversion would not explain away its poor result. Test the actual value of this penalty, rather than rewarding or suppressing variance by instinct.

**Acceptance:** a matched decision replay for risk weight, horizon and allocation families; disclose expected points forgone for model-uncertainty protection. Ownership should not become a standalone differential bonus. Maximizing league-win probability can be a separate late-season objective, explicitly chosen rather than silently substituted for points.

### 6 — Stronger prospective evidence and more honest decision reporting

**Change:** extend immutable scoring to the entire forecast universe and decision-relevant cohorts, not just finalists. Score appearance, conditional points, captaincy, bench use, defender components and chip opportunity costs separately. Keep one-week hindsight regret distinct from a feasible sequential policy's gain.

Show three different uncertainties: Monte Carlo precision; outcome prediction spread; uncertainty about model assumptions. A narrow simulated mean interval is not proof the suggested transfer will win in real life. Display numerical precision separately and do not pair one world's interval with a different weighted estimate without labelling it.

Freeze new benchmark policies and manager cohorts now. Use matched folds, budgets, hits, FTs and chip rules; report active-player accuracy as well as whole-universe MAE, which can be flattered by easy zero-minute predictions. Repeatedly inspecting the same 2025/26 test season across many experiments weakens a global “untouched” claim even where each individual experiment's split was valid.

**Acceptance:** weekly reconciliation to official account totals, pinned incumbent/challenger versions, complete delayed multiweek policy scoring, position/tail calibration and a logged promotion/rejection decision. Three events are not enough to certify a best-in-world model.

## 6. Historical results: useful evidence, not a licence to overclaim

- **Form reversion:** the stored lagged audit reports only 9.1% persistence of a recent points deviation after its controls. A process-reversion policy scored +23 net points on 2025/26, but its block interval crossed zero. The tested naive form-chasing policy suffered substantially, including excessive hits. This supports caution about points streaks, not automatic promotion of that challenger. [Replay](form-reversion-policy-replay.md).
- **Horizon:** the 5/0.88 challenger tied the 8/0.88 incumbent on the tested 2025/26 opening path. This is limited opening-window evidence, not a learned universal optimum or proof that fixed future rosters are sufficient. [Replay](horizon-decay-policy-replay.md).
- **Markets:** Betfair improved historical match-goal forecasting, but the selected player/transfer policy lost two points on its 2025/26 path. Better match forecasts do not mechanically imply better legal FPL decisions. The active 10% deployment is explicitly provisional and operator-authorized. [Calibration](betfair-exchange-calibration.md).
- **External model:** the matched OpenFPL-method reproduction covered 84,999 player forecasts and 114 legal decisions; aggregate results favoured us by 69 points, but OpenFPL was ahead by 41 in one season and only seven behind in 2025/26. This is a method reproduction with specific decision constraints, not proof of superiority over all public models or actual elite managers. [Benchmark](openfpl-matched-benchmark.md).
- **Prospective:** only two ordinary weekly events are fully scored against deployed frozen decisions, with a total -9 points versus frozen roll references. The distribution and role evidence still has important sample/coverage gaps. [Scoreboard](prospective-season-scoreboard.md), [distribution status](full-distribution-calibration.md).

## 7. Current recommendation remains unchanged during this review

The validated GW4 run published at **08:13 BST on 9 September** remains active:

- **Richarlison → Evanilson**, one free transfer, no hit.
- **Bruno Fernandes captain**, Szoboszlai vice-captain.
- **No operational chip recommendation**; the WC advisory qualification above matters.
- Projected GW4 score **53.89** including captaincy; weighted five-week gain over rolling **+2.16** under the current model.
- Current transfer timing advice is **wait**; another evidence refresh near the deadline remains appropriate.

The official GW4 deadline is **Saturday 12 September, 13:30 BST**. This review neither submits that transfer nor claims the proposed improvements have been implemented.

## Verification performed for this review

Read-only public API checks; archived-score reconciliation; code-level and live-artifact inspection; and a direct reproduction of the ordinary promotion checks on the frozen GW2 candidates.

Targeted existing tests:

```bash
.venv/bin/pytest -q tests/test_engine_weekly_decision.py \
  tests/test_engine_weekly_actions.py tests/test_engine_chip_strategy.py \
  tests/test_engine_weekly_simulation.py
```

**42 passed in 0.85 seconds.** The passing suite does not cover the skipped-admissible-runner-up case identified above. No source changes or new training runs were made.
