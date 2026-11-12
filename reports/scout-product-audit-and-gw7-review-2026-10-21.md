# Season review and Fantasy Football Scout audit

21 October 2026 · entry 2754976 · completed GW1–7 · GW8 decisions not regenerated

## Executive conclusion

The subscription works: the authenticated Scout projections and other member tools rendered
with numerical tables rather than subscription gates. Scout is useful as an independent
comparison and product reference, not evidence that its forecasts are necessarily better.
No paid dataset was bulk downloaded, copied into training, or made an automatic production feed.

Our most urgent gap is not another optimiser search. It is checking whether the forecasts and
uncertainty supplied to that search are trustworthy, especially for minutes and captaincy.
This implementation closes a feedback-loop gap and adds the user-visible review needed to
judge subsequent improvements. It does **not** claim an observed increase in future points.

## What actually happened

Public official manager history, locked event picks and final, data-checked event-live outcomes
were fetched and reconciled. Each player's official points times their official multiplier must
sum to the manager's gross score; transfer hits are subtracted once. Actual picks are never
assumed to equal our advice.

| GW | Actual net points | FPL event average | Latest frozen advice, scored on actual outcomes |
| --- | ---: | ---: | ---: |
| 1 | 35 | 50 | 34 |
| 2 | 90 | 81 | 86 |
| 3 | 43 | 51 | 43 |
| 4 | 56 | 69 | 56 |
| 5 | 62 | 48 | 62 |
| 6 | 36 | 58 | 36 |
| 7 | 60 | 59 | 60 |

The official total is **382**, overall rank **6,813,914**. That is 34 points below the sum of
the reported event averages. There were no transfer hits or chips used in these seven events.
Weekly counterfactual advice is scored against that week's actual starting state; summing it
does not establish an executable alternative season-long transfer policy.

### GW7: the problem was not an unperformed recommendation

The final archived GW7 advice was created on **17 October at 07:53:23 UTC**. It supersedes the
16 October receipt discussed in the older handoff. It selected no further transfer, no chip,
Semenyo captain and Igor Thiago vice-captain. Bruno and Hall started; the actual locked team
matched this recommendation. Its ordinary risk-adjusted projection was 52.42; actual points were
60, versus the FPL average of 59. One score exceeding one projection does not establish calibration.

Semenyo was forecast at approximately **80 minutes and 5.00 points**, with 95.5% probability of
any appearance but only 5.6% probability of a 1–59-minute appearance. He played **13 minutes
and scored one point**. Thus a good-looking appearance probability concealed the relevant
captain risk. Gibbs-White also did not play despite roughly 75 expected minutes, though he was
benched. Evanilson's 12 points and other returns offset some misses.

Perfect hindsight could improve the saved squad's configuration by 18 points: five from the
goalkeeper, two from a legal outfield change, and eleven from captaining Evanilson instead.
This is an unattainable hindsight upper bound, **not 18 points the system should have known to
recover**. The captain gap is part of that figure, not an additional eleven points.

Scout's archived pre-GW7 predicted lineup also included Semenyo. Therefore adding that source
alone would not have predicted this benching. We need calibrated uncertainty about a predicted
starter, not to pretend that two agreeing lineup graphics guarantee 90 minutes.

### Distribution reliability is a warning

Across the seven frozen recommended squads, the saved nominal 80% player-score intervals
contained **70.5% of 105 outcomes**. The nominal 50% intervals contained 38.1%.
For the seven recommended captains, **none** of the observed scores fell in the saved 80% range:
six were below the lower bound and one above the upper bound.

Seven captains is a small, selected, correlated sample, not seven independent experiments.
Nevertheless this is a serious calibration warning. The existing distribution gate remains
`HOLD_SHADOW`; the point estimates, saved marginal distributions and joint simulator are
different objects, and this result does not by itself identify which modelling component caused
the errors. Mean CRPS was about 2.074 against reference 2.087: only a small apparent improvement.
We should not claim calibrated tails or a state-of-the-art strategy from that result.

Other prospective policy challengers also lack a promotion case: on four scored events, the
zero-risk-weight challenger gained four total points, but its approximate mean-effect interval
included zero; tested continuation and shared-world challengers lost five and eight respectively.
Bad league rank is not permission to cherry-pick the best of these on a tiny holdout.

## What Scout offers and what we should learn

The following describes inspected workflows, not copied proprietary calculations or code.

| Inspected area | Useful capability | Implication for FPLAgent |
| --- | --- | --- |
| [Projected points](https://www.fantasyfootballscout.co.uk/fpl/projected-points) | Multi-week horizons, player filters, head-to-head curves and transfer comparisons | Independently benchmark frozen projections and make our transfer opportunity cost visible. More filters do not themselves improve forecasts. |
| [Player statistics](https://www.fantasyfootballscout.co.uk/fpl/stats) | Comparable price, starts, minutes, returns, ownership and haul tables | Build a concise player evidence dossier from our own licensed/public inputs, showing recent performance against the longer-run baseline. |
| [Defensive contributions](https://www.fantasyfootballscout.co.uk/fpl/defcon) | Per-90 production, threshold hit rates, recent matches and player comparison | Diagnose threshold probability and minutes jointly; average defensive actions alone do not equal expected threshold points. |
| [Market watch](https://www.fantasyfootballscout.co.uk/fpl/market-watch) | Fixture scoring/clean-sheet views and market movements | Surface our existing bookmaker coverage, freshness and authority. Prove incremental value with a matched ablation instead of assuming all odds are useful. |
| [Rotations](https://www.fantasyfootballscout.co.uk/fpl/rotations) | Pairings over configurable horizons, prices and different fixture metrics | Explain why an affordable rotation wins. Keep legal XI, appearance uncertainty, transfer costs and affordability in the evaluation. |
| [Price predictions](https://www.fantasyfootballscout.co.uk/fpl/price-predictions) | Signals about likely rises/falls | Benchmark timestamp-safe price signals; judge them on lost affordability and net points, not team value alone. |
| [Team news](https://www.fantasyfootballscout.co.uk/team-news) | Per-team predicted XI, fixture and editorial update | Match the opponent/venue and team update explicitly. A fresh page fetch is not fresh evidence. |

Scout's across-fixture variation in a projection curve must not be confused with an empirically
calibrated distribution of a player's possible match scores. Nor does a polished tool demonstrate
that its recommendations would outperform ours on identical historical inputs and decisions.

## Changes implemented now

1. **Season review in the web app.** Open the navigation's Season review entry, choose a completed
   gameweek, and inspect actual score, FPL average, realized saved advice, all 15 player outcomes,
   expected/actual minutes, captain contribution, bench and chip context. The screen includes the
   season-level interval warning and explicitly labels hindsight diagnostics. It uses our own
   visual style, accessible dialog controls and a responsive table, not a Scout clone.
2. **Read-only results refresh and CLI.** Results are fetched separately from squad optimisation.
   Opening the review reads the saved cache; Refresh results verifies official outcomes. An error
   retains the last saved review and does not replace the active recommendation.
3. **Automatic prospective scoring.** Normal deadline refreshes now score finalized archived
   decisions and rebuild the prospective scoreboard. Previously later outcomes existed without
   the scoring loop having been advanced. Diagnostic failures are explicit and do not block the
   next legal decision or silently promote a model.
4. **Versioned scoring correctness.** V4 filters post-deadline replays and binds chip results to
   their exact recorded lineup/captain configuration. Missing new-style chip lineage is reported
   as unscorable, not filled using an unrelated ordinary lineup. Older immutable receipts remain.
5. **Short-appearance diagnostics.** The outcome audit now distinguishes playing at all from
   1–59 and 60+ minutes, so a cameo cannot hide behind a favourable appearance Brier score.
6. **Scout source identity/freshness.** The collector uses the canonical team-news page, checks
   opponent and home/away, uses per-team update labels rather than the old article publication
   date, and treats date-only timestamps conservatively. Ads or edits to another club cannot
   renew an unchanged team's semantic observation. More than eleven names cannot be silently
   truncated into an apparently complete XI.

On 21 October the public team-news page still described GW7 fixtures. The revised parser correctly
rejected all twenty as evidence for GW8. This is a successful stale-data guard, not twenty fresh
lineup predictions. A date-only update cannot establish an exact intraday deadline-window age.

## Next implementation priorities, by expected value

### 1. Minutes and captain-distribution calibration

Separate starting, cameo, early substitution and near-full-match probabilities, including
congestion and rotation evidence without overriding players by name. Assess rolling historical
folds and untouched prospective weeks using probability calibration, minutes error, CRPS and
interval coverage. Then run the same legal transfer/XI/captain policy with old/new inputs. Promote
on reliable net-points improvement and acceptable downside, not prettier calibration alone.
First trace why the current frozen captain PMFs so rarely allow one- and two-point returns.

### 2. A matched external benchmark during this subscription month

Where the subscription permits exports for personal analysis, freeze a small, attributable
pre-deadline Scout comparison at the same timestamp, player universe and horizon as ours. Compare
forecast errors and feed comparable inputs through the same legal optimiser, with identical
manager state, transfers, costs and chips. Keep it as evaluation, not a proprietary-model imitation
training set. No retrospective current-page backfill can represent what Scout knew last week.
The benchmark is **not implemented yet** and cannot currently support an external superiority claim.

### 3. Premium-player capital allocation

Test coupled sell-and-reinvest routes when an expensive asset has weak forecast utility over
several weeks. Price must not force a player into the XI; the appropriate comparison is keeping
him versus the best affordable reinvestment after transfer costs and option value. Use historical
replay to distinguish patient mean reversion from keeping an expensive poor role indefinitely.

### 4. An explanatory player dossier

Combine our FPL and Understat evidence: minutes, non-penalty chance quality/creation, set pieces,
defensive-contribution thresholds, opponents and uncertainty. Show short-run observations beside
shrunken longer-run estimates. This should make anomalous role assumptions obvious before the
deadline and make transfer reasoning inspectable, without letting last week's returns dictate it.

### 5. Market signal attribution

Audit which bookmaker observations actually reached production forecasts for each fixture and
how much they changed goal and clean-sheet probabilities. Run timestamp-safe with/without odds
comparisons. Odds already present in the system are not proof of complete coverage, appropriate
weighting, or incremental points value.

### 6. Adaptive future transfers and squad-chip timing

The five-week fixed-roster configuration search is not a fully adaptive future transfer policy.
Continue testing feasible future transfers, cash/price scenarios, information arrival and chip
opportunity cost without pretending known future outcomes. BB/TC operational logic exists;
Wildcard/Free Hit timing remains research-only. This substantial gap must remain visible rather
than being described as a complete season-long optimal policy.

These priorities are experiments, not promises of recovery. Each needs a declared comparison,
time-safe data, uncertainty, an acceptance rule, and a promotion or rejection decision.

## Reproduction, security and limits

```bash
uv run fplagent review-gameweeks --entry-id 2754976
uv run fplagent score-weekly-event --event 7
.venv/bin/pytest -q --ignore-glob='tests/test_llm*'
cd web
npm run lint
npm run build
npm test
# With a local API and Vite available; browser requests are isolated after reading saved data:
node tests/season-review.mjs
```

Saved actual review: `data/model/gameweek_review_v1/2754976/current.json`.
Frozen prospective results: `data/model/prospective_weekly_scoring_v4/event-*/`.
Read-only API: `GET /api/v1/review`; explicit results update: `POST /api/v1/review/refresh`.
The review verifies saved receipt, decision, outcome and source-bundle checksums.

Validation covers official-score reconciliation, hit accounting, finality, owner isolation,
post-deadline exclusion, exact chip configurations, short appearances, stale/wrong fixtures,
conservative dates, failure retention, keyboard dismissal and desktop/mobile layout. It establishes
implementation correctness within those tests, not forecasting skill.

Final checks: **756 non-LLM Python tests passed**, targeted Ruff checks passed, frontend lint/build
and all six frontend tests passed, and the isolated browser review passed on desktop and mobile.
Existing dependency-deprecation and bundle-size warnings remain. QA-only servers were stopped;
start the normal app using the README workflow to inspect the saved review.

The Scout session stays in owner-only `.local/ffscout-cookie.txt`, excluded from git. Do not
paste it into logs, reports or chat. It is a bearer credential and should be removed or replaced
when the review period ends. Subscription access does not automatically permit redistribution,
bulk extraction or model distillation; respect the [site terms](https://www.fantasyfootballscout.co.uk/terms-and-conditions)
and any applicable member/data-provider conditions. Build independent features and calculations.

No GW8 optimisation, forecast-weight change, LLM run, FPL account write, commit or push was made
as part of this audit. The active decision remains the previously published GW7 receipt; it is
not a new recommendation for the coming deadline.

## Implementation follow-up: closing the first gaps

The user subsequently asked us to implement the most valuable Scout-inspired decision tools.
This follow-up goes beyond the original review screen. It still does not claim league-winning
performance, copy Scout's implementation or substitute a proprietary forecast for our own.

### Player scouting is now available

The new **Player scouting** navigation entry provides an A/B comparison and a searchable shortlist
for all **668 registered players**, using official finalized GW1–7 outcomes. It borrows the useful
workflow idea from Scout's stats/DEFCON/fixture tools, implemented independently from our data.

- Filter by position and minimum minutes; sort by chance creation per 90, minutes per fixture or
  defensive-contribution hit rate. The default 300-minute filter reduces obvious tiny-sample
  noise but is not a statistical guarantee. The shortlist is not a transfer ranking.
- Compare the latest three completed events, the **non-overlapping** earlier events and the full
  season. Show actual starts, minutes, goals/xG, assists/xA, FPL points and defensive awards.
- Read defensive-contribution awards from each fixture's actual scoring explanation. Two matches
  with individually sub-threshold activity cannot be incorrectly pooled into a double-GW award.
  Incomplete explanation coverage is unknown, not zero. This also avoids inventing old-season
  rules from a current aggregate count.
- Show official penalty/corner order, news, six scheduled gameweeks, forecast coverage and separate
  probabilities of any minutes, a short appearance and 60+ minutes. Missing forecasts are not zero.
- Show current-price differences without pretending they equal transfer budget: selling value,
  bank, formation, club limits, hits and coupled reinvestment still need the optimiser.
- New blank/haul probabilities and nominal intervals use the historically supported marginal
  model described below. Old forecast dates remain visibly old. Updating the catalogue does not
  pretend to regenerate forecasts or synchronize manager transfers.

Concrete examples visible in the captured data: Bruno's xG+xA/90 is 0.25 over GW5–7 versus 0.85
over GW1–4 and 0.59 for the season. Semenyo scored twice from 0.17 xG in GW5–7. These are reasons
to examine sustainable production and role assumptions, not proof either must be sold. FPL xG/xA
include penalties; the view does not claim these are non-penalty or Understat measurements.

The two-column desktop comparison collapses to a single column on mobile; the frontend skill
guided hierarchy, real loading/error states, keyboard access and readable evidence tables.

### A statistically supported score-shape change

The old saved marginal PMF added a position-level residual to a player's conditional mean. For a
high-xP player, that translates common two-point outcomes upwards, implicitly making an ordinary
blank unusually unlikely. This is distinct from the joint component/residual simulation used to
choose a policy; neither should be assumed correct because the other has a good headline metric.

`score_shape.py` learns a historical played-score histogram separately for each position, with
small count smoothing. Rather than move score values, it changes their relative probabilities:

`P(score=s | plays) ∝ historical_probability(s) × exp(theta × s)`

`theta` is solved so that the conditional mean equals `xP / probability_of_playing`. Explicit
nonappearance mass remains at zero. Therefore the unconditional mean stays equal to the existing
forecast: it does not inflate xP or force a named captain. Supported single-fixture scores span
−10 to 40; unsupported states fall back with a recorded reason. The earlier −4 lower support was
insufficient for an observed historical −5 score, which the validation caught.

The architecture was evaluated on **35,875 single-fixture player-event forecasts** in 2024/25 and
2025/26. Each fold's histogram and residual comparator were fitted only on earlier seasons. The
three highest-xP players in each event form a diagnostic high-forecast cohort (114 rows per season),
not a legally selected squad or actual manager captain. Prior repository research has used these
seasons, so this is time-forward validation, not a newly untouched global competition holdout.

| Test season | All-player CRPS: old → new | Top-three CRPS: old → new | Top-three nominal 80% coverage: old → new |
| --- | ---: | ---: | ---: |
| 2024/25 | 0.96485 → 0.94201 | 3.27677 → 3.05144 | 50.0% → 90.4% |
| 2025/26 | 1.04151 → 1.02581 | 2.85120 → 2.65608 | 48.2% → 88.6% |

CRPS is a probability-forecast error score; lower is better. The approximately 6.9% improvement
for high-xP players is **not** a 6.9% points gain. Blank and haul Brier scores also improved in
both folds. Mean xP drift was below 5×10⁻¹⁵. A four-GW moving-block resampling interval for average
CRPS improvement was positive in each fold: [0.0191, 0.0269] and [0.0118, 0.0197]. These intervals
preserve within-GW dependence and short temporal blocks, but do not represent all research or
season-shift uncertainty. The new 80% ranges are conservative; they are not perfectly calibrated.

**Promotion decision:** activate for the scouting probability display and future weekly frozen
uncertainty records only. Do not change mean forecasts, joint simulator distributions, risk weights,
transfer rankings or captain selection from this test. A legal-policy replay with preserved
fixture/player dependencies remains necessary. Old receipts are never rewritten. The prospective
scoreboard now separates distribution methods, and a mixed-method aggregate cannot pass the
single-method promotion check. This is evidence for a better diagnostic, not a SOTA claim.

### Correctness fixes shipped alongside the tool

1. Exact 0%/100% participation remains exact in the production residual simulator. It previously
   clamped probabilities to 0.001/0.999, allowing a nominally unavailable player to appear in a few
   simulations. Invalid probabilities now fail explicitly. This is a boundary correctness fix,
   not a claim it caused our league rank.
2. CRPS now respects gaps in sparse score distributions and observations outside their support.
   The previous contiguous-support calculation undercounted distance for sparse inputs.
3. The prior results-review implementation had archived GW7 without its bootstrap/fixture
   lineage. This could break the next normal feature rebuild. Review now creates a separate,
   validated catalogue/fixture capture without advancing the production official snapshot pointer.
   GW7's missing lineage was repaired; all 4,551 history rows across GW1–7 were rebuilt successfully
   into a validation-only output, leaving production features and forecasts unchanged.
4. Reobserving identical final outcomes now preserves an existing immutable prospective receipt's
   verified source path/time. Source-lineage repair cannot cause a false receipt collision, and
   changes to computed contents or underlying hashes still fail closed.

### Validation, files and remaining work

The implementation is in `scouting.py`, `score_shape.py` and `ScoutingDialog.tsx`. Saved scouting
evidence is `data/model/scouting_v1/current.json` with 24 checksummed source files. Historical
results are in `data/model/score_shape_v1/replay.json`; the enabled diagnostic artifact is
`data/model/score_shape_v1/marginal-diagnostics.json`. Rebuild it using
`fplagent replay-score-shapes --activate-diagnostics`. Missing/stale optional diagnostics fall
back explicitly and do not block a legal decision.

Run `node tests/scouting.mjs` and `node tests/season-review.mjs` against the local API/frontend for
isolated browser checks: all API requests are intercepted after reading saved data. They test A/B
selection, filters, empty results, stale labels, error retention/retry, responsive layouts and Escape.
No FPL writes or decision-refresh jobs are triggered by these browser tests.

The next highest-value work is **conditional minutes/rotation calibration and a legal-policy test
of improved score distributions**, followed by coupled premium-player sale/reinvestment evaluation.
The independent, timestamp-matched Scout forecast benchmark is still outstanding; we must not
compare current Scout numbers with our four-day-old forecasts and call the difference skill.
No paid-data feed, full adaptive future-transfer solver, or operational WC/FH timing promotion
was smuggled into this batch. No new GW8 recommendation was generated.

### Automation requirement and integration

The manager clarified that the purpose is **automatic decisions between gameweeks**, not more
manual research. The primary output remains one executable plan: transfers or roll, hit cost,
chip/no chip, legal XI, ordered bench and C/VC. The comparison screen is optional explanation;
it is not an extra task for the manager and its creation alone is not evidence of better decisions.

The normal weekly refresh now rebuilds the scouting cache after the final forecasts, reusing its
checksummed official generation and archived finalized outcomes. No extra live requests, separate
button press or Scout subscription is required. Results scoring was already in the same pipeline.
Input observation time is preserved rather than relabelled as the board build time. A failure
to build optional explanations retains the previous board and is recorded in the pipeline receipt;
it does not disable legal decisions or bypass their existing evidence gates. Forecast mutation
during collection and official-source checksum mismatch prevent publication of the new board.

An offline integration run on the real saved 21 October generation built GW8 scouting evidence
for 668 players using all seven finalized events in 0.70 seconds, making no network requests and
leaving the active decision hash unchanged. The extra tests exercise the normal pipeline's
post-forecast ordering, source identity, failure isolation and forecast/source immutability.
This is an automation/correctness improvement, **not a demonstrated points gain**.

Final validation: **778 non-LLM Python tests passed**; targeted Ruff passed. Frontend lint/build,
six frontend tests, and isolated desktop/mobile Playwright scouting/review checks also passed in
this batch. Existing Starlette deprecation and frontend bundle-size warnings remain. Temporary
QA API/frontend processes were stopped; no LLM jobs, FPL account writes or new GW8 decision ran.

Next algorithmic work should feed the same automatic plan: conditional minutes/cameo calibration,
legal-policy distribution replay, coupled premium sale/reinvestment and matched external forecast
validation. Previously rejected calibration experiments must not be blindly re-enabled: the
existing FWD appearance replay lost 0.789 points/event on its historical legal-squad comparison.
Production promotion requires matched time-forward decision evidence, not the desire to force a
particular player or to show a change. Model development is our job; the manager should only have
to act on the final advice, not adjudicate those experiments.

## Follow-up: premium capital, objective, future actions and distributions

The manager parked the minutes-model overhaul: the late Semenyo information is not sufficient
evidence to prioritise that research. This batch follows the requested order **2 → 3 → 4 → 5**.
Existing news/role collection and safety checks remain active. No forecasts were retrained.

### 2. Selling a premium and reinvesting jointly

Added an explicit required-sale constraint to the legal weekly candidate generator. The automatic
allocation experiment now protects alternatives selling either of the two highest-sale-value
outfield holdings. A solver can downgrade that player and upgrade a different position in the same
action. It uses actual selling prices, cash, club/position constraints, free transfers and hits.
The top-two limit is bounded search coverage, not a fitted spending rule or a demand to sell them.

The first run exposed a research-bound limitation: with zero free transfers, its old one-paid-move
limit prevented a two-player reinvestment route. The corrected version explicitly allows up to two
paid moves within its two-transfer cap. Tests cover both zero-FT search coverage and selling value
below market price. A constraint cannot silently disappear when protected role exits are also used.

On the **saved GW7 generation**, both premium targets had legal single-sale and two-move alternatives:

| Protected sale | Joint route found | Hit | Weighted GW7–11 difference versus roll |
| --- | --- | ---: | ---: |
| Bruno Fernandes | Bruno → Saka; Hall → Gabriel | −8 | −2.01 |
| Semenyo | Semenyo → Xhaka; N. Williams → Gabriel | −8 | −4.02 |

These are historical-input simulation examples, **not current GW8 advice**. Nor does a losing
screened route prove every possible sale is inferior. The wider nine-family experiment's winner
was actually a no-transfer alternative configuration, not a premium sale. In independent draws,
its weighted gain was just **+0.03334 discounted points**, with a conservative paired Monte Carlo
95% lower bound of **−0.00240**. It failed the fixed validation criterion: no production promotion.
The comparison uses regenerated scalar configurations, not the complete production configuration
frontier. Monte Carlo precision is not forecast accuracy or historical realised net-point lift.

### 3. Test the objective against frozen real outcomes

`policy_evidence.py` reads policy choices already frozen before each deadline, rather than selecting
using today's news or rebuilding old choices after seeing results. It requires identical events
for all four risk weights and separates original-candidate comparisons from expanded research.
The normal finalized-results feedback loop now returns this aggregate automatically.

| Worst-model coefficient | Paired first-action points versus 0.25, GW4–7 | Changed actions |
| --- | ---: | ---: |
| 0.00 | +4 | 1 |
| 0.10 | 0 | 1 |
| 0.25 | 0 | 0 |
| 0.50 | −3 | 1 |

The four-point advantage comes entirely from GW6. These are four dependent, one-deadline
counterfactuals on the real manager states, **not a continuous alternative season**. Common
transfer safety gates still apply even at zero risk coefficient, and this comparison does not
retune the fixed-roster configuration objective. There is insufficient evidence to change 0.25.
An unrelated expanded-search timeout previously suppressed even completed original-pool risk
comparisons; new receipts separate those completeness flags. Old scored receipts are unchanged.

### 4. Future transfers and chips: consistent future-move gates

The experimental next-deadline planner previously kept a scalar-screened continuation without
separately checking that future move against holding at the exact same future state. Version 2
keeps that comparator for every ordinary root. Free/paid future moves must clear the corresponding
after-cost, model-world and paired-simulation checks; paid moves also receive the existing
paid-hit checks. Failed children fall back to holding, without dropping the current root.

The real-data audit completed **42 future/chip branches**. It rejected a future continuation with
**+1.934 weighted projected gain** but **−1.917 in the raw-component world**, applying the existing
cross-world criterion consistently. This criterion itself remains subject to objective research;
the result does not establish that the rejected football move would have been wrong.

Additional prospective evidence does not support activating the old planners: their frozen first
actions scored **−5 points** (deterministic continuation) and **−8 points** (shared-world continuation)
versus the production ordinary action across GW4–7. This does not measure their full future paths,
and it does not test the new guarded variant. No future-transfer selector or WC/FH timing authority
was promoted. Current BB/TC eligibility is unchanged. Full sequential policy and chip-half validation
remains unfinished; passing legal WC/FH mechanics alone is insufficient.

### 5. Score distributions in legal decisions

Added a research-only mapping from existing residual paths to the historically supported score
atoms, retaining appearance masks and non-tied within-player score order. It uses earlier-season
calibration only, never realised outcomes. Component worlds remain unchanged. Single-fixture
distributions are not applied to double-gameweek totals. Integer quantisation is measured explicitly.

The selected ordinary action stayed unchanged in both existing and altered-shape validation worlds.
This is not a policy gain or proof of calibrated joint tails. Nonlinear mapping and discrete ties
can change covariance despite preserving non-tied ordering. A player does not become a better
expected-points captain simply because their variance increases. Historical joint-dependence,
legal-policy and prospective validation are still needed before replacing production simulation.

### Reproduction and release decision

```bash
FPLAGENT_ACCELERATOR=cpu .venv/bin/python scripts/audit_points_priorities.py \
  --output data/research/points-priorities/NEW-NAME.json
```

This is a developer research command, not a new manager task. Normal refreshes automatically run
the revised allocation/continuation diagnostics and finalized policy-evidence aggregation. The
distribution stress test stays an explicit research tool until it earns production authority.

Canonical receipt: `data/research/points-priorities/20261021-v2.json`, **58.02 seconds**, 10,000
selection paths per model family plus 10,000 independent validation paths per family. Source,
script and engine checksums remained stable. The first audit is retained separately. CPU was used
because an unrelated process occupied roughly 28GB of GPU memory; that process was not disturbed.

**Release: ship search coverage, future-comparator and measurement corrections; retain the existing
live ranking coefficient, candidate authority and joint simulator.** No proven points uplift is
claimed. **789 non-LLM Python tests passed**, targeted Ruff passed; the existing Starlette warning
remains. No active decision/forecast mutation, fresh GW8 recommendation, FPL write, LLM work,
service launch or Git commit occurred. A larger production-matched sequential replay is the next
substantial step, not a task completed by this bounded audit.

## Chronological follow-up: four policy paths across two seasons

Implemented and ran a **stateful historical experiment**, not another isolated comparison on the
actual manager's squad. Four policies begin with the same initial squad and lineup in each season:

1. Residual-world ordinary-transfer baseline.
2. The same policy with extra joint sale/reinvestment candidates for the two highest-selling-value
   outfield holdings. Selling is an option, never a mandatory selection.
3. Next-deadline transfer planning with an exact future hold comparator and after-hit checks.
4. The same ordinary candidate policy with historically fitted score-shape remapping.

All paths carry their own holdings, purchase-price-based selling proceeds, bank, free transfers
and hits into the next deadline. They execute only their current action and replan next week.
The replay scores actual points, legal autosubs and captain fallback; transfer hits are deducted
once. Later actual prices are visible only when that later deadline is reached.

### What makes the comparison meaningful—and what it does not test

The 2024/25 calibration uses 2023/24 data; the 2025/26 calibration uses 2023/24–2024/25. Current
outcome columns never enter the decision rows. Future forecasts are reconstructed from the
origin's out-of-fold prediction and fixture snapshot, rather than reading next week's prediction.
All policies use a five-week horizon, 0.88 decay, up to two transfers/two paid moves and one optimal
scalar candidate per transfer count. Extra premium-sale candidates and future branches extend
that declared search; infeasible constraints are distinct from unresolved solver timeouts.

Every evaluated deadline has 10,000 shared selection paths and 10,000 independent validation
paths. A frozen selection can be rejected to its roll comparator, but the validation draw cannot
pick a different winner. The next-week planner also validates its chosen imagined move against
the same future-state hold before executing the current root action. These are confidence checks
conditional on the simulation model, not confidence that the football forecasts are correct.

The live sampler normally reads today's fixtures and full historical calibration. Explicit
training-prefix and fixture inputs were added so historical experiments cannot inadvertently
use those live defaults. The live defaults themselves have not changed. Historical blank weeks
have zero appearance/points; unsupported double-gameweek sampling is rejected, not silently
approximated. The score-shape transformation records its coverage and finite-draw mean error.

**This is not a full production-matched replay.** It uses one residual world, unit residual scales
and zero terminal FT value in all arms, avoiding today's calibrations that have seen the test
seasons. It excludes the component worlds, chip timing and full configuration search. Historical
actual points follow their season's scoring. These previously inspected seasons are not pristine
holdouts. Four policies across 20 gameweeks are not 80 independent observations: there are only
18 paired post-GW1 decision events. The single-world experiment says nothing about which
cross-world risk coefficient to use.

### Results and release decision

The initial complete run took **201.56 seconds**. Points below include captaincy/autosubs and
subtract all transfer hits; both arms share each season's GW1 score.

| Policy | 2024/25 GW1–10 | Change | 2025/26 GW1–10 | Change |
| --- | ---: | ---: | ---: | ---: |
| Residual-only baseline | 578 | — | 494 | — |
| Extra premium-sale/reinvestment searches | 578 | 0 | 494 | 0 |
| Guarded next-deadline planning | 615 | +37 | 486 | −8 |
| Revised residual score shape | 600 | +22 | 494 | 0 |

The predeclared screen required positive net-point lift in **both** complete ten-gameweek folds.
None passed. A gain in one season is not sufficient grounds to replace the live policy.

Why the future-planning result differs matters. In 2024/25 it spent four hit points versus the
baseline's 28, explaining 24 of its 37-point net advantage; gross football points supplied the
other 13. In 2025/26 it spent 28 versus 32, yet lost eight net points. In GW6 it avoided the
baseline's Schär→Gabriel hit, but the alternative week's net score was eight points lower. The
later paths then diverged. This is not a reason to hard-code Gabriel or prefer hits: it shows that
waiting and saving transfers have an opportunity cost as well as a benefit.

The four-event moving-block intervals for recourse's mean weekly delta were approximately
**+0.44 to +7.44** in 2024/25 and **−3.33 to +1.56** in 2025/26, based on only nine paired events
per fold. Score shape gave approximately **+0.11 to +4.56** and exactly zero respectively. These
small, path-dependent samples are diagnostic, not a reliable season-long uplift estimate.

**Release call: keep all three policy variants in research.** Retain the current production
selector, risk coefficient, simulator and chip authority. Keep the new historical validation
infrastructure and existing automated diagnostics. Premium sale coverage remains useful as an
audit, but no extra points were demonstrated here. Better probability scoring has still not
established a repeatable decision-policy improvement.

Reproduce without touching live recommendations:

```bash
FPLAGENT_ACCELERATOR=cpu .venv/bin/python scripts/replay_sequential_policies.py \
  --output data/research/points-priorities/NEW-SEQUENTIAL-RUN.json
```

The command prints per-arm/event progress, saves source/code/configuration hashes before scoring,
checks that inputs remain unchanged, and refuses to overwrite existing experiment receipts.
The original run is retained as `sequential-20261021-v1.json`. The strengthened receipt format
also hashes rule/position inputs and the CLI entry point, stores effective rules, and records
score-shape coverage; those additions do not change selection logic, seeds or parameters.

Canonical rerun: `data/research/points-priorities/sequential-20261021-v2.json`, **201.63 seconds**,
SHA256 `91f91a2fced08dbac07028ddb2c2e4a09221b4b8f43d82335d3371db6cfaec54`. It exactly reproduced
all 80 arm-event actions, lineups, bank/FT transitions and scores. Input and implementation hashes
remained unchanged. Score remapping covered every requested player-event in these single-fixture
windows: 59,080 transformations across the two draws in 2024/25 and 66,040 in 2025/26, zero skipped.

**800 non-LLM tests passed**, including available GPU checks; targeted Ruff passed. An independent
ledger check verified all 80 records' sale-profit-floor calculations, bank, FT carry, hits, squad
legality and lineup partition. The initial CPU-only test invocation passed 794 with six GPU tests
skipped; the final normal invocation passed all 800. The existing Starlette deprecation warning
remains. No active forecast or decision changed, no fresh GW8 recommendation was generated, and
no FPL account write, LLM work, service launch or commit/push occurred. Both replay runs finished.

## Second continuation: three-world validation and chip-boundary correctness

The four workstreams remain premium sale/reinvestment, the points/risk objective, adaptive
future actions/chips, and score-distribution decisions. The implementation now includes a
larger chronological experiment, plus two independently justified chip-calendar corrections.
This section supersedes the older experiment's *scope*, not its recorded results.

### Historical architecture replay

`scripts/replay_multiworld_policies.py` compares seven separately evolving strategies: baseline,
premium reinvestment, risk coefficients 0/0.10/0.50 against the baseline 0.25, guarded future
transfers, and residual score-shape remapping. All start with the same initial squad. Each then
owns its purchase prices, sale-profit floors, cash, free transfers, hits and legal lineup.
Only today's action is executed; tomorrow's action is reconsidered at the next origin.

Important improvements over the residual-only experiment:

- The actual residual, raw-component and anchored-component samplers are used. Raw and anchored
  worlds share draws, and validation preserves that covariance rather than treating them as
  independent samples.
- Empirical minutes, goals, cards, saves, multi-fixture participation and residual/shape pools
  are restricted to earlier seasons. The existing minute classifier and team-goal model are
  recreated on historical prefixes; this is not a new minutes-model or LLM research programme.
- Future opponents use the dated schedule and origin team ratings. No future-event feature row
  or actual future result is used to construct a decision scenario.
- Saved-FT values are nonzero, fitted from earlier-season opportunity observations, not copied
  from the final all-season selected curve. The small calibration sample remains a limitation.
- Every proposed roster receives exact legal XI/bench/C/VC configuration search. The tested
  risk coefficient applies at **both** configuration and route selection. Role/paid-hit safety
  gates are unchanged; risk zero does not mean removing all safety constraints.
- Each independent simulation family has 10,000 selection and 10,000 new validation paths.
  Validation can reject the frozen choice, not choose a different validation winner. A rejected
  configuration restores the original decision as a transaction.
- Future moves must beat a same-root future hold after costs. Only the root is executed;
  projected future prices/news are not treated as known.
- Frozen outcomes score CRPS, interval coverage, tail breaches, haul Brier score and bias for
  each position, the baseline captain and baseline bench. These labels enter only after choices
  have been frozen, not during candidate construction or selection.

This is **not a complete production-matched backtest**. It has bounded two-transfer roster and
future-child searches, unit residual scales, fixed component-model inclusion, no archived live
market/lineup consensus, and no prior defensive-contribution sample before 2025/26. Actual
historical points include their season's scoring regime. These are already-inspected development
seasons, not pristine holdouts. Better Monte Carlo integration is not evidence of better forecasts.

An explicit archive preflight also exposed **missing same-event metadata for 2025/26 GW8**.
The existing features use lagged prices when deadline quotes are absent. The new world builder
uses the earlier GW7 dated fixture archive and stops rating updates at that archive's observation
time; it does not fill the gap from future outcomes. The receipt records snapshot age, missing
origin metadata and price coverage. Results therefore cannot establish exact real-world
execution-price feasibility or justify a claim of complete historical/live parity.

### Chip correctness: enforce expiry and remaining capacity

Two genuine decision-process defects were reproduced before being fixed:

1. The joint calendar could value first-half chips against a forecast after GW19. Both ordinary
   retention and forced-current-chip calendars now restrict opportunities to the current half.
   Terminal chip value is explicitly zero at GW19/GW38, including with older binned calibrations.
2. Beyond the visible horizon, separate chip priors were added without limiting how many chips
   could actually be played. With one unseen GW remaining, a regression reproduced a value of
   **14.67** despite at most one usable chip being worth **7.00**. The calendar now caps retained
   uses by the number of unseen deadlines, respecting one chip per gameweek there too.

These are legal/opportunity-accounting corrections, not a claim of measured season points lift.
They are active in normal weekly decisions. Tests cover both halves, post-expiry forecast
poisoning, exclusion of the chip played now, and equality with exhaustive small-calendar search.
They do not grant Wildcard/Free Hit timing authority or change the underlying retained-value fit.

### Exact chip opportunity audit runs automatically

Every normal weekly decision now includes `diagnostics.exact_chip_opportunities`. It compares
future proxies with shared-path scoring: BB is all 15 players' score minus normal scoring with
legal autosubs; TC is the extra captain copy with vice-captain fallback. Paired component-world
covariance is retained in sampling-error estimates. This requires no new external requests or
manual user workflow.

Saved-generation verification: `data/research/points-priorities/20261021-v4-chip-capacity.json`,
**59.40 seconds**, input and implementation hashes stable. This is the archived GW7 generation,
**not fresh GW8 advice**. Its future BB proxy exceeded exact simulated uplift by approximately
0.67, 1.00, 1.45, 1.60 and 1.71 points over GW7–11; TC fallback added roughly 0.26–0.35 points.
The saved-generation capital challenger still failed independent validation: weighted gain
+0.03334, conservative Monte Carlo lower bound −0.00240. The guarded plan and shape sensitivity
did not change its ordinary first action.

The exact chip comparison has **no timing authority**. Replacing future proxies in the deployed
selector without refitting matching retained-value paths would silently mix two definitions.
WC/FH retained value and full-season joint timing remain unvalidated, not hidden assumptions.
The production risk coefficient, forecast weights and current published recommendation are
unchanged by these research additions.

The risk objective is disagreement between **model worlds**, not a blanket penalty for players
who can haul. It combines weighted-average regret with worst-world regret. Changing a player's
variance while keeping their mean and appearance paths fixed does not, by itself, raise expected
linear FPL points. The useful nonlinearities are legal autosubs, captain fallback, chip effects,
transfer costs and affordability. Tail calibration must therefore be tested alongside legal
decisions, not sold as an automatic points advantage.

Shared configuration caches are now scoped by simulation-array identity, world ordering, horizon
and rules. Identical worlds can reuse frontiers across the risk grid, but a new generation cannot
silently reuse an old world's preferred captain. Cached worlds must remain immutable. Regression
tests switch the strongest player between two worlds and require the captain selection to follow.

### Completed three-world results and release decisions

Canonical receipt: `data/research/points-priorities/multiworld-20261021-v4.json`.
Completed in **786.18 seconds (13m06s)** with all input/code hashes unchanged during the run.
SHA256: `6492b0fb57617a8217249275a94f94a6f1b4e564e5f44df181eba974714c9a48`.
The failed/partial earlier receipts remain preserved and are not counted as completed folds.
The 2024/25 fold's 70 core action/state/lineup/score records exactly reproduced the earlier
partial run after archive preflight and calendar/cache infrastructure corrections.

These are GW1–10 **net points after hits**, not an entire season or fresh live advice:

| Strategy | 2024/25 net points | Delta | 2025/26 net points | Delta |
| --- | ---: | ---: | ---: | ---: |
| Three-world control, risk 0.25 | 602 | — | 496 | — |
| Protected premium sale/reinvestment | 602 | 0 | 496 | 0 |
| Risk 0 | 587 | −15 | 495 | −1 |
| Risk 0.10 | 587 | −15 | 491 | −5 |
| Risk 0.50 | 593 | −9 | 496 | 0 |
| Guarded future transfers | 638 | +36 | 495 | −1 |
| Residual score-shape remapping | 623 | +21 | 496 | 0 |

All six variants fail the **predeclared positive-in-both-folds necessary screen**. In particular,
recourse saved 12 hit points in 2024/25 and eight in 2025/26, but the latter still finished one
net point behind. Saving transfers or avoiding hits is not itself the objective. The
short-window moving-block intervals for recourse and score-shape differences include zero; they do not
establish reliable positive effect sizes. We did not retune the hypotheses after seeing scores.

The earlier residual-only 2025/26 results **0, −8, 0** remain valid for that experiment. The
new results **0, −1, 0** use different controls: three simulation families, exact configurations
and nonzero prefix-fitted saved-transfer values. They are not a retroactive correction, and the
two controls' absolute totals must not be used to claim a live points improvement.

Distribution scoring covered **5,908 + 6,604 player-events**, after all decisions were frozen.
Shape remapping improved all-player mean CRPS from 0.679912→0.665146 and
0.676052→0.669915, but baseline-captain CRPS worsened from **2.578462→3.223300** and
**1.708393→2.001140** (only nine captain observations per fold). Bench-player CRPS improved
slightly. This is precisely why broad calibration averages are not enough to promote a decision
model: they are dominated by many low-appearance players, and are not joint squad-tail tests.
Discrete 80% intervals cover roughly 93–94% overall; point masses can cause overcoverage,
so neither that coverage nor these small captain samples establish calibrated tails.

The concluded release is `points_first_release_20261021_v3`, enforced in `policy_release.py`:

- **Promote correctness:** half-expiry and remaining-calendar-capacity chip fixes. Harden shared
  configuration caches against reuse with another world generation. These do not claim measured
  points gains, change forecast weights, or bypass any live evidence gate.
- **Retain current selector:** risk 0.25, existing simulation policy and current calibrated BB/TC
  authority. No extra premium-sale search authority, new continuation policy or score-shape
  simulator is promoted on these results.
- **Collect automatically:** capital-release alternatives, matched first-action risk/continuation
  outcomes, and the new exact BB/TC opportunity diagnostic in normal weekly decisions. Existing
  marginal score-PMF reporting is unaffected. Research commands are reproducible engineering
  checks, not a manual task the manager must run each gameweek.
- **Reject new timing authority:** exact chip measurements cannot silently replace proxy-trained
  retained values. WC/FH timing still needs a matched, recent-rule, full-inventory sequential
  evaluation. Legal chip mechanics are implemented; optimal eight-chip season timing is not proven.

This completes the implementation, validation and deployment-decision pass for priorities
**2, 3, 4 and 5**. It does not mean those research areas are permanently solved. The next useful
research is a separately preregistered, more completely production-matched sequential comparison
with stronger historical quote/lineup coverage and matched exact-chip retention fits—not more
post-hoc tuning on these same two opening windows. Prospective evidence continues accumulating
through the existing automated feedback loop.

Final verification: **854 non-LLM tests passed** (one existing Starlette deprecation warning),
targeted Ruff and edited-file whitespace checks passed. An independent calculation verified all
**140 strategy/gameweek records** for sale-profit floors, cash, FTs, hits, roster/formation/club
constraints, captain/vice and score arithmetic under the archived-price assumptions. All runs
completed. No services, live refresh, FPL account writes, LLM execution or commits were performed.
The published GW7 receipt remains SHA256
`a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
New code takes effect on the next process/run; archived advice is not silently rewritten.

## Follow-up: challenge the benchmark and the validation gates

The earlier pass must not be read as proof that the incumbent is good enough. It tested
bounded variants, not the entire space of possible improvements. In particular:

- Historical search returned one scalar-optimal roster per transfer count, with at most two
  transfers. That is smaller than the live search and can hide a better portfolio.
- A zero risk coefficient did not remove the route or configuration vetoes. It was not a
  clean maximum-expected-points comparator. Configuration validation could reject a positive
  weighted gain because one world lost more than 0.05 points. Paid routes also required a
  55% chance of beating roll, which is not equivalent to maximizing expected points.
- Residual and anchored-component worlds share the same mean xP. Their combined 95% weight
  is not three independent opinions agreeing. More samples reduce integration error; they
  do not repair a biased forecast.
- Independently checking 10,752 legal formation/bench/appearance combinations found no
  autosub mismatch. Saved-GW7 mean checks found no gross scale or DNP-point error. These
  are useful correctness checks, not proof of accurate forecasts or optimal policy.

### What Scout teaches us, and what remains unknown

The [projection workspace](https://www.fantasyfootballscout.co.uk/fpl/projected-points)
organizes decisions around gameweek windows, fixture swings, set pieces, captaincy,
price brackets and incremental transfer value. Its budget-enabler view supports looking
at the squad's funding trade-offs, not just sorting expensive players by form. Its
consistency view describes variation across a projection curve, which must not be
confused with a match-outcome predictive distribution. These are observable product
mechanics, not evidence that we have recovered Scout's private prediction algorithm.

Scout's [team-rating page](https://www.fantasyfootballscout.co.uk/fpl/rate-my-team)
explicitly says its ratings use RMT projected points. A screenshot rating, editorial
Scout Picks, the quantitative projections, and an individual expert's transfers are
different comparators. We must identify which one is being evaluated.

Our interpretation and independent implementation priorities:

| Decision question | Existing FPLAgent capability | Useful next test |
| --- | --- | --- |
| Is a good player entering a better run? | Dated team-strength/fixture forecasts and rolling player features | Compare identical forward windows; separate fixture uplift from underlying player-rate changes |
| Does the player have a repeatable route to points? | xG/xA history, set-piece orders, component model | Audit discrepancies by attacking role and sample size; don't multiply a set-piece boost into a model already using that feature |
| Is a premium worth its budget? | Legal capital-release/reinvestment alternatives | Widen the historical roster pool; compare complete affordable pairs, not xP/price ratios alone |
| Who should start/captain? | Exact legal simulation XI, autosubs and C/VC fallback | Compare frozen forecasts on the same 15; distinguish a forecast error from a selector error |
| Are we transferring too cautiously? | Cross-world regret and several extra vetoes | Isolate the configuration veto; also test a mean-points policy retaining legal and incoming-role checks |
| Does Scout actually forecast better? | Previously no timestamp-matched member comparison | Private pre-deadline paired captures and finalized-outcome scoring, now implemented |

We do not know Scout's exact rate priors, training data, coefficients, human overrides or
retraining cadence from the exposed page. No claim is made to have reverse-engineered
those internals. Reputation is a reason to test a strong external comparator, not to
treat every difference as truth. Ownership is not a points bonus for our stated objective.

Concrete editorial cross-check: the [21 October GW8 early Scout Picks](https://www.fantasyfootballscout.co.uk/2026/10/21/fpl-gameweek-8-early-scout-picks-arsenal-trio-two-double-ups)
use a one-week objective, an £83m starting-XI budget and £100m squad budget. Their reasoning
combines confirmed fitness, midweek rest, underlying chance creation, penalties, opponent
weakness, clean-sheet prospects and defensive-contribution frequency. They distinguish
Thiago's booking risk as a multi-week purchase from his one-week suitability, and separate
Brighton players being reasonable starters in an existing squad from earning a place in a
freshly cherry-picked XI. They also flag overperforming clean sheets rather than simply
extrapolating recent returns. These are good methodological checks, not their private RMT
formula. Our benchmark must not pit that one-week, no-hit selection against a five-week
transfer policy and call the difference a forecasting win.

Independent hypotheses arising from that editorial comparison: carry accumulated-card
suspension risk into future availability, condition defensive-contribution threshold rates
on minutes, and distinguish changes in opportunity quality from short-term conversion luck.
Their value still needs dated feature availability and legal-policy evaluation. No new
coefficient, player override or paid-feed dependency is installed merely from this article.

### Private, automated external comparison

Implemented `scout_benchmark.py`, `scripts/capture_scout_benchmark.py`, and the normal weekly
pipeline hook. Authorized session access is optional. No CAPTCHA bypass, credential logging,
full-page persistence, paid dataset redistribution or training on Scout predictions.
The existing ignored `.local/ffscout-cookie.txt` must be owner-readable only. Captures are
immutable, owner-only files under ignored `.local/scout-benchmarks/`.

The fixed cohort is the held 15 plus the top two by position from each source over the same
unweighted forward window, bounded to 40 players and five events. Element ID AND stable
player code, season, club and position must agree. Missing xP is not zero. Price mismatch,
local input/build times older than six hours, future timestamps, mixed generations, or
post-deadline capture prevent a contemporaneous comparison. Scout's model publication
time is unknown: an observation time must never be presented as its model build time.

When eligible, both forecasts choose a legal XI/C/VC on exactly the same 15 using a simple
scalar-mean control. This is deliberately labelled **not Scout's actual recommendation**,
and not our full simulation optimizer: it isolates differences in means without inventing
Scout per-gameweek availability from its aggregate minutes column. Final official outcomes
then score MAE/bias/RMSE and legal lineup points, including autosubs and captain fallback.
Selected-cohort error is not an unbiased full-universe error. Repeated captures are separate
snapshots, not independent gameweeks and must not be pooled as such. There is no promotion
from a disagreement alone. Archive scoring continues even after the paid session is removed.

The first actual capture, 21 October at 20:45:32 UTC, covers 25 players/GW8–11. It correctly
reports **unmatched**: local forecasts are from 17 October and four player prices differ.
Receipt: `.local/scout-benchmarks/gw08-aece99be7ca6fbb9ecf7.json`, SHA256
`aece99be7ca6fbb9ecf775fd6279d7c8732ed3fcff9c61beeb5ef615d712d3bc`.
This cannot establish Scout superiority or generate fresh GW8 advice. In particular,
a zero Scout projection versus an older positive forecast is a news/freshness investigation,
not automatically a forecast-model defect. The next normal weekly refresh captures both
sources near the same time; no manual Scout analysis is required each week.

### Registered gate/search experiment

`gate_search_replay.py` and `scripts/replay_gate_search.py` freeze five arms before observing
their results: incumbent, remove configuration world-veto only, wider incumbent, mean-points
policy, and wider mean-points policy. The wider pool literally includes the narrow pool,
then four scalar rosters per transfer count plus protected exits for the two most expensive
outfield holdings. It is still bounded to two transfers/two paid transfers, not exhaustive.

The mean policy uses risk zero at configuration and route selection, and a positive weighted
paired Monte Carlo lower bound after transfer costs and the shared terminal FT value.
It removes world-loss and win-frequency vetoes, but never legal/affordability/incoming-role
checks. The configuration-only arm retains production risk and route gates, isolating that
one restriction. Selection choices are frozen before fresh validation paths; validation can
reject to the already-defined fallback, not choose its own winning roster.

The same two GW1–10 development folds, prefix-only models and independent portfolio ledgers
are used. Passing the positive-both-folds screen is necessary, not sufficient for promotion;
these previously inspected windows are not pristine confirmation. Source/code hashes and
the registered experiment definition are saved before the full run. No live advice, forecast
or FPL account is changed by the experiment. Results and deployment decision follow below.

### Completed follow-up results and release decision

Receipt `data/research/points-priorities/gate-search-20261021-v1.json` completed in
**1,034.40 seconds (17m14s)** with stable input/code hashes. SHA256:
`399b2a3bc63b8791a921967d2e4c16ac4305334929d090a04192ed9d12b12a9b`.
Registered-definition SHA256:
`afed18e74dad69227fb68b5d90ab08d10e4e3d2966c07b6f68371c5ecd74535e`.

| Carried policy, realized GW1–10 points after hits | 2024/25 | 2025/26 |
| --- | ---: | ---: |
| Narrow control | 602 | 496 |
| Remove configuration world-veto only | 602 (0) | 496 (0) |
| Wider pool, incumbent gates/risk | 628 (+26) | 491 (−5) |
| Narrow pool, mean-points objective/gates | 614 (+12) | 493 (−3) |
| Wider pool, mean-points objective/gates | 614 (+12) | 475 (−21) |

The baseline exactly reproduces the earlier experiment. Wider incumbent search paid 8/20
hit-points versus control 12/24, while mean-points arms paid 20/32. More aggressive selection
did not give robust improvement. Wider search did improve one season materially; it is false
to conclude that every explored alternative was equivalent to the incumbent. It is also false
to ignore its latest-season loss. All four replacements fail the prespecified positive-both
screen. The wider-pool mean-policy loss of 21 in the recent season is particularly relevant
to deploying loosened gates with the already wider live search.

Nine post-initialization event differences per fold are a small, dependent sample. The wider
incumbent's block-resampled mean-delta interval is +1.56 to +4.33 points/event in 2024/25 but
−5.00 to +3.56 in 2025/26. These are development diagnostics, not a pristine confirmation or
forecast-confidence interval. A tiny latest-season loss is not proof an idea can never work;
we retain it as research rather than changing thresholds until it passes.

`scripts/verify_policy_ledger.py` independently checked all **100 arm-events** for cash,
sale-profit rounding, roster transitions, FT accrual, hits, legal formations, substitutions,
captain fallback and score arithmetic. It uses neither the production action transitions nor
the production autosub scorer. The same checker also reproduced all 140 earlier arm-events.
No bookkeeping/scoring discrepancy was found under the archive's stated price assumptions.

`scripts/audit_search_coverage.py` checked the first wider-pool roster divergence in each
season (2024/25 GW3, 2025/26 GW4). Both selected rosters exist in the plain four-alternatives
search without forced premium sales. This is evidence of candidate coverage, **not** a
blanket premium-selling edge, and does not attribute every subsequent point. Live production
already defaults to four alternatives per transfer count and a larger transfer-count limit;
the historical +26 is not a newly installed +26-point benefit for the live app.

Release `points_first_release_20261021_v4` therefore:

- Keeps existing live risk/route/configuration gates; rejects the tested replacements.
- Activates private Scout comparison capture and prospective measurement, **not** forecast,
  training, transfer or chip authority from Scout. Runtime guards prohibit accidental promotion.
- Retains the stronger research harness and independent ledger/coverage tools. Future policy
  experiments should not rely solely on the old three-candidate historical control.
- Does not treat these tests as a reason to stop improving forecast quality. All policies here
  still largely share our xP. Their disagreement cannot establish whether Scout's means,
  team environment or role assumptions are better.

One concrete live investigation was completed without overwriting our artifacts: a read-only
check of the [official FPL bootstrap](https://fantasy.premierleague.com/api/bootstrap-static/)
on 21 October reports Semenyo injured, 0% next-round availability, with the news added
17 October at 17:30:09 UTC. Our saved forecast inputs are from that morning at 07:53 UTC.
This explains why a zero Scout projection versus that old positive forecast is a freshness
warning. It does not prove Scout's underlying model is better. A fresh GW8 run must incorporate
the later official evidence; no new GW8 recommendation was generated in this research pass.

Next highest-value step: use the next normal fresh decision run's contemporaneous capture to
separate availability, player attacking/creative rates, and team fixture-environment differences;
then evaluate targeted forecast changes on dated historical inputs and frozen future outcomes.
Do not just increase simulations around the same possibly biased means, blend Scout on
reputation, or copy its one-week editorial squad into a multi-week transfer policy. Current
prospective scoring covers the capture's first event; forward-window rows are preserved for
comparison, not yet claimed as a scored multi-week Scout policy benchmark.

Final verification: **883 non-LLM tests passed** in 34.24s (one pre-existing Starlette
deprecation warning). Targeted Ruff and edited-file whitespace checks passed. Optional
comparison failure, archive persistence/reuse, immutable capture checks and rejection of
accidental authority are covered. All research/test processes completed. Published GW7
receipt remains SHA256 `a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
No FPL writes, LLM execution, live decision refresh, service restart or commit/push.
