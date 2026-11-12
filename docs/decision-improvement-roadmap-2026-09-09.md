# Points-first improvement programme — 9 September 2026

Goal: improve expected season-long **net FPL points**. We do not optimize team value, ownership,
exciting single-week outcomes or chat quality as substitutes. No LLM training or FPL account writes.

This supersedes the older GW3 implementation status. The evidence motivating this work is in the
[opening-three-gameweeks review](../reports/opening-three-gameweeks-strategy-review-2026-09-09.md).
The opening results do not establish a winning edge. These priorities are ranked by reach across
decisions, strength of the evidence for a defect, and implementation/validation cost—not invented
estimates of points we will certainly gain.

**Deployment decisions now concluded:** read the [promotion/rejection review](../reports/points-first-promotion-decisions-2026-09-09.md).
It supersedes any "pending promotion" wording below for these experiment versions. Correctness and
measurement fixes ship; the failed/unvalidated replacement policies are explicitly rejected for this
release. Recording additional measurements is not an indefinite approval queue.

See the [completed implementation and publication report](../reports/points-first-implementation-2026-09-09.md)
for the final live run, exact receipt hashes, test results and reproduction commands.

**Latest continuation:** [round-two validation and GW4 handoff](../reports/points-first-validation-round2-2026-09-09.md)
adds shared-world future-transfer/chip plans, full-season chip-state audits, role-change folds,
candidate-access/risk tests and prospective scoring. Read its final publication section for the
latest run; the first report above preserves the earlier batch.

## Priority order and current delivery

| Priority | Work | Why it comes here | Status in this iteration |
| --- | --- | --- | --- |
| 1 | Select the strongest admissible action | Demonstrated selector defect; affects every deadline; small, testable correction | Implemented and replayed on frozen GW2–GW4 |
| 2 | Adaptive transfers and future affordability | Fixed-roster lookahead undervalues the ability to change next week; affects all moves and capital allocation | Paired opening-ten-event replay +58/−2 failed activation; shared-production-world continuation now integrated, still diagnostic |
| 3 | Four-chip strategy and credible validation | Eight scarce opportunities with expiry; false validation confidence is costly | BB/TC forward calibration passed; joint two-deadline frontier and 76-event/eight-chips-per-season state audit complete; WC/FH timing authority still unproved |
| 4 | Detect genuine role changes and expose data authority | Minutes/role errors affect every forecast and can dominate optimizer sophistication | Non-overlapping role-change model tested on 83,243 events; narrow latest-fold log-loss failure, not promoted; no new independent source claimed |
| 5 | Test squad allocation and the objective | Expensive reserves and model-world protection can sacrifice starting/captain points | Seven candidate families and four risk weights scored in shared worlds; frozen GW2/GW3 weights tied on realized points; no coefficient retuned |
| 6 | Prospective scoring and honest uncertainty | Makes future improvements falsifiable; small evidence-capture changes should ship now | Full-pool forecasts plus role, first-action continuation and allocation/risk alternatives frozen and scorable; future evidence pending |

Low-cost evidence/reporting fixes from later priorities are included now because they are prerequisites
for judging the larger modelling changes. This is not a claim that all six research programmes are complete.

## 1. Strongest admissible action

Previously, the selector tested only the robust leader, then jumped straight to roll on failure.
Now every ranked route receives the same after-cost, cross-world, Monte Carlo and paid-hit checks
against the unchanged roll comparator. Current incoming-player role checks also run before selection.
The highest-ranked admissible route wins; roll remains eligible. The receipt records every gate and
the higher-ranked routes rejected. Final role and deadline publication gates remain in place.

Frozen replay (original candidates and simulation metrics, legal actions reconstructed from archived
manager state; no replacement of historical forecasts with today's news):

| Event | Old action | Corrected selection | Interpretation |
| --- | --- | --- | --- |
| GW2 | Roll | Richarlison → Igor Jesus, rank 3 | First two routes failed; the third passed. +0.688 weighted horizon gain, +0.560 worst world. Actual GW2 points would still have been 90; no realized gain claimed. |
| GW3 | Lacroix → António Silva; Gakpo → Gibbs-White | Unchanged | Does not explain away the poor GW3 outcome. |
| GW4, morning evidence | Richarlison → Evanilson | Unchanged | The original robust leader already cleared the gate. |

The historical replay isolates the selector; it does not re-evaluate old role feeds with new information.
Live role checks are covered separately by regressions and the full current-event pipeline.

Weekly receipts and the app cache now fingerprint engine implementation files. An engine fix cannot
be hidden behind a recent cached result. UI-only changes do not invalidate engine decisions.

## 2. Bounded adaptive-transfer diagnostic

`weekly_continuation.py` fixes today's action first, then permits legal transfers at the next deadline
under each supplied scenario. State retains the exact squad, purchase/selling prices, cash, free
transfers and chips. Prices change buying/selling feasibility; they do not add arbitrary points bonuses.
One first action must be chosen across scenarios—there is no clairvoyant choice using later outcomes.

Defaults: at most four first actions (including the operational action and roll), up to two future
transfers with at most one paid transfer, one solve per transfer count, one-second per-solve limit,
and a 12-second total budget. A budget-exhausted root comparison cannot declare a winner.
The default scenario uses frozen forward forecasts and flat prices: it does **not** predict future
news or price probabilities. Caller-supplied price/news scenarios are sensitivities, not calibrated probabilities.

The objective remains the deterministic screening utility, including its bench proxy, decay and
terminal FT curve. Current/future hits and terminal FT value are counted once. Future rosters after
the next deadline remain a fixed-roster approximation. This is not yet a full stochastic season planner.
Every receipt states `decision_authority: false`; an invalid diagnostic cannot block publication of an
otherwise legal recommendation. Full-table testing caught and fixed Arrow decimal/date serialization.

On the morning GW4 snapshot, the direct diagnostic finished in approximately 2.2 seconds. Next-week
recourse added about 3.78 utility points to rolling and 1.94 to the selected move. These are *screening
utility* differences, not comparable to the production simulation's +2.16-point estimate. They show
why future moves deserve proper testing; they do not authorize a new transfer recommendation.

Next acceptance gate: recent chronological sequential replays with legal state carry-forward,
frozen scenario-generation rules, common simulation worlds and net-points scoring. Compare the
incumbent against adaptive 1/3/5-deadline policies, including affordability shocks and future repairs.
Report incomplete solves and match solve budgets. Promote only after held-out and prospective support.

**Follow-up completed on 9 September:** the new [adaptive-transfer experiment](../reports/adaptive-transfer-replay-2026-09-09.md)
tests paired GW1–10 paths, reconstructs future forecasts only from each origin and earlier training
seasons, and handles actual deadline price/club changes. It gained 58 net points in 2024/25 but lost
two in 2025/26, so it failed its predeclared two-fold screen. This is a deterministic zero-terminal-FT
ablation, **not** a comparison with the complete production selector. No policy weight was changed
to make it win. A confirmed optimal solve or proven infeasibility is now required for a complete
continuation comparison; timeouts no longer count as impossible routes. New receipts preserve
future rosters/lineups and prospective scoring tracks the frozen first-action challenger separately.

Next work is production-matched sequential validation and joint chip-state continuation, not
automatic activation or repeated tuning on those same two results. Tactical-role validation remains
the next independent high-impact workstream.

## 3. Chips

See [chip strategy v2](chip-strategy-v2.md). Calibration now trains only on earlier seasons; all 38
events per season must be present. The corrected 2024/25 and 2025/26 tests passed the existing gate.
Their actual BB/TC uplifts were 34 and 17 points; the offline forecast-selected comparators scored
17 and 21. These are narrow path comparisons—not proof of SOTA timing or a universal points uplift.

BB/TC remain eligible under live gates. WC/FH remain research-only because persistent future-state
value has not passed the required outcome test. Normal-week FH routes are no longer incorrectly
blocked merely for lacking a blank/double. Legality, expiry and schedule-risk checks still apply.

Next: extend adaptive continuation to permanent Wildcards, Free Hit restoration and WC→BB interaction;
replay complete chip halves jointly with ordinary transfers, not just isolated chip uplifts. The UI
now distinguishes research-only upside from a validated decision to retain.

## 4–5. Role, market and capital hypotheses still to test

- Calibrated role-change detection must distinguish lost selection/changed job from finishing variance.
  Test start patterns, conditional minutes, team-share xG/xA and fresh independent lineup evidence.
  Existing short/long-form features are not new independent signals merely because they are renamed.
- Audit source → fixture rates → player forecasts → candidate access. A market model cannot win with
  a player structure it never gets to propose. Preserve current authority boundaries until a matched
  decision replay establishes lift; no FPL-authored `ep_next` or `ep_this` is permitted.
- Compare reachable lean-bench, balanced, strong-defence and premium-captain structures, including
  legal WC alternatives. Charge their captain/XI opportunity cost and attribute reserve value to
  autosub cover, scheduled starts and chip benefit separately.
- The current robust selector may intentionally sacrifice mean points. New `objective_tradeoff`
  fields split the sacrifice into safety-gate exclusions and robust-ranking preference. This makes
  the trade-off visible without silently changing risk weights to fit one bad week.

## 6. Evidence capture and presentation

New weekly receipts freeze every player in the current-event forecast pool, including minutes,
appearance probability and a PMF with calibration lineage. They record candidate coverage separately.
Prospective scoring now reports all-frozen, selected, omitted, predicted-regular, top-30-forecast and
position cohorts. Missing official outcomes remain missing and are counted, never zero-filled.
Old subset receipts stay explicitly labelled; there is no pretend pre-deadline backfill.

The app distinguishes the weighted model gain from one world's mean and its Monte Carlo confidence
interval. A narrow interval is precision of simulated mean estimation—not a range of actual FPL
outcomes, a calibrated success probability, or protection against model misspecification. Expanded
details expose this without adding another main-panel card. The existing frontend design skill
guided that progressive-disclosure treatment, not a redesign.

## Validation and operational handoff

143 targeted engine, state, chip, prospective, workspace, refresh and publication tests passed during
implementation. Python lint and the frontend build/lint passed; final browser and full-publication
results are recorded in the accompanying implementation report. The tests include unchanged active
state on gate failure, paid hits, sale-price changes, FT carryover, diagnostic budgets, chronological
folds, chip collisions/expiry and cache invalidation after engine changes.

Do not restart the LLM workstream. Do not treat the new diagnostic as an instruction to transfer.
The next highest-value **research** work remains priority 2's matched sequential replay, followed by
joint WC/FH continuation. Current-season evidence must continue to accrue untouched.
