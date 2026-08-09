# FPLAgent points-first season roadmap

**Prepared:** 6 August 2026 · reconfirmed 7 August 2026  
**Product objective:** maximise Lewis's FPL points over the 2026/27 season through better
point-in-time forecasts and better legal decisions. Conversational quality and visual polish are
supporting capabilities; neither is the optimisation target.

**Current product decision (8 August):** the final bounded V9 LoRA completed and was rejected by the
locked promotion gate. It improved exact grounded routing and real screenshot extraction, but did
not improve strict response contracts or clear legacy, safety, qualitative and held-out screenshot
requirements. App defaults remain unchanged and further LLM work is parked. Guarded chat is a
supporting interface while forecast, data freshness and decision quality receive the engineering
budget. The user-facing priority board and full-season behaviour are maintained in
[`docs/points-first-roadmap.md`](../docs/points-first-roadmap.md).

## North star and accountability

The app cannot promise football outcomes. It can promise that every decision uses the freshest
available evidence, beats declared alternatives in honest tests, exposes uncertainty and is
reproducible. The scorecard therefore has four levels:

1. **Forecast quality:** participation Brier/log loss, minutes calibration, expected-points error,
   distribution score, 5+/10+ return ranking and top-shortlist yield on forward seasons.
2. **Decision quality:** legal-policy replay against roll, incumbent, form and simple expected-points
   baselines; paired scenario regret; captain, bench and transfer stability under forecast error.
3. **Operational quality:** zero illegal recommendations, zero silent stale-data decisions, a complete
   pre-deadline receipt and a successful shadow run at every deadline.
4. **Season outcome:** cumulative FPL points and overall rank, accompanied by frozen counterfactuals
   so luck is not confused with a good or bad model change.

No model is promoted for novelty, training fit or one lucky gameweek. It must improve a frozen
forward test or a prospective receipt stream without breaking calibration, legality or freshness.

## What already works

- A leakage-safe historical/current feature layer passes the checked data-quality gates.
- The opponent-adjusted fixture model passed its preregistered champion/challenger gate.
- The direct position-specific forecast beats five-match form on the main forward tests.
- The component simulator provides match-level correlation, current-rule scoring, exact autosubs
  and captaincy.
- The robust GW1 search, horizon audit and bench/formation counterfactuals already generate and
  interrogate legal full-squad candidates rather than choosing players independently.
- The promoted GW1 proposal has an evidence receipt and an explicit deadline rerun rule.

The next phase should extend these foundations into a reliable weekly decision system, not replace
them with an unvalidated monolithic model.

## Priority 0 — win the information race before GW1

These are blocking tasks before trusting the opening squad.

### 0.1 Immutable live collection and freshness orchestration

- Persist official API, fixture, player, price and authenticated manager snapshots at T-72h, T-24h,
  T-6h, T-60m and T-10m, plus immediately after material news.
- Give every input `observed_at`, source, checksum, TTL and completeness state.
- Add one idempotent `refresh -> validate -> forecast -> search -> synthesise -> publish` command.
- Fail closed when availability, fixtures, price or manager state is stale; retain a dated cached
  proposal only as a clearly marked fallback.
- Store the exact input/model/rule hashes in the decision receipt rendered by both the page and chat.

**Done when:** a complete shadow run can be reconstructed byte-for-byte and the UI cannot describe
old evidence as current.

### 0.2 Deadline-safe market fixture probabilities

The first independent team-rate challenger is implemented and passes the frozen fixture-forecast
gate, but it does **not** pass the continuous transfer-policy gate. Football-Data's explicitly
pre-closing `AvgH/AvgD/AvgA` and over/under prices are de-vigged and converted into home/away Poisson
goal rates. Raw season files, hashes, mapped FPL fixture IDs and information-policy receipts are
retained.

- Across the frozen 2023/24–2025/26 fixture set, Poisson deviance improves from 1.0892 to 1.0514,
  goal MAE from 0.9331 to 0.9179 and clean-sheet Brier from 0.1702 to 0.1678.
- A legal independent-gameweek selection replay chooses the blend weight on 2024/25 only. The
  untouched 2025/26 result is +5.00 realised points/GW versus direct xP (95% interval +1.34 to
  +8.66) and +2.18/GW versus an internal-component control at the identical weight.
- The subsequent continuous replay starts from a legal GW1 squad and carries exact bank, purchase
  prices, selling values, free transfers and hits through all 38 deadlines. A 25% market weight won
  the 2024/25 validation path by 145 net points, then lost the untouched 2025/26 path by two points
  (`2005` versus `2007`); its four-GW moving-block interval was -3.18 to +2.87 points/GW. The
  market signal is therefore **rejected for weekly transfer authority**.
- GW1 remains a narrower shadow hypothesis: the full-pool replay improved realised GW1 points at
  the strong research weight in both available seasons, but two opening weeks are not enough to
  promote it without current complete odds and the full robust funnel.
- The live `fixtures.csv` readiness contract is now event-aware across a configurable horizon. It
  checks its page upload timestamp against every FPL deadline and requires all official event
  fixtures plus complete 1X2 and totals prices before that event enters a paired match-world shadow.
  Partial snapshots are archived but cannot alter a decision. On 8 August it correctly reports zero
  of ten GW1 fixtures because the Premier League batch is not published yet.
- The same market-derived fixture rates now re-score the existing GW1 component-tournament universe
  and every in-season weekly action using paired random streams. Candidate/action rank movement and
  value shifts are recorded with exact artifact hashes, but market scenarios remain excluded from
  production weights.

**Next action:** operate the collector at every refresh and scheduled deadline window. When all ten
GW1 fixtures arrive, the exact batch will automatically invalidate the cached run and activate the
paired shadow. Do not use it for weekly transfer authority. Missing, partial, stale or mismatched
prices leave the incumbent unchanged. See
[`docs/market-evidence-subsystem.md`](../docs/market-evidence-subsystem.md).

### 0.3 Preseason minutes and availability

Minutes remain important before GW1, but the completed decision-opportunity and policy replays no
longer justify treating a generic appearance recalibration as the highest-value model change. The
previous FWD calibration was retired after costing 0.789 points/GW. Revisit participation only with
new player-role evidence and position-specific calibration rather than another blanket correction.

- Predict DNP, 1-59, 60-89 and 90-minute probabilities, conditional minute quantiles and a role
  confidence flag.
- Expand the audit universe to value candidates and all plausible squad selections, not only the
  incumbent shortlist.
- Add point-in-time injury/suspension status, preseason starts, substitution patterns, manager/role
  continuity, congestion and timestamped team-news claims.
- Build explicit returning-player, promoted-club, new-signing and academy priors with wider
  epistemic uncertainty.
- Promote per position only when Brier and log loss improve on both forward seasons and squad/captain
  replay does not regress.

**Done when:** intended starters and bench cover have calibrated appearance probabilities and no
selection depends on an unsupported hard “nailed” label.

### 0.4 Final GW1 tournament

After the final data refresh, rerun the complete funnel rather than editing the squad by hand:

- direct and component forecasts;
- global legal candidate search;
- 3/5/8-gameweek and future-decay scenarios;
- open-transfer, roll, forced-bank and fixed-squad routes;
- appearance, promoted-team, goal-rate and clean-sheet stress;
- lean-bench and 3/4/5-defender counterfactuals;
- all-15 lineup selection followed by captain and vice-captain; and
- an independent simulation seed for the final holdout.

**Candidate-coverage finding, 7 August:** the exhaustive one-swap audit showed that a legal
Mukiele-to-Senesi neighbour could rank strongly over a fixed eight-week horizon while missing the
10,000-squad five-week discovery cut. Forced equal replay ranked it second in the horizon family
but 27th in the five-week robustness family, and combined synthesis rejected it (1.498 regret
versus 0.906). Keep production unchanged. The horizon audit now carries a protected 32-squad
neighbour portfolio across the top eight robust seeds so this class of candidate is measured
automatically without allowing a fixed-squad result to bypass transfer optionality or cross-family
stress. A live generation check retained the exact Senesi neighbour at position 26; it enters
production evidence only when the complete deadline funnel is next rebuilt.

The incumbent survives only if it remains the evidence-weighted leader and its edge is stable. A
tiny central-mean advantage that disappears under plausible model error is not enough.

## Priority 1 — turn the GW1 picker into a weekly decision engine

The current rules audit is explicit: opening-squad legality works, but the engine is not yet a full
season agent. Implement a versioned FPL state machine containing:

- 15-player squad, starting XI, bench order, captain and vice-captain;
- bank, purchase price, exact sell value and price changes;
- free-transfer earning/carry/use and points hits;
- chip inventory, first/second-half availability and expiry;
- wildcard/free-hit temporary state and squad restoration;
- autosubs and formation legality; and
- deadline, live, provisional-score and finalised-event states.

For every gameweek the optimiser must generate at least these comparable action bundles:

1. roll;
2. best one-free-transfer route;
3. best multi-free-transfer route when available;
4. hit routes only when their after-cost horizon value is credible;
5. chip and no-chip routes when a chip is eligible; and
6. the best XI, bench order, captain and vice-captain after each squad route.

Evaluate bundles over correlated scenarios, not just summed point estimates. Re-plan every deadline;
do not pretend an eight-week route is a fixed future script. Publish expected gain versus roll,
downside, required assumptions, route stability and the strongest rejected alternative.

### Price-change execution timing progress, 8 August

The public 15-minute FPL market state is now an append-only prospective evidence stream. A nightly
outcome builder brackets UK midnight, records the actual price move and calibrates rise/fall
thresholds independently. The selected weekly action receives an exact affordability stress using
its post-transfer bank, every incoming rise and the purchase-price-aware selling loss for every
outgoing fall. It is lineage-bound but operationally `wait` with zero authority.

An exploratory weekly-snapshot price model was rejected on information timing before it could be
considered for promotion. Across the available 2023/24–2025/26 data the next weekly label arrived a
median 3.6–5.1 days after the decision deadline, so it includes post-deadline transfer behaviour and
cannot answer tonight's move-now question. Prospective calibration requires 14 nights, 30 calls per
direction and 75% precision in both directions; a later move-now-versus-wait replay must still win
on net points rather than team value. Full contract:
[`docs/early-transfer-policy.md`](../docs/early-transfer-policy.md).

## Priority 2 — add predictive signal only through champion/challenger tests

### 2.1 Match and team strength

- Keep the promoted opponent/venue hierarchy as champion.
- Test properly licensed or research-safe market goal/clean-sheet probabilities, public Elo and
  richer point-in-time team xG as challengers.
- Improve promoted-team priors with prior-league strength, squad continuity and transfer turnover.
- Model rest, congestion, European competition and manager changes with time-aware features.

**Market progress, 8 August:** the research-safe pre-closing market challenger passes the frozen
fixture metrics and independent legal selection replay described in Priority 0.2. Its continuous
ordinary-transfer replay did not generalise: validation selected 25%, but the frozen test finished
two net points behind incumbent and its block interval crossed zero. It is rejected for weekly
transfer use. Event-aware live collection and paired GW1/weekly match-world evaluation are now
wired into the deadline pipelines, still with zero decision authority pending complete current data
and prospective validation.

### 2.2 Player role and event rates

- Maintain per-position goal, assist, clean-sheet, save, card, defensive-contribution and bonus
  component models conditional on minutes.
- Add stable set-piece/penalty role, share-of-team events, on-pitch position and substitution role
  when their observation time is defensible.
- Complete the 2026/27 BPS implementation where event data permits; keep goalkeeper and missing
  Opta components explicitly probabilistic rather than inventing precision.
- Calibrate return probabilities and score quantiles, not only mean xP.

**Return-ordering progress, 7 August:** the first distribution-aware challenger is implemented.
It predicts under-five, 5–9 return and 10+ haul probabilities with position-specific,
season-forward XGBoost models, prior-season temperature calibration and no test-season labels. A
25% blend was selected solely on the continuous 2024/25 transfer path: +99 net points with three
hits rather than six. The untouched 2025/26 continuous path gained 94 net points (+2.474/GW), and
independent legal squad/XI/bench/captain replay gained 41, 94 and 60 points across 2023/24,
2024/25 and 2025/26 respectively. However, the frozen four-GW block interval is -0.211 to
+5.132 points/GW, narrowly missing the predeclared -0.10 downside bound. The candidate is therefore
`HOLD_SHADOW`: it cannot alter live forecasts or decisions. Freeze a current-season shadow score
at each deadline and require prospective stability before promotion; do not relax the gate after
seeing the result.

**BPS progress, 7 August:** the existing counterfactual has now been checked against an independent
public reconstruction covering all 537 players and 380 fixtures from 2025/26. The model beats both
no correction and a position-only correction on player-season MAE (0.535 vs 0.693 and 0.752) and
has 0.625 rank correlation. All 537 players and all 440 unique changed player-fixtures map to the
local archive. The external page duplicates Junior Kroupi's GW9 movement and reconstructs rather
than observes complete big-chance-save labels, so it remains advisory evidence. No production
artifact changed: retain the shrunk outfield prior and the neutral goalkeeper policy until a
complete reliable event feed and forward policy replay support anything stronger.

### 2.3 Price and transfer option value

- Model plausible price scenarios and exact selling value so multi-week routes remain feasible.
- Give retained free transfers, bank and flexible price points a learned terminal value.
- Reject churn for gains smaller than historical forecast error unless the move resolves a genuine
  availability or structural problem.

Every challenger uses time-forward folds, a frozen selection season and an untouched test season.
The prospective 2026/27 stream becomes the decisive holdout as it accumulates.

## Priority 3 — chips and schedule uncertainty

**WC/FH implementation progress, 8 August:** both chips now have exact legal squad searches inside
the weekly action universe. Wildcard optimises a permanent multi-event 15; Free Hit optimises only
the current event and supplies an explicit event-to-squad map that restores the original 15 for all
later shared-world simulations. The receipt compares every candidate with the strongest weighted
ordinary route and exposes transfers, bank, captaincy, raw edge and downside. Authority remains
zero because the retained-chip policy failed its point-in-time historical downside gate. See
[`docs/squad-chip-shadow.md`](../docs/squad-chip-shadow.md).

The first point-in-time retention input is also frozen. The historical fixture ledger contains
1,771 decision/future-event rows across 83 pre-deadline snapshots: 37 in 2023/24, 35 in 2024/25 and
11 in the available 2025/26 archive. It records the blanks, doubles, unassigned fixtures, schedule
certainty and events-ahead visible at each decision without backfilling final rearrangements. This
closes the schedule-information input, but not the retained-points policy: historical chip
inventories differ and legal WC/FH replay still must select on one season and clear untouched and
prospective tests.

**Progress, 8 August — rearrangements:** the point-in-time transition builder found 17 historical
unassigned-to-assigned episodes, 16 resolved, representing nine independent correlated
announcement batches across two seasons. The empirical delay/lead support now drives a current
Monte Carlo blank/single/double/triple shadow and is included in weekly lineage. Its frozen evidence
gate requires 20 batches across three seasons, so it remains diagnostic and cannot turn an
unassigned fixture into a confirmed double.

**Progress, 8 August — continuous chip retention:** exact WC/FH replay now carries legal state over
38 deadlines. A 2023/24-selected trigger gained 79 points on untouched 2024/25 but failed its
four-Gameweek downside gate (−1.053 points/GW lower bound). The BB/TC trigger gained 24 test points
and finished two above an offline best-forecast-opportunity comparator in total, but failed the
stricter timing-regret lower bound (−0.474 versus the frozen −0.25 bar). Both verdicts are `REJECT`;
their receipts are lineage, not authority. Next is policy improvement, joint four-chip competition
and prospective 2026/27 evidence—not weaker promotion thresholds.

- Build versioned blank/double fixture scenarios from the schedule known at each deadline.
- Optimise Bench Boost, Triple Captain, Wildcard and Free Hit against no-chip routes plus the option
  value of retaining the chip.
- Encode the 2026/27 half-season chip expiry/reset exactly.
- Require a high route-stability threshold before spending a chip; uncertain future doubles must not
  be treated as confirmed fixtures.
- Test chip policies in historical point-in-time replays and prospectively in shadow mode before
  allowing them to drive the live recommendation.

**Progress, 7 August:** Bench Boost and Triple Captain are now exact shadow branches of every
ordinary weekly action. Triple Captain adds the third captain score with vice fallback; Bench Boost
scores all 15 plus ordinary captaincy rather than relying on the autosub approximation. Because each
variant shares the same transfers, squad and simulation worlds as its no-chip parent, the receipt
has paired current-uplift evidence. It subtracts the best visible same-half future opportunity,
requires positive weighted and worst-family value plus a central paired interval above zero, and
fails whenever the forecast does not cover every remaining event before expiry. The official
fixture generation now produces a content-addressed schedule receipt that distinguishes confirmed,
provisional and unassigned matches, lists every blank/double team-event and detects rearrangements.
Unassigned matches remain unassigned rather than being speculatively placed into a future double;
unresolved schedule coverage is an explicit chip-gate failure.

The component simulator was also corrected at the match boundary. A double now has independent
appearance, clean-sheet, concession, save, discipline, defensive-contribution and bonus scoring per
fixture before gameweek aggregation; blanks score zero. Event-level P(any minutes) is preserved,
while the allocation across a double uses the historical conditional split: 70.2% two appearances
and 29.8% one. Even a passing current-horizon shadow route remains operationally `no_chip`.
Separate historical retention replays and probabilistic rearrangement scenarios are now
implemented, but their frozen evidence gates rejected promotion. Joint four-chip competition and
prospective validation remain open.

## Priority 4 — prospective learning loop

At each deadline freeze forecasts for every selectable player and every generated action route.
After the gameweek finalises:

- ingest corrected final scores and actual minutes;
- score calibration, return ranking and policy regret;
- compare the chosen action with roll and all frozen feasible alternatives;
- attribute misses to participation, team goals, player events, bonus, rules or optimisation;
- update monitoring dashboards without silently retraining the champion; and
- promote challengers only at scheduled review points.

Lewis's result is the product outcome, but one manager supplies only 38 path-dependent observations.
Model validation must use all player outcomes and frozen policy counterfactuals so the system learns
from thousands of events without overreacting to one captain blank.

**Progress, 8 August:** final-event scoring now separates best-considered-action regret from a legal
hindsight XI/captain upper bound, captain regret within the frozen XI, player xP error and
appearance Brier score. It also scores the form-reversion and market-policy actions frozen inside
the deadline receipt. A season scoreboard selects the latest valid pre-deadline receipt per event,
and a checksum-bound registry combines those paired outcomes with five historical challenger gates.
Automatic promotion is impossible; before GW1 the correct state is zero finalized events and direct
xP remains champion.

A GW31–38 mini-league shadow is also implemented. It compares only already-legal action routes,
using immediately prior-event rival lineups, current league gap, rival-exposure distance and a
bounded xP-sacrifice cap. It has no authority and needs historical rank-distribution simulation plus
prospective league receipts before it may alter the points-first objective.

## First implementation sprint

1. Build and test the scheduled snapshot collector plus the unified refresh pipeline.
2. Surface a freshness/completeness receipt in the API and workspace.
3. Re-run the position-specific appearance audit with the broader value-candidate population.
4. Implement the weekly state machine and golden/property tests for transfers, hits, prices, chips,
   lineup legality and autosubs.
5. Add roll/one-transfer/multi-transfer action generation using all 15 players.
6. Build a frozen weekly policy-replay harness and prospective scoring table.
7. Complete a full pre-GW1 shadow deadline before permitting a final squad receipt.

## Committed delivery order from 7 August

The first implementation sprint is intentionally split into independently testable releases. This
prevents a large weekly optimiser from hiding bad state transitions or stale evidence.

### Release A — trustworthy deadline pipeline

Build an append-only current-season snapshot store and one orchestration command that performs:

`collect -> validate freshness/completeness -> rebuild features -> forecast -> generate candidates
-> simulate -> synthesise -> publish receipt`.

The first vertical slice covers official bootstrap, fixtures, authenticated manager state and the
forecast artifacts already used by the app. Every stage records `observed_at`, source checksum,
artifact hash and status; rerunning the same inputs is idempotent. The web workspace reads the
published receipt rather than combining independently dated squad and model files.

**Acceptance:** a test fixture can replay a deadline run byte-for-byte; a deliberately stale or
incomplete source prevents publication; the UI receives one coherent freshness receipt.

**Progress, 7 August:** the official-data slice is implemented. Bootstrap and fixture collections
are now immutable, content-locked and structurally validated; their live pointer advances only for
a complete capture. Freshness tightens automatically as the deadline approaches, normalized
Parquet writes are atomic, and a refresh receipt binds raw and processed checksums. The first real
capture (`20260807T082624030905Z`) contains 572 players, 20 teams, 38 events and 380 fixtures and
passed the complete data validation suite. Authenticated MCP sync now archives an allowlisted,
content-locked manager snapshot with purchase/selling prices and rejects credential-like fields.
The publication gate then verifies official and manager freshness, full forecast-grid agreement,
exact source-snapshot alignment, decision/source checksums and current-forecast lineage. On the real
workspace it first refused the existing decision because the fresh 7 August official snapshot,
6 August forecast and 3 August decision were different generations. The feature layer was then
rebuilt from the new snapshot and all 20 leakage/coverage checks passed. Direct and component
forecasts now share the exact 7 August source timestamp and explicit cross-artifact hashes, leaving
only the robust-search, horizon and synthesis decision generation stale. The web workspace exposed
that precise state instead of describing the old recommendation as current.

The complete decision funnel was then rebuilt from that generation. Artifact-lineage guards now
reject stale residual candidates, component selection receipts, global shortlists, horizon inputs
and synthesis inputs before expensive simulation begins. The global search considered 559,379
legal squads, deep-tested 64 finalists, and selected a five-week leader; the independent GW1–8
audit promoted a different horizon leader by +1.386 decayed points (95% CI +1.216 to +1.556). The
cross-family synthesis selected balanced finalist `R-dc7de17def`, a 4-3-3 with Bruno Fernandes
captain, after 40 squads had measured regret in both audit families. The final deadline evidence
receipt is publishable with zero issues and points to the 7 August official, direct-forecast,
component-forecast and decision generations. The remaining orchestration task is now implemented as
`fplagent deadline-run`. It performs the public refresh, validation, feature rebuild, frozen direct
and component inference, exact manager-state derivation, weekly candidate generation, shared-world
simulation, synthesis and gated publication. Direct and component inference use input manifests so
unchanged generations retain byte-identical outputs. A repeated pipeline fingerprint reuses the
published receipt; failed staged evidence cannot replace it, and a failed final recheck rolls back
both the decision and freshness status. Fixed-time fixtures prove byte-for-byte reuse, blocked
publication and rollback. Broad engine/data/web QA now passes 139 tests. Release A is code-complete;
the remaining requirement is the scheduled pre-deadline shadow operation on live inputs.

After the failed FWD appearance calibrator was retired, a first manual rebuild considered 545,913
legal squads and retained balanced finalist `R-dc7de17def`. That receipt is now superseded. The
production orchestrator exposed a further reproducibility defect: the current feature query had no
final order, so unchanged logical rows produced different forecast hashes on repeated refreshes.
The grid is now deterministically ordered by event/player and component inference rejects any
equal-length grid whose exact key order differs from the direct forecast.

The canonical ordered run considered 547,415 legal squads. Five-week robust search selected
`R-5043bb75d6`; the untouched eight-week audit promoted `R-2f0b2cc758` over it by +1.082 decayed
points (95% CI +0.920 to +1.244); and cross-family synthesis selected `R-ee60e45c6d`, a 5-3-2 with
Bruno Fernandes captain, Tarkowski vice-captain and £1.0m bank. The decision hash is
`084f7eff7f59beda1281318002f02587d949099d5af99d718106c0fa4a7f0ce7`, and the deadline evidence
gate is publishable with zero issues. Static checks and all 161 non-LLM engine, data and web tests
pass after the rebuild.

A subsequent checksum-bound local-decision audit closed the remaining stale-incumbent gap in the
older bench review. It held the published 15 fixed, enumerated all 550 legal XIs, scored 3,300 bench
orders and 4,950 joint XI/bench/captain/vice configurations on 5,000 residual and component
selection worlds, then evaluated 64 finalists on independent 25,000-world holdouts. The selection
champion was exactly the published configuration: 5-3-2, Bruno captain, Tarkowski vice, with
Calvert-Lewin ahead of Szoboszlai and McAteer on the outfield bench. This audit is read-only and must
be repeated after a changed synthesis; the full non-LLM suite now passes 164 tests.

The remaining manual-run risk is now addressed by `fplagent gw1-deadline-run`. It fingerprints the
forecast, component forecast, runtime rules, implementation and full simulation configuration;
runs the anchor, residual tournament, independent component selection/holdout, global search,
horizon audit and synthesis in fixed order; stages the final decision/results/report; and publishes
only after both staged and final evidence checks. Identical fresh inputs reuse the published bytes.
A failed staged gate leaves the active decision untouched, while a final-check race restores all
previous published artifacts. The first real full invocation passed every gate and published the
canonical receipt. An immediate repeat reused the same generation in 4.15 seconds without starting
optimisation, proving the idempotency path on production artifacts rather than only test doubles.
The remaining operational work is to repeat it at the declared pre-deadline refresh windows.

### Release B — executable weekly FPL state

Introduce immutable `ManagerState`, `GameweekState` and `ActionBundle` contracts. Encode exact squad,
purchase prices, selling values, bank, free transfers, hits, chip inventory, active chip, temporary
Free Hit state, lineup, bench order, captaincy and event finality. Implement transitions separately
from optimisation and cover them with golden and property tests.

**Acceptance:** every legal transition in the rules audit is reproducible; illegal budgets,
formations, transfers and chip sequences fail before the solver; state restoration after Free Hit
and transfer-bank behaviour around Wildcard are exact.

**Progress, 7 August:** the immutable transition foundation is implemented independently of the
optimizer. It represents purchase/current/selling prices, the half-profit sale rule, bank and a
five-transfer cap; charges exact four-point hits; validates all 15 players plus XI, bench order,
captain and vice-captain; makes Wildcard permanent and Free Hit temporary; preserves the entering
transfer bank for both unlimited-transfer chips; expires first-half chips and unlocks the second set
at GW20; rejects GW1 and consecutive Free Hits; and advances scores only through locked, live,
provisional and final states. An authenticated-snapshot adapter now joins the 15 picks to the
current event-scoped player catalog, preserves the MCP purchase/selling prices, bank, remaining
free transfers and already committed hit cost, reconstructs lineup/bench/captaincy and fails closed
when finance or current-half chip state is incomplete. Seventeen focused transition/adapter tests
pass. The real preseason snapshot correctly remains outside this weekly contract because FPL returns
null free-transfer and purchase-price state before the season begins. Next, the app must persist the
derived contract once the authenticated endpoint becomes complete and action generation must use it
rather than the older optimizer-local transfer counters.

### Release C — roll-versus-action policy engine

For a connected manager, generate roll, best one-transfer, best available multi-transfer and
after-cost hit routes. Optimise the best XI from all 15 players for every resulting squad, then set
bench order, captain and vice-captain. Re-rank legal routes under correlated match simulations and
forecast-error perturbations.

**Acceptance:** roll is always an explicit comparator; gains include hit cost and retained-transfer
value; no bench player is excluded from XI/captain consideration; the result exposes central gain,
downside, stability and strongest rejected route.

**Progress, 7 August:** the deterministic action funnel now solves exact transfer counts against the
immutable manager state. It uses real selling proceeds and bank, labels roll/one-FT/multi-FT/paid
routes, subtracts incremental hit cost, and produces the forecast-best legal formation, XI, bench
order, captain and vice from all 15 players for every squad and every event in the requested
horizon. Alternative squads are generated by no-good cuts rather than a hand-picked transfer list.
Production residual, raw-component and anchored-component worlds now evaluate every action on
shared simulations with exact autosubs and captain fallback. The synthesis reports paired gain
versus roll, confidence interval, beat probability, downside CVaR, mean rank and scenario regret;
requires identical action IDs in every scenario; and uses stricter evidence gates for hits than free
transfers. It falls back to roll when the apparent winner is unstable. A versioned runner records
manager, forecast, component-model and canonical runtime-rule hashes in its receipt. It now fails
closed unless the direct and component forecast grids, source snapshot, direct-forecast hash and
component-model hash prove one exact evidence generation; the simulator consumes that validated
component path rather than a mutable global default. Thirty-two focused state, adapter, MILP,
simulation and decision tests pass, including promotion of a bench player into the XI and
captaincy. Retained-transfer value is now learned from frozen point-in-time opportunity states:
2023/24 and 2024/25 fit the curve, 2025/26 remains held out, and no future realised outcome enters
the estimate. The promoted cumulative value for arriving with 1–5 free transfers is 1.57, 3.25,
4.36, 5.17 and 5.85 points; held-out MAE improves from 3.47 for the former zero assumption to 0.94.
The runtime discounts the curve to the end of the fixed horizon, validates its rules hash and
records the artifact in its receipt. Authenticated MCP sync now attempts a second, immutable weekly
state derivation after archiving the raw response. A ready contract is bound to one raw snapshot,
official next event, forecast generation and canonical rules hash; its loader revalidates all four
before optimisation. Legitimate preseason null finance/pricing or incomplete chip rows return
`not_ready` without writing a contract, while data-lineage failures return `blocked`. The weekly
runner accepts this exact contract directly. Remaining Release C work is therefore operational: the
first complete post-GW1 response must exercise and publish the real contract and decision receipt;
the new terminal curve must also join prospective weekly policy scoring rather than being treated
as permanently correct. The
workspace contract and UI now support the other half of the release: a valid weekly receipt exposes
the selected route, named transfers, hit cost, formation, captain, next transfer bank, paired gain
and confidence interval, beat-roll probability, worst model-world gain and strongest rejected
route. Missing and malformed receipts render explicit pending/blocked states, and the receipt hash
joins the evidence dialog. No fake current receipt is published before the authenticated weekly
state is complete. Combined engine, data and web QA passes 130 tests; frontend lint and production
build also pass.

### Release D — forecast challenger programme

Improve participation/minutes first, then team strength and player component rates. Each challenger
is time-forward, position-calibrated and evaluated both statistically and through frozen squad,
lineup, captain and transfer replay. Add richer signal only when it beats the champion without
degrading calibration.

**Acceptance:** promotion reports show Brier/log loss, minutes calibration, return ranking and
paired policy outcomes on frozen folds. No hand-tuned current-week fact is allowed into model
weights.

**Progress, 7 August:** the first candidate-only four-class appearance audit trained and evaluated
position-specific challengers on strict 2024/25 and 2025/26 forward slices. None passed the full
gate: some probability and minutes metrics improved, but squad-relevant expected-points and ranking
metrics regressed. An exact 76-gameweek legal-squad/XI/bench/captain replay was then run for the
existing production FWD calibration. It lost 0.789 points per gameweek to the raw policy on average
(paired 95% interval -1.569 to -0.010), so every retention check failed. The FWD calibrator was
retired through a content-hashed receipt, its exact prior artifact was archived, and production is
back to raw appearance probabilities. Direct and component forecasts have been regenerated under
that policy. A complete robust-search, horizon and synthesis rebuild now passes the final evidence
gate. The later deterministic-grid and canonical two-pass pipeline correction selected a different
15-player synthesis winner; no appearance challenger was promoted merely for improving probability
metrics.

A second, leakage-safe role challenger added longer appearance/start windows, full-match rates and
minute stability. GK alone passed the two-slice statistical screen, but applying that slice in the
same 76-Gameweek legal-squad replay lost 0.013 points per Gameweek, with a paired 95% interval of
-0.426 to +0.400 and a negative 2024/25 floor (-0.184). It was rejected; production remains
unchanged.

The first live preseason evidence layer is now collected separately from model weights. Its
content-addressed receipt covers 52 confirmed friendly lineups, 56 Premier League team/event sides
and 352 current FPL players across 18 clubs. Brentford and Brighton have no confirmed lineup feed,
and source minute statistics exist for only 33.5% of lineup rows, so unknown minutes remain null.
For the published 15 it flags Bruno Fernandes (zero of three captured United lineups) and Watkins
(zero of six Villa lineups) for urgent verification, while Collins, Igor Thiago and Verbruggen are
explicitly unknown because their clubs are uncovered. These facts are advisory, not hand-authored
probability changes. The bound, scenario-only squad/XI/bench/captain replay and its refined
availability-retention curve are now complete; remaining friendlies and timestamped availability
evidence are the next inputs.

That scenario audit is now complete. It uses identical counterfactual conditional-DNP masks in the
residual and component families, 5,000 selection worlds and a separate 25,000-world holdout. The
published squad and exact configuration survive baseline and moderate stress. Severe stress still
retains the published XI/bench/captain configuration, but nominates `R-5043bb75d6`: McAteer and
Mukiele out, Neco Williams and Enzo Le Fée in. A second equal-footing stage exhaustively searches
all 550 legal XIs, 3,300 bench orders and roughly 4,950 joint configurations for both squads. The
challenger survives with +0.079 residual points (95% CI +0.042 to +0.116) and +0.162 component
points (+0.079 to +0.245). At the extreme boundary where every three-plus-lineup absence is forced
to DNP, the deep squad comparison and within-15 configuration both reverse. No production value
changed. Public context makes post-World-Cup return timing a more credible explanation for Watkins
and Bruno Fernandes than established injury, so this is an operational verification trigger. The
follow-up fresh-seed threshold curve shows how extreme that trigger is. The challenger has support
at 51.0% conditional retention for three-plus-lineup absences and 75.6% for role-watch players, but
loses cross-family support at 51.5%/75.9%. The supported-edge component interval clears zero by
only 0.002 points. This is not an availability estimate: capture the remaining friendlies and press
conferences, then stage forecast changes only if attributable evidence justifies them. During this
audit an unordered residual-bootstrap query was also found and fixed; identical seeds now reproduce
identical simulation bytes across processes.

The operational availability watch now binds these layers into one current-squad receipt rather
than leaving the manager to reconcile separate reports. It shows official FPL status and news,
forecast appearance probability, preseason evidence, feed gaps and the supported-edge mechanical
stress value for every selected player. The initial receipt has no official doubts, four players
requiring attributable role verification and three uncovered-feed players. It retains the current
decision and cannot promote an advisory change; any lineage mismatch or receipt older than 72 hours
returns `refresh_required`. `deadline-status` now exposes the compact summary alongside the official
publication gate.

### Release E — chips and prospective learning

Add half-season chip inventory/expiry, blank/double schedule scenarios and option value. Freeze every
weekly forecast and feasible action before the deadline, then score it after official finalisation.

**Acceptance:** chips are compared with no-chip routes and retained-chip value; the app can explain
after each gameweek whether a miss came from minutes, team events, player events, bonus, rules or
optimisation rather than changing the champion from hindsight.

**Progress, 7 August:** the prospective half is now executable. Successful weekly publications are
copied into immutable event/fingerprint archives, and the v3 weekly receipt freezes event lineups
plus every relevant player's position, expected/robust points, participation probability and
expected minutes. Official event-live outcomes can only be archived when bootstrap marks the event
both `finished` and `data_checked`; the collector requires the exact bootstrap player set and locks
all bytes by checksum. `fplagent score-weekly-event` then rejects post-deadline decisions and scores
the selected route, roll and every considered alternative with exact formation-valid autosubs,
captain fallback and incremental hit costs. It records realized rank, gain versus roll, opportunity
cost, aggregate forecast error and player-level points/minutes errors in an immutable receipt. The
scorer now also emits exact action, legal-XI/captain, captaincy, participation and paired
shadow-policy attribution; the season scoreboard and challenger registry aggregate those frozen
receipts. The workflow is covered by finality, corruption, deadline, idempotency and action-scoring
tests. It must be exercised on the first finalized 2026/27 Gameweek and accumulated over multiple
weeks before it can promote a policy change. Exact chip searches, rearrangement scenarios and
separate retained-value replays are implemented, but their frozen historical gates rejected
authority; joint four-chip replay remains.

The different GW1 synthesis format is covered too. A separate content-addressed contract freezes
the selected squad, strongest rejected squad, 30 additional synthesis finalists and all relevant
event-one player forecasts without changing the active decision. The current contract fingerprint
is `0c6e7d97659e0dde8a3ba1bc9a3ab0cb2f8c6f1edefaae36cb959369e8c64f5f`; it binds selected
`R-ee60e45c6d` to direct forecast `c900c197…`, official bootstrap `ef61736b…` and the 21 August
deadline. GW1 publication now treats successful contract creation as an atomic final step and
restores the previous decision/results/report/evidence if it fails.

## Deliberate non-priorities

- More LLM fine-tuning unless a measured product failure blocks decisions.
- Automated writes to the official FPL account before read-only decisions are dependable.
- Deep neural forecasting merely because the RTX 5090 can train it.
- Mini-league differential authority before late-season rank simulations and prospective receipts
  pass; the current bounded shadow is diagnostic only.
- UI additions that do not improve evidence, decision clarity or deadline reliability.

The standard is simple: each sprint should either improve a frozen predictive/decision metric,
reduce the probability of a costly operational failure, or make an existing point-winning decision
usable before the deadline. Everything else waits.
