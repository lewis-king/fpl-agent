# FPLAgent continuation handoff

## Latest work — chips used before expiry, 6 November (Claude Code takes over from Codex)

Lewis: chips reset each half and must never be lost. Before this change WC/FH had blanket
`authority_by_chip=False`, plus a hard `raise` in `policy_release`, so both would have expired at GW19.
Now:
expiry guarantee for all chips; live full-half WC timing (`chip_timing.py`, run automatically
after publication with a second pass); FH on calendar/uncertainty gates; dated `deadline_plan` in the
API, CLI and web. Details and limits are in `docs/chip-strategy-v2.md` (6 November section). The GW10 result was a
WC-now edge of +3.1 against a required 4.0 (international break), so it **held**, with WC planned for GW11. Lewis agreed.
GW10 advice: no transfers, Gabriel (C), Bruno (VC), roll to 2 FT.

Tests: new `tests/test_engine_chip_timing.py`; updated chip strategy and policy release tests.
927 non-LLM tests pass. Five web tests fail for environmental reasons (the LLM captain tool reads the frozen GW1
forecast covering GW1–8 while the live calendar is GW10), not because of this change.
Ops notes: the CLI's `decisions --refresh` poll times out while the API is busy simulating
(the job keeps running); poll `/api/v1/workspace/refresh` instead. The FPL token can expire
mid-day (401 on my-team): restart the MCP server, then sync again.

## Latest work — adaptive Wildcard audit, 22 October

The user challenged GW8's −4 recommendation versus using the first-half Wildcard and retaining
United players. Do not describe the current recommendation as proven optimal or say WC lost:
WC/FH are still denied automatic authority by the existing release policy. A positive blocked
chip alternative is now explicitly unresolved in the API view, CLI and frontend; ordinary moves
are conditional on no chip. Frontend/CLI support an older API's existing candidate-status fields,
so the warning does not require publishing a new decision. The saved squad was not replaced.

New isolated module: `src/fplagent_engine/wildcard_timing.py`; commands in
`docs/chip-strategy-v2.md`. Full evidence and caveats:
`reports/wildcard-timing-audit-2026-10-22.md`. No LLM work or FPL account writes.

Baseline: 88 full-half paths, GW8–19, weekly replanning with exact finances/FT/chip mechanics.
10k selection / 20k validation draws. WC now +7.22 vs published −4 followed by WC9; free
Semenyo→Rogers then WC9 +2.21. Conditional BB/TC date selection keeps WC preferred (+7.59).
United −20% point sensitivity switches the preferred WC from both Bruno/Mbeumo to neither.
These are simulations conditional on model assumptions, NOT calibrated match-outcome confidence.

Two recent-season chronological DEVELOPMENT comparisons chose WC-now on forecasts but realised
0 and −34 net points versus the independently selected later-WC branch. Both branches replan
using each real deadline's forecasts/prices. Earlier seasons only fit each residual calibration.
Do not promote timing on this evidence. Original historical scoring/current chip mechanics are
mixed counterfactually, and these seasons have already been reused in development.

Further audit extends current ordinary-move generation to anticipate the selected WC date
(`--wc-aware-roots`); the exact published route always stays fixed for comparison. Read its
separate receipt before interpreting differences; historical replay above covers the original
fixed-root prototype, not a validated deployment of that extension.
The completed follow-up selected WC-now/Bruno-only at +7.47 versus the published root, while
the free Semenyo→Rogers bridge to WC9 was +2.41. The top two WC structures are near-tied and
switch selection between draw seeds; do not claim stable evidence for one Mbeumo decision.

Future-news audit must FREEZE root and WC date using the no-news origin run, then execute only
revealed information. `scripts/audit_wildcard_news.py` checks pre-news path equality. Selecting
the best root from a particular future-news scenario is an oracle sensitivity comparison and
must not become a recommendation. An auxiliary sorted-metric indexing error was caught/fixed;
ignore the explicitly invalid-index receipt. Main comparisons use correctly ordered arrays.

Next substantive work: calibrated future-news/role transitions and waiting option value; joint
Free Hit plus BB/TC preparation transfers; more origins/manager states; long-range forecast
validation; production-world replication. GW13–19 currently uses labelled frozen-ability fixture
extrapolation, not known future odds/lineups. Do not hard-code United cuts or remove evidence gates.

Research artifacts are under `data/research/wildcard-timing-20261022-*`; private frozen manager
contracts are included, so do not indiscriminately commit them. Core source/tests/report are the
durable record. Existing unrelated worktree changes were preserved.

## Latest completed implementation — fresh forecast diagnosis, 21 October

User accepted three priorities: contemporaneous Scout comparison, error diagnosis, strongest
evidence-led correction. **Real live input bugs found and fixed; do not summarize as no change.**
Full results: [forecast diagnosis and corrections](../reports/forecast-diagnosis-and-corrections-2026-10-21.md).

- Official snapshot `20261021T212002161760Z`; fresh direct/components GW8–12 and market/role
  evidence rebuilt. Private Scout capture (25 players/five events) now passes identity, price
  and contemporaneity checks. Fixed supplied GW7 roster, **not refreshed authenticated GW8 state**.
  Both scalar controls choose the same XI/Bruno C, different VC/bench. Scout outcomes pending.
- Critical bug: live features still used absolute preseason GW1/2/3 availability branches;
  participation preferred this-round100 over next-round0. Semenyo incorrectly had p=.755,
  xP2.70. **18 official unavailable players had nonzero forecasts; now zero violations**.
  Returning players also repaired. General next-round/relative-event fixes, no player-name rules.
- Independent final gate enforces official unavailability without lineup-source dependency.
  Raw-bootstrap publication validation catches recurrence in direct/components. Zero role ratios
  stay zero in component forecasts. Next actionable event beats unfinished current event.
  Cache identities include direct/component code. Existing future recovery priors labeled
  unvalidated, not assumed known injury return dates. No new learned minutes architecture.
- `forecast_diagnosis.py` verifies frozen evidence, handles missing minutes, decomposes appearance
  versus conditional-performance errors, and refreshes automatically in finalized-outcome scoring.
  2,768 frozen player-events; chosen15 mostly lost on returns while appearing, not DNP alone.
  Detailed old attacking/CS/DC predictions were not fully archived; do not invent attribution.
- Complete three-season38-event zero-flag ablation: +29/−39/0 net points, calibration improved,
  no demonstrated policy gain. Independent342 ledger-events checked. Receipt
  `data/research/forecast-diagnosis-20261021/historical-zero-policy-v3.json` (76.19s).
- Paired GPU chronological availability-input refit: 0/0/+30 net points; only2025/26 materially
  exercises changed training feature; block interval crosses0, MAE slightly worse. Independent228
  ledger-events checked. `paired-refit-v2.json` (95.54s), same research folder. Not promoted.
  Both experiments have lagged/proxy snapshot prices and missing-event limitations, not production
  five-week multi-world replication or pristine holdouts. Do not blend their different baselines.
- Release **points_first_release_20261021_v5**: promote semantic correctness, retain learned
  weights/risk/search/chips. LLM parked. No FPL writes, authenticated sync, new recommendation,
  services, commit or push. Last published GW7 receipt deliberately preserved.

Next genuine advice run must sync the manager account first; `decisions --refresh` remains the
normal workflow. The fresh Scout gap is now strongest in some attacking-player assessments,
but one page's disagreement is not evidence to copy its xP. Next research should emphasize
conditional-return rates/fixture context and prospective comparisons, not undo these round fixes
or endlessly retune the same tiny policy samples.

## Latest follow-up — external Scout benchmark and gate/search audit, 21 October

User challenged the repeated lack of policy promotions and stressed that Scout's assessment
methods must inform our thinking. Completed a separate five-arm preregistered experiment;
do not claim the incumbent is optimal or that wider search never helps.

Receipt `data/research/points-priorities/gate-search-20261021-v1.json`, **1034.40s**, completed,
hashes stable; SHA256 `399b2a3bc63b8791a921967d2e4c16ac4305334929d090a04192ed9d12b12a9b`.

| GW1–10, points after hits | 2024/25 | 2025/26 |
| --- | ---: | ---: |
| Narrow incumbent | 602 | 496 |
| Configuration world-veto removed only | 602 | 496 |
| Wider incumbent | 628 | 491 |
| Narrow mean-points policy | 614 | 493 |
| Wider mean-points policy | 614 | 475 |

All replacements fail the fixed positive-both screen. First wider winners in each season
already appear in plain four-alternative search; do not attribute gains solely to forced
premium exits. Live search was already broader than the narrow historical comparator.
Keep risk .25 and existing gates; latest release is **points_first_release_20261021_v4**.
These are inspected development folds, limited to two transfers and no chip timing, with
archive gaps/lagged prices and 95% of world weights anchored to our xP. Not a SOTA test.
Independent ledger/scoring validation passed all 100 new plus 140 earlier arm-events.

New tools:

- `gate_search_replay.py` / `scripts/replay_gate_search.py`: narrow/wide × incumbent/mean
  policy plus isolated configuration-veto arm. Untouched MC validation can reject, not pick
  its own winner. Frozen hashes; never edit engine code or compete for GPU during a run.
- `scripts/verify_policy_ledger.py RECEIPT`: independent accounting and exhaustive legal-sub
  checker. `scripts/audit_search_coverage.py RECEIPT`: first divergent roster coverage audit.
- `scout_benchmark.py` / `scripts/capture_scout_benchmark.py`: authorized session at ignored,
  owner-only `.local/ffscout-cookie.txt`; automatic optional capture in weekly pipeline.
  At most 40 players/five GWs, fixed cohort, strict element+code+club+position join, finite
  values and missingness, timestamp/price checks. No raw HTML/cookies in receipts. Immutable
  private captures under `.local/scout-benchmarks/`; optional failures do not block advice.
  RMT `mn` is an aggregate, NOT next-GW minutes. Scout publication/model build time is unknown.
  Validated final outcomes score current-event MAE/bias/RMSE and frozen same-roster scalar
  XI controls with legal autosubs/VC fallback. These are NOT Scout's actual optimizer/advice.
  Outcome scoring continues if membership is removed; no paid-feed training or authority.

First actual capture: `.local/scout-benchmarks/gw08-aece99be7ca6fbb9ecf7.json`, 25 players,
GW8–11, 21 October 20:45 UTC. Correctly **unmatched**: our forecast is 17 October, plus four
price mismatches. Do not call this a fair forecast-skill win or fresh squad recommendation.
Read-only current FPL bootstrap confirms Semenyo is injured/0%, news added 17 October 17:30
UTC, after our saved 07:53 forecast inputs. No live forecast or published recommendation
was changed. The next genuine weekly refresh must use this newer official evidence.

Full methods, source links and deployment conclusions are in the final sections of
[the Scout audit](../reports/scout-product-audit-and-gw7-review-2026-10-21.md). Scout's public
editorial picks use a one-week objective and £83m XI budget; don't compare that directly with
our multi-week transfer portfolio. Their analysis prompts useful checks on sustainable rates,
set pieces, opponent weakness, rotation/rest, defensive contribution and booking risk.
Exact private RMT priors/coefficients remain unknown; no claim to have recovered them.

Next priority is contemporaneous forecast/disagreement diagnosis and prospective scoring,
not endlessly retuning the same two windows. LLM work remains parked. No FPL account writes,
services, commits/pushes or fresh GW8 decision were made during this follow-up.

Final verification: **883 non-LLM tests passed**, targeted Ruff/whitespace clean, one existing
Starlette deprecation warning. All processes from this follow-up completed. Published GW7 SHA
is unchanged: `a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.

## Latest completed pass — priorities 2, 3, 4 and 5, 21 October

The user asked to continue through all four priorities without repeated permission prompts.
This pass is now implemented, tested and reviewed for promotion. **Do not represent rejected
experiments as live improvements, or say processing is still running: all runs completed.**
Priority 1/new minutes-feature research and LLM work remain parked. Recreating the existing
minute classifier on earlier seasons was solely historical calibration, not a new live model.

Canonical three-world experiment:
`data/research/points-priorities/multiworld-20261021-v4.json`, completed **786.18 seconds**,
SHA256 `6492b0fb57617a8217249275a94f94a6f1b4e564e5f44df181eba974714c9a48`.
Input and engine/CLI hashes were stable throughout. Full explanation, caveats and release calls:
[21 October audit](../reports/scout-product-audit-and-gw7-review-2026-10-21.md), final sections.

| Carried-forward strategy, GW1–10 | 2024/25 | 2025/26 |
| --- | ---: | ---: |
| Three-world control, risk 0.25 | 602 | 496 |
| Premium sale/reinvestment | 602 (0) | 496 (0) |
| Risk 0 | 587 (−15) | 495 (−1) |
| Risk 0.10 | 587 (−15) | 491 (−5) |
| Risk 0.50 | 593 (−9) | 496 (0) |
| Guarded future transfers | 638 (+36) | 495 (−1) |
| Residual score-shape remapping | 623 (+21) | 496 (0) |

All fail the predeclared necessary positive-both-folds screen. The earlier residual-only
latest-season **0/−8/0** result below remains valid; the new **0/−1/0** has a different control,
nonzero prefix FT values, three worlds and exact configuration search. Do not cherry-pick or
compare the absolute control totals as a production improvement.

What is implemented:

- `historical_worlds.py`: prefix-only residual/empirical/component/goal/minute inputs. Explicit
  simulation dependencies prevent reading live calibrations. Dated fixture origin boundaries,
  component OOF inputs and previous-season FT opportunity values are recorded.
- `multiworld_policy_replay.py` + `scripts/replay_multiworld_policies.py`: seven independent
  purchase-price/bank/FT/hit/roster ledgers; 10k selection + 10k new validation draws per family;
  covariance of paired components retained; exact legal XI/bench/CVC and consistent risk
  parameter at both configuration and route levels. Validation can reject, not choose its winner.
- `simulation_calibration.py`: post-decision CRPS, coverage, tail breaches, haul Brier and bias,
  by position and baseline captain/bench. 12,512 player-events; captain cohorts have only nine
  observations per season. Shape remapping improved overall CRPS but worsened captain CRPS in
  both seasons, and did not pass the decision-lift screen. Existing marginal-PMF reporting stays.
- **Production correctness:** `chip_strategy.py` forbids current-half retention beyond GW19/38,
  zeros expired terminal value, and caps retained-chip count by unseen deadline capacity in both
  retain and forced-play calendars. The previous capacity bug valued two saved chips at 14.67
  despite one remaining slot worth at most 7.00. This is a legal/accounting correction, not a
  season-points uplift claim. Shared configuration caches also isolate world generations.
- `chip_opportunity_audit.py`: every normal weekly decision captures exact BB uplift excluding
  already-scoring autosubs and TC with vice fallback. No external requests or manual workflow.
  Diagnostic only: proxy-trained retained values cannot be silently combined with new exact inputs.
- `policy_release.py`: concluded release `points_first_release_20261021_v3`. Promote calendar
  correctness; retain risk 0.25 and existing BB/TC policy; reject expanded pool, guarded recourse,
  score-shape replacement and new exact/WC/FH timing authority. Fail-closed authority tests cover
  the new diagnostics. Research does not promote itself.

Important limitations: bounded two-transfer roster/child search, unit residual scales, no matched
historical live odds/lineup feeds, no pre-2025/26 DC pool, already inspected development folds,
and missing 2025/26 GW8 same-event metadata. The latter uses the earlier dated fixture archive
and stops rating updates at its observation time. Features may carry lagged prices; this is NOT
proof of exact execution-price availability or a complete production-matched/SOTA backtest.
The ordinary-transfer experiment does not validate full-season eight-chip timing.

Saved-GW7 audit `data/research/points-priorities/20261021-v4-chip-capacity.json` completed 59.40s,
hashes stable. Capital challenger +0.03334 simulated points, MC95 lower bound −0.00240: reject.
The exact-chip audit found future BB proxies ~0.67–1.71 above exact uplift; TC fallback adds
~0.26–0.35. These are archived sensitivities, **not fresh GW8 instructions**.

Validation: **854 non-LLM tests passed**, one pre-existing Starlette deprecation warning; targeted
Ruff/whitespace checks passed. Independently recomputed all **140 arm-events** for sale-profit
floor, cash, FT/hit accounting, roster/formation/club constraints, captain/vice and score arithmetic
under the archive's stated price assumptions. No active decision/forecast mutation, FPL writes,
LLM execution/training, service starts, or commits/pushes. Published GW7 receipt remains SHA256
`a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`. Code changes apply on
the next process/run; they do not retroactively rewrite that receipt. **No fresh GW8 refresh.**

Reproduce with `.venv/bin/python scripts/replay_multiworld_policies.py --output
data/research/points-priorities/NEW-NAME.json` (one line). Never overwrite prior outputs or edit
engine code during a hash-frozen experiment. Run GPU-heavy tests/audits separately: an earlier
attempt exhausted GPU memory under concurrent work and is preserved as failed, not counted.

Next research should be preregistered and address historical quote/lineup coverage, matched
production searches and exact-chip retained-value/timing fits, not retune these same two windows
until a score happens to improve. Automatic pre-deadline evidence/outcome capture continues in
the normal feedback loop. A fresh live recommendation is a separate refresh with current evidence.

## Earlier same-day continuation — residual-only policy experiment

The user asked **“are you doing this!?”**. Clarified that the previous turn had finished and
no work was still running; then implemented and actually ran a larger stateful historical test.
Do not claim work continues in the background after a final response.

New `sequential_policy_replay.py` and `scripts/replay_sequential_policies.py` compare baseline,
protected premium sales, guarded next-deadline recourse and score-shape changes. Each arm starts
with the identical GW1 squad, then carries its own roster, purchase/sale values, bank, FTs and hits
through GW10. Only the current action is executed; all decisions replan at the next deadline.
Forecasts/outcomes are separate. Fits use earlier seasons only; dated fixture snapshots and
origin forecasts supply the future horizon. Selection uses 10,000 residual paths and fresh
10,000-path validation; validation may reject a frozen choice, never choose a new holdout winner.

`tournament.calibrate_residuals` now accepts explicit training rows/fixtures without mutating them;
`_simulate_player_outcomes` accepts an explicit fixture map and positional scales. Live defaults
are unchanged. These dependencies prevent accidentally using current fixtures/full-history
calibration in historical replay. The replay explicitly uses unit scales and zero terminal FT
value in all arms to avoid importing calibration fitted after the evaluation seasons.

Canonical completed receipt `data/research/points-priorities/sequential-20261021-v2.json`
(201.63s), SHA256 `91f91a2fced08dbac07028ddb2c2e4a09221b4b8f43d82335d3371db6cfaec54`.
V1 is retained. V2 adds rule/position/CLI hashes and score-shape coverage, without changing
policy logic, seeds or parameters. All 80 selected actions/lineups, state transitions and scores
exactly reproduced V1. All frozen input/code hashes matched on completion.

| Arm | 2024/25 GW1–10 net points | 2025/26 GW1–10 net points |
| --- | ---: | ---: |
| Residual-only baseline | 578 | 494 |
| Premium reinvestment | 578 | 494 |
| Guarded recourse | 615 (+37) | 486 (−8) |
| Score shape | 600 (+22) | 494 (0) |

All failed the predeclared screen of positive net lift in BOTH seasons. **Retain live production
authority**: no risk retune, no expanded-candidate promotion, no new simulator or WC/FH timing.
The recourse gain in 2024/25 included 24 fewer hit points (28→4); in 2025/26 it saved four hit
points but still lost eight net points. This is evidence against equating fewer transfers with
better decisions. The baseline has zero FT terminal value and is NOT the live champion.

Important scope: this is a prefix-fitted residual-world ablation, **not the promised full
production-matched three-world replay**. Historical component/goal calibration and historical
live lineup/market evidence still need matching; a single world cannot validate risk weights.
Chips, DGWs, full fixed-roster configuration search and whole-season timing are excluded. No
coefficients were retuned after seeing results; no pristine holdout/SOTA/proven-live-lift claim.
Keep priority 1 (minutes-model overhaul) and LLM work parked. Next substantial research remains
the genuinely matched multi-world evaluation, not repeating this ablation under a new name.

Validation: **800 non-LLM tests passed**, including available GPU checks; targeted Ruff and
tracked diff whitespace checks passed. A separate ledger verification checked all 80 arm-events'
purchase/sale-profit-floor arithmetic, bank, FTs, hits, roster legality and XI/bench/C/VC partition.
Score-shape coverage was complete for these windows (59,080 and 66,040 player-event/draw transforms;
zero skipped). No live forecast/decision mutation, fresh GW8 advice, FPL write, service start,
LLM execution/training or commit/push. Active GW7 receipt remains SHA256
`a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
Both replay processes and test suites completed; nothing from this turn is still running.

## Latest implementation — 21 October, priorities 2 → 3 → 4 → 5

The user explicitly parked a minutes-model overhaul: Semenyo's late lineup news may simply have
been unlucky. **Do not restart priority 1 or LLM work.** Focus on premium-sale/reinvestment,
points/risk objective, future transfers/chips and distribution-based decisions, in that order.
Existing role inputs/safety checks are unchanged; parking research does not disable those feeds.

Implemented and tested a first bounded pass:

- `generate_weekly_actions` accepts an explicit required-sale constraint, validated and combined
  with any protected role exit. `allocation_research_v2` automatically tests the two largest
  outfield selling values with legal one/two-transfer routes and up to two paid transfers. This
  matters when no FTs remain: the previous one-hit research limit could not examine reinvestment
  into another position. Sale proceeds, hits, bank and future FTs are real state constraints,
  not arbitrary points bonuses. These extra candidates still have no production authority.
- `policy_evidence.py` automatically aggregates matched **pre-deadline-frozen** risk and first-action
  continuation outcomes in the normal feedback loop. Original risk comparisons survive a timeout
  in unrelated expanded search; old v1 receipt interpretation is preserved.
- `weekly_policy_research_v2` retains a no-future-transfer child per ordinary root and tests every
  screened future move against that same-state hold, including after-cost/cross-world and paid-hit
  gates. A failed child restores its hold; it does not remove the current root. WC/FH branch
  mechanics remain diagnostic; this is not a promoted full chip/future-transfer policy.
- `distribution_policy_audit.py` tests rank-preserving single-fixture residual score remapping;
  appearance paths and component worlds unchanged. Discrete ties/covariance are not proven
  calibrated, doubles untouched, and this is research-only, not a promoted joint simulator.

Canonical audit `data/research/points-priorities/20261021-v2.json` completed in **58.02s**, with
stable source/code hashes, 10,000 paths per family for selection and 10,000 independent validation
paths. Command: `FPLAGENT_ACCELERATOR=cpu .venv/bin/python scripts/audit_points_priorities.py
--output data/research/points-priorities/NEW-NAME.json` (one line). CPU was chosen for this bounded
audit because an unrelated process already occupied about 28GB of GPU memory; it was not killed.
The first v1 audit is preserved; v2 corrects the two-hit search coverage, not tuned coefficients.

Results: frozen GW4–7 risk weights 0/0.1/0.25/0.5 had paired first-action deltas +4/0/0/−3 versus
0.25; the +4 is one event, not sequential season lift. Existing deterministic/shared-world future
planners' first actions scored −5/−8 versus production across those same events. No retuning earned.
On saved GW7 inputs, Bruno→Saka + Hall→Gabriel cost eight hit points and lost about2.01 weighted
horizon points versus roll; the Semenyo capital-release pair lost about4.02. These are **not GW8
transfer recommendations**. The expanded pool's best alternative was a no-transfer configuration,
only +0.03334 simulated points with conservative MC95 lower bound −0.00240: reject promotion.
42 future/chip branches completed; the new guard rejected a continuation with +1.934 weighted gain
but −1.917 in the raw-component world. Score-shape change retained the same ordinary action.

**789 non-LLM Python tests passed**, targeted Ruff passed. No active decision or forecast changed,
no FPL writes, no training, no services started, no commits. Active receipt remains GW7 SHA256
`a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`. No fresh GW8 run.
Next substantial work is a production-matched chronological sequential policy replay for the new
search/continuation/score-shape variants; the current audit does not provide it. Keep existing
risk setting, chip authority and simulator until that evidence supports a replacement. Do not
describe this as all four research programmes complete or as proven extra points.

## Product requirement — automated between-gameweek decisions

The user's latest clarification takes priority: **do not turn this into a manual analytics
workbench**. They want one actionable transfer/roll, chip/no-chip, XI/bench/C/VC plan from the
normal browser or CLI refresh. Scout is a research/benchmark reference to help improve that
automation, not a paid website they must consult or a dashboard they must interpret. Do not
assume Scout is better without matched evidence. Keep optional explanations, but prioritise
independently validated points-producing changes to the automated engine. LLM work stays parked.

`refresh_current_generation` now automatically rebuilds scouting after final direct/component
forecasts, using the exact checksummed official snapshot; **zero extra network calls**. Finalized
outcome scoring was already integrated. Optional scouting failures are recorded under
`refresh.scouting`, retain the old board and do not block a legal recommendation. Snapshot and
forecast timestamps remain separate. No model promotion or point-forecast change is implied.
A real saved-data GW8 evidence build covered 668 players/GW1–7 in 0.70 seconds with no active
decision mutation. Pipeline tests cover ordering, zero-network operation, failed-checksum
retention, concurrent forecast mutation and non-blocking diagnostic failure.
Final validation: **778 non-LLM Python tests pass**; targeted Ruff passes. Frontend lint/build,
six frontend tests and desktop/mobile Playwright review/scouting checks also passed earlier in
this batch. No new GW8 decision was generated. The temporary QA API/frontend were stopped.

## Latest implementation — 21 October, Scout-inspired gap closure

Read the [implementation follow-up](../reports/scout-product-audit-and-gw7-review-2026-10-21.md#implementation-follow-up-closing-the-first-gaps).
User asked to start closing the gap using useful Scout tools. New **Player scouting** navigation
supports optional A/B evidence comparison for all 668 players: recent/earlier xG/xA, minutes/starts, real
per-fixture DEFCON awards, set-piece order, six future fixtures, dated forecasts and blank/haul
probabilities. It uses independent official FPL data, not paid Scout values. Backend `scouting.py`,
GET `/api/v1/scouting`, POST `/api/v1/scouting/refresh`, CLI `fplagent scouting-refresh`.
No auth needed; normal weekly runs archive outcomes and populate it automatically. UI filters position/minutes and sorts
by chance creation, minutes or DEFCON. The comparison is evidence, not a legal transfer proposal.

`score_shape.py` implements a mean-preserving exponentially tilted historical score histogram plus
explicit DNP mass. Time-forward 2024/25 and 2025/26 tests cover 35,875 single-fixture forecasts. Both
folds improved overall, positional and top-three-candidate CRPS; top-three improvements about 6.9%,
coverage 50.0→90.4% and 48.2→88.6%. **Diagnostic-only activation earned**, not a points/decision-policy
promotion. It is used in scouting and future weekly frozen PMFs, not means, simulator worlds or
optimiser ranking. Old receipts unchanged. Reproduce with
`fplagent replay-score-shapes --activate-diagnostics`; artifact/data paths in report.
Missing/stale optional artifact falls back explicitly. Distribution cohorts remain separate;
mixed-method scoreboards cannot promote based on the aggregate. Historical seasons were used in
prior research: don't call them pristine untouched holdouts or claim SOTA.

Production correctness fix: residual simulator now preserves exact 0/1 appearance probabilities
instead of clipping to .001/.999. Also fixed sparse/out-of-support CRPS. A significant issue in the
previous review turn was discovered and repaired: GW7 outcomes had no bootstrap/fixture lineage.
Review now captures complete official inputs under its own root (not the production pointer).
Identical-outcome recaptures preserve existing immutable scores. A validation-only normal player
history rebuild succeeded for 4,551 rows/GW1–7. Do not overwrite production forecasts from this audit.

Next: conditional minutes/rotation and legal-policy score-distribution replay, then premium
sell/reinvestment and a timestamp-matched Scout benchmark. Neither is done by the new UI.
No GW8 decision run, no point-forecast changes, no LLM execution, no FPL writes or commits/pushes.
Active receipt still GW7 SHA256 `a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
QA API used `--lifespan off`, browser API calls were isolated; temporary API/Vite stopped afterwards.
Use the normal README startup commands, never that scheduler-disabled QA invocation for decisions.

## Latest audit — 21 October 2026, Scout access and GW1–7 feedback loop

Read [the season/Scout audit](../reports/scout-product-audit-and-gw7-review-2026-10-21.md) first.
The user supplied a locally stored Scout session after buying a month's membership and asked us
to review performance, inspect useful features and improve our app. Authenticated projection,
stats, DEFCON, market and rotation interfaces were inspected successfully. Do not print or copy
`.local/ffscout-cookie.txt`: it is an owner-only, git-ignored bearer credential, not a dataset.
Use permitted personal access only; no bulk proprietary-data extraction, model distillation or
subscription bypass was implemented. No saved FPL credentials were needed for public results.

Official entry 2754976 has **382 points**, overall rank **6,813,914**, after seven completed
gameweeks. Net scores: 35, 90, 43, 56, 62, 36, 60. The total is 34 below the sum of FPL event
averages. No hits or chips were used. Actual picks are reconciled independently from advice.

**Important correction to the older handoff below:** the last frozen GW7 advice was published
17 October at 07:53:23 UTC, not the earlier 16 October receipt. It started Bruno and Hall;
the actual team matched. Ordinary projection 52.4237, realized 60, average 59. Semenyo C,
Thiago VC, no further transfer, no chip. Current receipt SHA256:
`a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
It was verified unchanged during this audit. **No new GW8 recommendation was generated.**

Semenyo played 13 minutes/one point versus approximately 80 minutes/5.00 xP forecast. Any-appearance
probability was 95.5%, but the 1–59-minute bin only 5.6%. Scout also predicted him to start, so its
addition alone would not have caught this. Seven frozen squads' saved nominal 80% score intervals
covered 70.5% of 105 player outcomes and zero of seven captain outcomes (six below, one above).
This is a small, dependent sample and a serious calibration warning, not a causal explanation
or proof that all simulator outputs have the same defect. Distribution authority remains shadow.

Shipped in this turn:

- `gameweek_review.py`: fetch finalized public history/picks/live results; reconcile points and
  hits; score against frozen decisions; persist owner-specific cache and checksum evidence.
- `fplagent review-gameweeks --entry-id 2754976`; web GET `/api/v1/review` and explicit POST
  `/api/v1/review/refresh`. No optimisation, authenticated MCP requirement or account writes.
- New navigation **Season review** dialog: all 15 player outcomes, minutes errors, actual/advised
  scores, chips, bench, season reliability and clearly labelled overlapping hindsight gaps.
- Normal deadline pipelines now score all finalized events and refresh the prospective scoreboard.
  A diagnostic failure is recorded per event; it does not block publication or auto-promote models.
- Prospective scorer **v4**: latest pre-deadline receipt selection, exact chip execution/configuration
  lineage, missing new-style chip plans unscorable, and short-appearance diagnostics. V1–V3 preserved.
  Distribution and prospective dashboards consume v4. Select receipts by frozen time, not file mtime.
- Scout public team-news uses canonical URL, per-team conservative date, opponent/venue matching,
  no silent >11-player truncation, and team-semantic first-seen timestamps rather than ad/nonce
  changes. On Oct21 its page still showed GW7; all20 are correctly ineligible for GW8.

Saved data: `data/model/gameweek_review_v1/2754976/current.json` (22 verified evidence files),
and seven `data/model/prospective_weekly_scoring_v4/event-*/` receipts. The review includes
`forecast_health`; the UI displays it without pretending it proves future performance.

Validation: **756 non-LLM Python tests passed**, Ruff on changed data/scoring/test modules,
frontend lint/build, six frontend tests, and isolated Playwright desktop/mobile review QA.
Existing Starlette deprecation and frontend bundle-size warnings remain. QA screenshots are
under `data/web/qa/season-review-*.png`. The API used `--lifespan off` for QA so no scheduled
decision jobs ran; these temporary API/Vite processes were stopped afterwards. MCP was not started.
The normal app must be started through the documented workflow, not this QA-only invocation.

Next priorities: (1) minutes/cameo and captain-tail diagnosis, then historical/time-forward legal
decision replay; (2) permitted timestamped matched Scout benchmark during membership; (3) coupled
premium sell/reinvestment tests; (4) explanatory own-data player dossier; (5) market coverage and
ablation; (6) adaptive future transfers and WC/FH timing. The report defines the rationale and
promotion standard. These experiments are **not completed or promoted**. Bad rank is not grounds
to force players, copy another model or cherry-pick the tiny prospective sample. LLM work remains
parked. No FPL writes, model-weight changes, commits or pushes were made.

## Latest implementation — 16 October 2026, GW7 configuration search

The user challenged Bruno being benched, then explicitly requested integrating simulation-based
XI/bench/C/VC selection into normal weekly refreshes and reporting honestly if it disagreed with
the previously suggested XI. This is implemented in `weekly_configuration.py`, called from
`weekly_decision.py`. It is **not** promotion of the rejected wider-roster September experiment.

- Each existing transfer/roll/chip roster is searched across every legal XI, outfield bench order
  and starting captain/vice pair, at each event of the existing five-event horizon. Appearance-mask
  conditional point sums preserve correlations, legal autosubs, captain fallback and negative
  scores. Exact CPU/CUDA scoring agrees with the reference implementation, including BB/TC.
- Per-event non-dominated frontiers feed a joint horizon solve with the existing decay 0.88 and
  0.25 worst-world regret weight. Its reference is the fixed roster's own attainable frontier.
  Forecasts, model-world weights and the transfer shortlist are unchanged. This is not adaptive
  future-transfer planning or proof of a globally optimal football policy.
- Selection uses at least 50,000 paths per independent model family; the selected ordinary and
  operational chip routes are frozen before 100,000 fresh validation paths per family. Raw and
  anchored component worlds share samples; paired error calculations preserve their covariance.
  Gates require a positive paired MC95 lower bound versus the **same route's original lineup**
  (unless unchanged) and no world loss worse than 0.05 discounted points. These are simulation
  precision checks, not observed/historical performance gains or forecast confidence intervals.
- Failed validation restores the entire original candidate set and selection. It does not pick
  a replacement on holdout data, loosen thresholds, or force Bruno to start. Both proposed and
  original lineups, hashes, seeds and the outcome are saved under
  `diagnostics.configuration_optimisation`. Browser/CLI explanations expose the fallback.
- New BB/TC receipts include an `execution_plan` binding the chip's exact lineup and armbands to
  its transfer parent. Browser/CLI must not combine a chip configuration with an unrelated ordinary
  winner. This fixes the September display-contract issue for new receipts. WC/FH timing authority
  remains rejected; legal squad-chip mechanics are still tested.

Validation: **731 non-LLM Python tests pass**, six frontend tests pass, and the frontend build passes
(existing bundle-size warning). One outdated test was corrected: a promoted bench player may be
the recommended vice-captain. No LLM execution/training, FPL account writes, commits or pushes.
Saved credentials must never be read into chat/logs; an expired MCP session was renewed through
the existing saved-login endpoint, then the user's completed Schade → Groß transfer was synced.

The first integrated pass, before the post-transfer sync, selected the previously suggested Bruno
and Hall configuration in its selection sample but **rejected it on holdout**: +0.01885 weighted
discounted points, MC95 interval −0.00640 to +0.04411; residual-world loss −0.09125. The old lineup
was correctly retained. Do not describe the earlier advice as a proven improvement. Consult the
latest published receipt for the final post-transfer outcome rather than reusing this comparison.

Two operational issues were found during live validation and corrected: CLI timeouts during an
already-running job now retry only read-only progress requests within the user's wait limit, and
the material-change probe ignores only `game_config.status.price_change_last_updated`. Real
`elements.now_cost`, player role/news, rules, scoring, price-change deadlines and unknown status
fields remain fingerprinted. Two real consecutive snapshots differed only in that bookkeeping
timestamp and wrongly launched an extra tournament. No forecast/model data was excluded by this
fix. Regression tests cover both retry bounds/no POST retries and real-price/rule changes.

**Final live outcome:** published **16 October, 15:33 BST**, with official evidence observed at
15:27 and the authenticated post-Groß squad synced at 15:21. Action `A-efd4629411-0`: no additional
transfer, no chip, 3-4-3, Semenyo C and Igor Thiago VC. XI: Donnarumma; Truffert, Tarkowski, António
Silva; Groß, Semenyo, Mbeumo, Gibbs-White; Evanilson, Igor Thiago, Calvert-Lewin. Outfield bench:
Hall, Bruno Fernandes, N. Williams; reserve GK Verbruggen. Saved robust projection **52.3703**;
individual raw xP labels do not sum to this risk-adjusted projection.

The selected deeper plan initially starts Bruno and Hall, matching the earlier conversational
suggestion, but also changes future configurations in GW8/10/11. The frozen five-event package
fails holdout: weighted +0.012753 points, paired MC95 −0.012658 to +0.038164; residual −0.094383,
anchored component −0.032913, raw component +1.495113. Thus `retained_original` is intentional.
This does not establish that Bruno is a clearly inferior football pick; it prevents claiming an
unproven revised plan is better. 35 proposed routes, 87 cached frontiers, 31,581,000 legal
combinations represented before exact dominance pruning; CUDA backend used.

Published and immutable archived receipt bytes match SHA256
`9f457b3e261ed1b8be7b186bc030907d51a823771cba39f0d065fc00e07a40e4`.
Archive:
`data/decisions/weekly/event-7/89e461bf4575802587ef3d865d5c155ae6d4709fde9bf60947f0502d8012c54b.json`.
The browser read model and CLI were checked against the receipt for exact XI, bench order,
captain, vice, transfers, chip and checksum agreement. API restarted on the new probe code:
PID 453200/session 16072, port 8000; Vite session 62959, port 5173; MCP PID 281519, ports 8020/8021.
After restart the scheduler is `covered`, correctly records 15:33 validation and schedules its
next cadence check for 17:33 BST. Later material news may advance that check normally.

## Latest refresh/login handoff — 11 September 2026

Read [GW4 refresh and saved-login status](../reports/gw4-refresh-2026-09-11.md) first. Automatic
owner-only saved-file login works, manager state is freshly synced and the latest refresh was
published/archived at 08:13:55 BST. **A newly observed display mismatch remains:** the joint chip
decision selects Richarlison → Evanilson + Bench Boost, whereas the transfer panel displays the
separate Maguire → Muharemović no-chip winner. The user was warned not to combine these plans and
asked to approve the display/contract fix. Do not present the current combined UI as execution-ready
or change the algorithm's selection merely to hide this mismatch. No saved credentials may be read
into logs/chat. Service IDs, receipt hashes and the exact diagnosis are in the report.

## Latest completed deep audit — 9 September 2026, afternoon

Read [the deeper-search audit and decision](../reports/weekly-deep-search-2026-09-09.md) before the
earlier release notes. User requested materially deeper search. New `weekly_deep_search.py` and
`exact_configuration.py` test 4/8/16/32 shortlist depths, all legal fixed-roster XI/bench/C/VC
configurations over five events, joint horizon MILPs and two untouched 25,000-path-per-family
holdouts. The completed run took 629.27 seconds: 100 legal roster routes and 540 frozen policies.
Both holdouts rejected the expanded Gonzalo winner (weighted losses −0.249/−0.302 to Evanilson).
Do not loosen gates, select another policy on those holdouts, or silently enable this rejected
selector in normal app refreshes. The exact command and remaining objective/recourse priorities are
in the report. The deeper audit is reusable; ordinary production authority remains unchanged.

Current API verification: event 4 ready, `A-5329ac8f23-1`, Richarlison → Evanilson, Bruno C,
Szoboszlai VC, no chip, 53.8743 displayed GW4 xP. Refresh `refresh-v1-f98e6b71c4212a2c` completed
at 14:52:59 BST. Active and archived weekly bytes still hash to
`cc14d4ea02e7798e2703ad70f0d29989f5589b60dcfdff3246b3e69da069478d`.
API PID 493127/session 55531 on 8000, frontend 5173, MCP 8021/login 8020 remained available.
No refresh or deep worker remains from this audit. Code changes are not automatically loaded into
that API process; a future engine deployment needs a controlled restart and transactional refresh.
665 non-LLM Python tests and six frontend tests pass; frontend build passes with the existing bundle
size warning. New engine/script tests lint clean. No FPL writes, LLM work, commits or pushes.

## Latest deployment review — 9 September 2026

Read [the concluded promotion/rejection decisions](../reports/points-first-promotion-decisions-2026-09-09.md)
first. User explicitly requested that we decide on merit, not leave everything pending in shadow.
Rejected versions may collect frozen outcomes but have no automatic path to authority.
`policy_release.py` enforces the release boundary in weekly receipts. The new v4 selector computes
its risk benchmark only over admissible actions; the old all-candidate ranking remains an audit.
Its invariance regression failed before the fix and passes afterward. Frozen GW2/GW3 outcomes stay
133 net points; do not claim a measured points gain. v3/v4 scoring compatibility is tested.

Correctness/measurement fixes and the existing eligible BB/TC policy are included. Deterministic
recourse, shared-world v1 recourse, new WC/FH timing, role-shift v1, expanded allocation v1 and
risk-weight retuning are rejected for this release for the specific reasons in the report.
This is not a rejection of researching better successor versions. No LLM or FPL-write work.
The report's final handoff supersedes the service IDs and publication timestamps below.

## Latest addendum — 9 September 2026

**Latest batch:** read [round-two validation and publication](../reports/points-first-validation-round2-2026-09-09.md)
before the earlier morning result below. Shared-world two-deadline transfer/chip plans, seven
allocation proposal families and a failed role-change challenger are now diagnostic integrations.
The exact state engine now supports authenticated/witnessed real-club overflow: hold is legal,
the next transfer must repair, and Free Hit restores the original state. A full 76-event chip-state
audit passes after explicit reconstruction/certification of missing historical blank holdings.
These are not proofs of optimal timing or adaptive points lift. All research receipts preserve
`decision_authority: false`; live BB/TC eligibility is unchanged and WC/FH remain research-only.
The final publication and service details are in the round-two report. Do not restart LLM work.

Final round-two refresh `refresh-v1-8132a9853a041bd9` published at **13:51:48 BST** in 128.85s:
Richarlison → Evanilson, Bruno C, Szoboszlai VC, no chip, **53.87 GW4 xP**. Manager state was freshly
synced at 13:49 BST. API PID 451200 (session 27999) is on 8000; frontend 5173 and authenticated
MCP 8021/login 8020 remain running. 635 non-LLM Python tests, six frontend tests, build/lint and
both browser scripts pass. Browser incoming-player evidence was also corrected after publication;
engine fingerprint/active decision bytes are unchanged. No FPL account writes or LLM runs.

Do not hide research disagreement: shared-world continuation prefers rolling; the final expanded
candidate-set diagnostic prefers Richarlison → Gonzalo at risk weight 0.25. Neither is promoted.
The ordinary validated selector still selects Evanilson. Read the report's discussion of
candidate-relative regret and the missing promotion evidence before changing that authority.

**We are now preparing GW4.** Read the [current ordered programme](decision-improvement-roadmap-2026-09-09.md)
and [adaptive-transfer follow-up](../reports/adaptive-transfer-replay-2026-09-09.md) before the older
GW3 status below. The latest standard refresh published at **12:46 BST**: Richarlison → Evanilson,
Bruno captain, Szoboszlai vice, no chip; 53.89 GW4 xP. Exact IDs, hashes, full lineup and service
state are in that report; runtime receipts supersede these dated notes.

The admissible-runner-up selector fix and forward-only BB/TC calibration are live. Next-deadline
recourse is diagnostic-only: the paired opening-ten-event test scored +58 and −2 in the two recent
folds and failed activation. It now rejects incomplete solver comparisons and freezes its first
action for prospective scoring. WC/FH joint continuation and tactical-role validation remain major
unfinished priorities. LLM work remains parked. The sections below retain the 3 September context.

**Prepared:** 3 September 2026, Europe/London  
**Purpose:** durable context for a new AI agent or engineer continuing the project  
**Current product phase:** in-season, preparing the GW3 decision  
**North star:** maximise Lewis's total FPL points and mini-league results through fresh,
point-in-time evidence and legal, robust decisions

This document is the recommended starting point for a new session. It records what the project is,
what has actually been implemented, the current decision state, what is and is not authoritative,
how to run and verify the system, and the next work in priority order. Read the linked specialist
documents when changing a subsystem, but do not assume their dated status paragraphs still describe
the live season.

## 1. Executive summary

FPLAgent began as a Gameweek 1 squad picker and has become a local, single-manager, season-long FPL
decision workspace. It now combines:

- immutable official FPL and historical data collection;
- the project's own player expected-points forecasts, with FPL's `ep_this` and `ep_next` explicitly
  forbidden as model inputs;
- independent match-component simulations and a direct forecast family;
- legal optimisation of squads, transfers, hits, starting XI, bench order, captain and vice;
- exact manager state including free transfers, bank, purchase/selling prices and chips;
- a five-deadline receding decision horizon with transfer option value;
- robust shared-world comparisons against the mandatory “roll” action;
- current predicted-lineup evidence and official participation status;
- betting-market goal and clean-sheet evidence with deliberately bounded authority;
- exact Bench Boost, Triple Captain, Wildcard and Free Hit counterfactuals;
- fail-closed, checksum-bound staging and publication;
- a phase-aware React/FastAPI web application;
- local authenticated, read-only FPL squad sync through the sibling MCP server;
- screenshot import through a multimodal Qwen model plus deterministic player resolution;
- a grounded conversational layer over deterministic tools; and
- research reports, a technical white paper and a Remotion decision-story video.

The project is not finished and should not claim that its live decision policy is globally state of
the art. It has a strong research and engineering foundation, but only prospective 2026/27 scoring
can establish whether it consistently adds points. Several current validation failures and one
weekly/GW1 status-boundary bug must be fixed before adding more modelling complexity.

## 2. Product intent and non-negotiable decisions

The following requirements came directly from the product owner and should survive future sessions:

1. **Points are the reward function.** UI polish, chat quality, team value and model novelty matter
   only insofar as they help make and understand better FPL decisions.
2. **Use our own xP.** Never use official FPL `ep_this`, `ep_next` or an alias of those values as a
   production feature, fallback or tie-breaker. They may remain in lossless raw snapshots.
3. **Every decision starts from all 15 players.** Starting-XI, bench, captain and transfer logic must
   allow a current bench player to become a starter or captain. Do not optimise only the stored XI.
4. **Compare against rolling.** A transfer route must beat the best optimised no-transfer route after
   hit costs, lineup/captain changes, future flexibility and uncertainty. Never compare a transfer
   only with the manager's currently saved lineup.
5. **Re-plan every deadline.** A five- or eight-week horizon is a valuation window, not a promise to
   execute a fixed sequence for that long.
6. **Freshness and provenance are product features.** A failed run preserves the previous valid
   decision and must say why. Missing or incoherent inputs are not silently replaced with guesses.
7. **Evidence earns authority.** New models and sources enter as challengers and receive production
   weight only after time-forward forecast tests and legal decision replays pass declared gates.
8. **The LLM does not own arithmetic or live facts.** It interprets intent and explains structured
   receipts. Forecasts, legality and recommendations come from deterministic services.
9. **LLM improvement is parked.** Do not run another LoRA training/evaluation programme unless Lewis
   explicitly reopens it. The existing model service remains useful to the product.
10. **The FPL integration is read-only.** The app does not submit transfers, lineups or chips. Lewis
    applies recommendations manually in the official game.
11. **Current scope is local and single-user.** Do not expose the local MCP login service or its
    in-memory session as a hosted multi-user architecture.
12. **Be transparent about uncertainty and mistakes.** Recent Haaland, Watkins, Richarlison, bench
    ordering and UI-delta challenges exposed real gaps. Player-level spot checks and omission
    reports are required parts of decision QA, not optional narrative.

## 3. System architecture

```text
Official FPL + historical archives + manager snapshot + independent sources
                                │
                                ▼
                  immutable raw snapshots and checksums
                                │
                                ▼
             DuckDB/Parquet point-in-time features and schedules
                                │
                     ┌──────────┴──────────┐
                     ▼                     ▼
          direct player xP family   match-component family
                     └──────────┬──────────┘
                                ▼
       legal route generation: roll / transfers / hits / chip branches
                                │
                                ▼
       XI + bench + captain optimisation in shared simulated worlds
                                │
                                ▼
      robust regret, downside, roll comparison and publication gates
                                │
                                ▼
             immutable weekly decision receipt and web read model
                                │
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
        React decision workspace      grounded Qwen explanation
```

### Repository map

| Area | Location | Responsibility |
| --- | --- | --- |
| Data ingestion | `src/fplagent_data/` | Official/history downloads, snapshots, event outcomes, market telemetry, Understat and participation sources |
| Forecast/decision engine | `src/fplagent_engine/` | Features, models, simulation, optimisation, transfers, chips, evidence and scoring |
| LLM integration | `src/fplagent_llm/`, `llm/` | Corpus/evaluation code, Qwen loading, tools, screenshot extraction and parked LoRA work |
| Application API | `src/fplagent_web/` | FastAPI workspace, refresh orchestration, MCP gateway, profile, uploads and Qwen gateway |
| Frontend | `web/` | React/Vite season workspace and dialogs |
| Decision film | `episode/` | Remotion project and rendered knockout-style explanation |
| Durable architecture docs | `docs/` | Long-lived contracts and operator guides |
| Research/evidence | `reports/` | Dated tests, audits, white papers and rendered media |
| Generated runtime state | `data/` | Raw evidence, DuckDB, features, models, manager state and decision receipts; mostly ignored by Git |

The main Python package is managed by `uv` and targets Python 3.12. The web client uses npm. The Qwen
runtime has an intentionally separate environment in `llm/.venv` because the Unsloth/PyTorch stack
is more volatile than the deterministic engine.

## 4. Local service topology and startup

The complete local product uses five ports:

| Port | Process | Notes |
| ---: | --- | --- |
| 5173 | Vite/React | User-facing application |
| 8000 | FPLAgent FastAPI | Workspace API and OpenAPI docs |
| 8011 | Qwen sidecar | Private local model health/chat service |
| 8020 | MCP login web service | Embedded inside FPLAgent; `/` itself may not be the app in older MCP builds |
| 8021 | MCP streamable HTTP | Backend-only endpoint at `/mcp` |

Install once:

```bash
cd /home/lewis/Workspace/fpl-agent
uv sync
bash llm/install_qwen35.sh
cd web
npm install
cd /home/lewis/Workspace/fpl-mcp-server
uv sync
uv run playwright install chromium
```

Run the sibling MCP server in terminal 1:

```bash
cd /home/lewis/Workspace/fpl-mcp-server
FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src uv run python -m fpl_server.main
```

Run FPLAgent in terminal 2:

```bash
cd /home/lewis/Workspace/fpl-agent
bash scripts/run_local_web.sh
```

Then open `http://127.0.0.1:5173`. The launcher starts the API, persistent Qwen sidecar and Vite.
Its shutdown handler sends TERM, waits at most eight seconds, then kills a child that will not exit.

As of this handoff, **none of these services is running**. The current decision is persisted on
disk, but a future session must start both terminals to reconnect and refresh.

Health checks:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/v1/workspace
curl -s http://127.0.0.1:8000/api/v1/workspace/refresh
curl -s http://127.0.0.1:8000/api/v1/workspace/refresh/schedule
curl -s http://127.0.0.1:8000/api/v1/market/telemetry
curl -s http://127.0.0.1:8011/health
```

Credentials are entered into the MCP-owned page embedded in the app. React and FastAPI must never
receive or store them. The authenticated MCP session is currently in memory, so restarting MCP
requires login again. The saved entry ID is not authentication.

## 5. Data foundation

The local data directory is roughly 2.3 GB and the ignored LoRA/model-output directory is roughly
9.6 GB. The principal database is `data/fpl_history.duckdb`; the latest refresh reported about
14.5 million rows and 449 views.

### Core sources

- **Official FPL bootstrap and fixtures:** current player catalog, prices, availability, teams,
  events, fixtures and rules.
- **Official event-live:** finalized points, minutes, xG, xA, BPS and defensive contribution inputs.
  An event is admitted only after FPL marks it finished and data-checked.
- **Authenticated manager state through MCP:** the current 15, selected lineup, bank, purchase and
  selling values, free transfers, existing cost and chip inventory.
- **Historical FPL archives:** Vaastav, Solio, FPL Genius factual trails and veteran-manager
  spreadsheets, with source-specific caveats.
- **Betting markets:** Football-Data historical pre-closing prices and a live anonymous delayed
  Betfair Exchange collector for Match Odds and over/under 2.5.
- **Predicted lineups:** RotoWire and Fantasy Football Scout, independently timestamped and mapped.
- **Understat:** immutable prior-season player npxG/xA/shot/chance-chain evidence for challenger
  tests.
- **SofaScore:** tested as a challenger, lost the untouched legal policy replay and has zero weight.
- **FBref:** not used as a current advanced-event dependency; the former advanced feed and access
  contract are unsuitable.

### Current source authority

| Evidence | Current authority | Important qualification |
| --- | --- | --- |
| Official FPL current data | Production | Schema/completeness/freshness gates apply |
| Final official event-live outcomes | Production | Only final, data-checked events enter history |
| Authenticated manager snapshot | Production | Must be aligned to the decision deadline |
| Direct project xP | Production champion | FPL-authored xP is denied |
| Component player models/simulation | Production scenario family | Deliberately independent failure mode |
| Online hierarchical team strength | Production | Updated only from knowable prior results |
| Live predicted lineups | Bounded operator override | Current use is not yet prospectively promoted |
| Betfair rates in weekly decisions | Diagnostic/paired shadow | Current weekly direct feature weight is exactly zero |
| Understat player features | Shadow, 0% | Development selector chose no blend |
| Return-distribution captain model | Shadow | Promising test mean but downside gate failed |
| Lead-specific participation model | Shadow | Passed screens, failed the complete decision funnel |
| Form-reversion policy | Diagnostic/challenger | Prevents naive points chasing; does not silently override champion |
| Price movement model | Diagnostic, 0 authority | Team value alone cannot justify a transfer |

The latest GW3 pipeline captured complete Betfair books for all 10 GW3 fixtures and all 10 GW4
fixtures. GW5–GW7 were not yet available. This evidence is archived and shown in diagnostics, but
the weekly market-feature policy remains inactive because its continuous held-out transfer replay
missed the declared downside bound.

The latest participation generation has fresh RotoWire data but stale Fantasy Football Scout data.
RotoWire is therefore the only eligible source. The model currently applies bounded one-sided
start/bench adjustments through an explicit operator override. The receipt says this clearly:
prospective scoring has not yet earned automatic authority. A future agent must not rewrite this as
“two-source consensus”.

## 6. Forecasting and simulation

### Direct player forecast

The production forecast is a position-specific XGBoost hurdle system:

```text
conditional points if the player appears
                    ×
probability distribution over DNP / 1–59 / 60–89 / 90+
                    =
our expected FPL points
```

Features include lagged FPL outcomes, minutes/starts, official xG/xA, goals/assists, clean sheets,
BPS, defensive contributions, set-piece order, price, availability, venue, rest and opponent-adjusted
team strength. Current-event results are labels, never inputs for their own deadline.

The current direct model is `forecast_v3_opponent_adjusted`, trained 3 August 2026. The latest
inference generation was built from the 3 September official snapshot for events GW3–GW7 and
contains 561 players × 5 events = 2,805 rows.

### Component family

The independent component family models goals, assists, clean sheets, saves where supported, bonus,
cards and defensive contributions. It simulates match outcomes and correlated player returns rather
than adding independent mean xP values. This is important for clean-sheet stacks, captain tails,
autosubs, blanks and doubles.

The current component model version is `component_event_v2`. Its 2026/27 outfield BPS correction is
active; goalkeeper corrections remain conservative where source events cannot support them.

### Team strength and fixtures

Team attack and defence use an online hierarchical Poisson model with promoted-team priors, venue
effects and time decay. Fixture rates produce expected goals and clean-sheet probabilities. Market
rates are an independently measured challenger, not an unquestioned replacement.

Each fixture in a Gameweek is scored separately. A blank contributes zero fixtures. A double has
two appearance, clean-sheet, concession, bonus and return opportunities, including double-specific
rotation uncertainty. The current schedule receipt has all 380 fixtures assigned and no presently
known blank/double exceptional team-events.

### Distribution and robustness

The engine carries player score probability mass functions with explicit DNP mass. It evaluates
actions in shared random worlds so differences have much lower noise than unrelated simulations.
The decision gate considers:

- after-cost mean gain versus roll;
- residual and component scenario families;
- paired confidence intervals;
- downside/CVaR and worst-scenario behaviour;
- robust regret against other legal actions;
- lineup, captain and autosub consequences; and
- retained transfer flexibility.

## 7. Optimisation and decision policies

### Preseason/GW1 path

The GW1 system used legal MILP seeds, hundreds of thousands of one-swap/local candidates, distant
MILP restarts, evolutionary candidates, residual screens, component holdouts, a global robust
search, an eight-week horizon audit and cross-family synthesis. It also ran exact bench, formation,
captain, role-risk, one-swap and top-player-omission audits. That work is preserved for research and
the white paper, but GW1 is no longer the active production phase.

### Weekly path

The in-season pipeline is now the operational centre:

1. Refresh or reuse an immutable official snapshot.
2. Archive any newly finalized event outcomes and rebuild current-season history.
3. Collect predicted-lineup and market evidence.
4. Build point-in-time features from the next actionable event across the chosen horizon.
5. Run direct and component forecast inference.
6. Derive an exact manager-state contract from the authenticated snapshot.
7. Generate roll, one/multiple free-transfer and bounded hit routes.
8. Generate protected routes for actionable retained role risks, rather than letting candidate
   pruning hide an obvious sale.
9. Optimise every route's XI, bench order, captain and vice from all 15 players.
10. Simulate identical actions across residual and component worlds.
11. Evaluate every legal chip branch and retained-chip calendar.
12. Compare the selected route against the mandatory optimised roll route.
13. Stage the decision, revalidate hashes/evidence and atomically publish it.
14. Preserve the previous valid decision on any failure.

The normal command is:

```bash
uv run fplagent deadline-run --manager-entry-id YOUR_ENTRY_ID
```

Use `--reuse-latest-official` only for a deliberate deterministic replay. Useful bounds are exposed
by `--horizon`, `--alternatives-per-transfer-count`, `--max-total-transfers`,
`--max-paid-transfers`, `--residual-simulations` and `--component-simulations`.

### Horizon policy

Preseason uses a longer view; the current weekly decision uses GW3–GW7, a five-deadline receding
horizon. Future points are discounted and the route is reconsidered at every deadline. Historical
replay tested 1/3/5/8-week policies and did not justify replacing the conservative incumbent merely
because one shorter policy won a development selector. Do not tune horizon length against the
current recommendation without a point-in-time season replay and a sealed test.

### Hardware routing

XGBoost training/inference uses the RTX 5090 through CUDA/CuPy. Independent HiGHS MILP policies use
up to 12 isolated CPU workers; role scenarios use up to four processes. The current sparse autosub
and candidate kernels stay on CPU because production-shape benchmarks found GPU transfer/setup
slightly slower. Environment controls are:

```text
FPLAGENT_ACCELERATOR=auto|cpu|cuda
FPLAGENT_POLICY_WORKERS=<positive integer>
FPLAGENT_ROLE_WORKERS=<positive integer>
FPLAGENT_GPU_MIN_MULTIPLIES=<integer>
```

Do not force every operation onto the GPU for appearance's sake. Benchmark wall time and require
byte-equivalent decisions.

## 8. Chip strategy

The 2026/27 rules provide two of each chip: one Wildcard, Free Hit, Bench Boost and Triple Captain
for GW1–19 and another set for GW20–38. Only one chip may be used in a Gameweek. The first-half set
expires at GW19.

The engine models:

- exact Bench Boost scoring for all 15;
- exact Triple Captain scoring with vice fallback;
- a permanent unlimited-transfer Wildcard squad;
- a one-event Free Hit squad followed by restoration of the prior squad and transfer bank;
- one-chip-per-event calendar collisions;
- current versus retained opportunity value before expiry; and
- known blank/double schedule state without inventing future rearrangements.

Chip strategy v2 uses a finite visible horizon plus a historically calibrated terminal retained
value. Recent complete seasons receive recency weights. BB/TC timing has passed its historical
promotion gate but must still pass live uncertainty, schedule and paired-downside gates. WC/FH are
exact visible counterfactuals but have not earned automatic timing authority.

The current GW3 operational decision is **NO CHIP**. The UI should distinguish this authoritative
call from attractive future or research-only raw uplifts.

Read [`chip-strategy-v2.md`](chip-strategy-v2.md) before changing chip logic.

## 9. Current persisted GW3 decision

The latest successfully published weekly receipt is:

```text
data/decisions/2026-27-weekly-current.json
version: weekly_decision_synthesis_v3
created: 2026-09-03 15:56:59 UTC
decision event: GW3
selected action: A-dfba4d364b-2
roll comparator: A-5954bed386-0
```

### Recommended action

- Use both free transfers; no hit.
- Sell Lacroix for António Silva.
- Sell Gakpo for Gibbs-White.
- Play 3-5-2.
- Captain Szoboszlai.
- Vice-captain Gibbs-White.
- Retain all chips.

Recommended XI, with current mean xP:

| Player | Position | xP |
| --- | --- | ---: |
| Donnarumma | GK | 4.07 |
| Truffert | DEF | 3.53 |
| N. Williams | DEF | 4.48 |
| António Silva | DEF | 3.55 |
| Szoboszlai (C) | MID | 6.00 before doubling |
| Semenyo | MID | 5.14 |
| Bruno Fernandes | MID | 5.19 |
| Mbeumo | MID | 4.51 |
| Gibbs-White (VC) | MID | 5.45 |
| Igor Thiago | FWD | 5.11 |
| Calvert-Lewin | FWD | 4.08 |

Bench order:

1. Maguire — 3.16 xP
2. Tarkowski — 2.63 xP
3. Richarlison — 1.66 xP, 53.3% play probability, 23.9 expected minutes
4. Verbruggen — 3.38 xP, reserve goalkeeper

The selected GW3 projection is 56.839. The best optimised roll route is 55.995, so the **pure GW3
action advantage is only +0.844 points**. The larger case is multiweek:

| Event | Selected minus optimised roll |
| ---: | ---: |
| GW3 | +0.844 |
| GW4 | +0.269 |
| GW5 | +3.155 |
| GW6 | +1.853 |
| GW7 | +1.926 |

The unweighted total is +8.047; the discounted decision utility improves by about +6.08. The
published robust receipt reports +6.205 weighted mean gain versus roll, +6.112 in its worst model
scenario and a residual paired 95% interval of +6.004 to +6.220.

Lacroix to Silva is principally a structural move. Silva releases £1.0m, funds the £0.9m
Gakpo-to-Gibbs-White upgrade and leaves £0.1m. For GW3 Silva's robust 3.513 replaces Maguire's 3.157
in the XI, while Gibbs-White's 5.431 replaces Gakpo's 4.943. This exactly explains the approximately
+0.844 immediate route edge. Do not describe the entire +6.64 saved-lineup delta as transfer gain.

### Richarlison exception handling

The engine now detects retained severe role risks and forces exact sale alternatives into the same
shared-world ranking. Richarlison is not being ignored:

- current price £5.9m, bought at £6.0m;
- last minutes 0;
- single-source predicted bench;
- 53.3% play probability and 23.9 expected minutes;
- best forced-sale route is Richarlison to Igor Jesus plus Mbeumo to Gibbs-White;
- that route ranks third and is approximately 0.867 weighted points behind the selected action.

The current model therefore retains Richarlison despite flagging him. This is a live watch, not an
assertion that he is a good asset. Fresh role evidence, a price move or a changed replacement price
can change the result at the next refresh.

### Publication state

`data/manifests/fpl-weekly-deadline-pipeline.json` says the GW3 pipeline was published successfully.
It is bound to the official snapshot, direct/component forecasts, manager-state contract, runtime
rules, chip calibration, schedule and market receipts. The decision was generated from finalized
GW1 and GW2 event history.

## 10. Web product and UX

The UI is an original “decision room” rather than an FPL clone. Its current major journeys are:

- silent account sync and decision refresh on open;
- `Your FPL squad` versus an authoritative `Recommendation` view;
- a pitch and list view for the complete 15;
- transfer/lineup/captain/chip decision cockpit;
- player focus with xP, minutes, play probability and participation evidence;
- source and checksum evidence dialog;
- manual refresh with persisted progress and single-flight behaviour;
- legal constrained preseason squad builds;
- screenshot upload, extraction, deterministic validation and explicit confirmation;
- manager identity/MCP connection; and
- grounded chat over the active decision.

The backend should continue a refresh if the browser is closed; only stopping the API process ends
it. Repeated refresh requests join one in-process job. Unchanged content can reuse a prior generation.

The primary UI files are `web/src/App.tsx`, `web/src/components/DeadlineCockpit.tsx`,
`DecisionRail.tsx`, `WeeklyDecisionPanel.tsx`, `SquadPitch.tsx` and `web/src/index.css`.

### Known UX integrity issue

The workspace currently exposes a +6.64 comparison between the saved FPL lineup and the full
recommended configuration. That figure includes lineup, bench and armband correction and is not the
transfer route's gain over an optimised roll. The UI needs two explicit labels:

1. **Saved team configuration → recommended configuration**; and
2. **Optimised roll → recommended action**, with the transfer's honest immediate and horizon edge.

This distinction should be fixed before further visual embellishment.

## 11. MCP integration

The sibling repository is `/home/lewis/Workspace/fpl-mcp-server`. FPLAgent uses only a narrow,
read-only gateway:

- authentication status;
- begin embedded web login;
- poll login completion; and
- get the authenticated manager snapshot.

The login was updated for the Premier League OAuth/PKCE flow and Playwright browser installation.
An earlier cross-event-loop failure was fixed by ensuring async clients, locks and events are not
shared between the web login loop and MCP transport loop.

Do not paste credentials or bearer/refresh/ID tokens into source, docs, test output or Git. Tokens
previously pasted into chat should be treated as compromised/expired and never reused as fixtures.

## 12. LLM and multimodal work

The base is `unsloth/Qwen3.5-4B`, a multimodal model. LoRA adapters were genuinely trained locally
with Unsloth/PEFT on the RTX 5090; the base remains separate and the adapter is attached at runtime.
Important outcomes:

- V3 is the best current screenshot adapter.
- Later text/chat adapters did not consistently beat base Qwen on locked routing, schema, response,
  qualitative and vision gates.
- Base Qwen plus grounded deterministic tools remains the promoted text-chat configuration.
- No more LoRA work should run without explicit user authorization.

The screenshot path is intentionally multimodal:

```text
image → Qwen vision extraction → current player catalog resolution
      → deterministic squad legality → user confirmation
```

OCR can be added as cross-check evidence, but should not replace the visual model by default. The
LLM must never invent player IDs or silently confirm an illegal team.

The LoRA artefacts under `llm/outputs/`, model environments and generated LLM data are ignored by
Git. Preserve them locally, but do not commit or push them.

See [`fpl-llm-architecture.md`](fpl-llm-architecture.md) and `../llm/README.md` for the exact parked
state.

## 13. Research and communication artefacts

The canonical methodology document is:

- `reports/fplagent-algorithm-technical-whitepaper-standalone.html`

Its maintainable source is:

- `reports/fplagent-algorithm-technical-whitepaper.md`
- `scripts/build_algorithm_whitepaper.py`

The decision episode is under `episode/`, with rendered outputs in:

- `reports/fplagent-decision-episode.mp4`
- `reports/fplagent-decision-episode-poster.png`

The episode was redesigned from lecture slides into a knockout narrative with named candidate
squads, more diverse contenders and full-team visualisation. It is supporting communication, not
decision evidence.

The white paper contains a stale example rebuild command (`pipeline-gw1 --force`) that is not in
the current CLI. Correct it the next time the paper is rebuilt; current production commands are
`gw1-deadline-run` for historical preseason reproduction and `deadline-run` for in-season work.

## 14. Verification state at handoff

Commands executed on 3 September 2026:

```bash
uv run ruff check src tests llm
cd web && npm run lint
cd web && npm run build
uv run pytest -q
```

Results:

- Python lint: **pass**.
- Frontend lint: **pass**.
- Frontend production build: **pass**, with a non-blocking 531 kB bundle-size warning.
- Python tests: **602 passed, 16 failed**.

The failing suite is a release blocker. Failure clusters are:

1. **Market stale-generation fallback (2):** fresh ready market evidence is not retained in two
   mocked transient-failure paths.
2. **Parked LLM fixtures/corpus (5):** a screenshot benchmark player is no longer selectable in the
   moving current catalog, related resolution scores fail, and one synthetic corpus prompt is
   duplicated.
3. **Calendar-dependent web tests (2):** assertions still assume GW1/GW2 while the live official
   database has advanced to GW3.
4. **Workspace historical-time isolation (6):** tests instantiate the default live manager
   repository, whose active snapshot was created after their historical `now`; they need injected
   fixture state rather than the moving local decision.
5. **Preseason model-squad exposure (1):** current phase/data changes leave an old preseason
   expectation without a model squad.

Fix the tests by isolating clocks, catalogs and repositories. Do not weaken production freshness or
point-in-time checks merely to make dated fixtures pass.

## 15. Known correctness gaps

### P0: status command is bound to the wrong decision family

`uv run fplagent deadline-status --manager-entry-id ...` currently reports `publishable: false`
because it checks `data/decisions/2026-27-gw1-synthesized.json`, which predates the fresh GW3
forecasts. At the same time, the actual weekly pipeline manifest and web refresh state say the GW3
weekly decision passed and was published. This is a real phase-boundary bug.

Fix `deadline-status`/deadline evidence resolution so that an in-season check validates
`2026-27-weekly-current.json` and the matching weekly archive/manager contract. The CLI, API status,
workspace banner and evidence dialog must agree on one canonical result.

### P0: prospective decision scoring has not started

GW1 and GW2 final event outcomes are present in current history, but `fplagent
prospective-scoreboard` reports zero completed events. Determine whether valid frozen pre-deadline
contracts exist, score the latest eligible pre-deadline decision for each event and make missing
contracts explicit. Without this loop, we cannot distinguish a good process from lucky or unlucky
points and cannot promote challengers honestly.

### P0: current test suite is red

Resolve the 16 failures described above and rerun the entire suite. Preserve the current passing
lint/build state. Add a stable test data clock/catalog fixture so advancing live seasons cannot
re-break preseason unit tests.

### P0: recommendation delta labelling is misleading

Expose saved-configuration uplift separately from transfer-versus-optimised-roll uplift. The latter
is the number that should justify spending free transfers.

### P1: participation evidence has operator, not empirical, authority

The one-source RotoWire adjustment is intentionally bounded but currently active because the user
requested role news to affect real decisions. Freeze its pre-deadline predictions and score lineup
hits, minutes calibration and legal-policy lift for every event. Restore a genuinely fresh second
source or use disagreement to widen uncertainty. Remove the operator label only after the declared
prospective gate passes.

### P1: Richarlison and similar retained role risks need deadline watches

The protected forced-sale frontier closes the prior candidate-pruning gap, but the app should make
the exact keep-versus-sale trade-off and price sensitivity prominent. Re-run after fresh lineups and
near the price update/deadline. Generalise tests so every expensive low-minute holding receives an
exact protected counterfactual.

### P1: price timing remains diagnostic

The app records 15-minute transfer pressure and exact selling-value consequences, but cannot yet
recommend “move now”. Continue timestamp-safe midnight outcome collection. Promote only after a
prospective move-now/wait replay improves net points with an acceptable downside floor.

### P1: market evidence has not earned weekly authority

GW3/GW4 coverage is useful and the fixture rates can explain decisions, but the weekly blend is
zero. Score frozen market-world decisions prospectively and revisit only at a scheduled evidence
review. Do not promote it because one fixture feels intuitively correct.

### P2: chip frontier

Continue prospective scoring for every hold/use branch. BB/TC have bounded authority; WC/FH still
need a causal multi-event replay of persistent squad effects. Add schedule-rearrangement trees only
after enough independent historical announcement batches exist.

### P2: broader SOTA evidence

The six research-frontier items remain:

- a second stable independent player-event source;
- a matched external model/policy benchmark;
- materially more untouched 2026/27 events;
- calibrated two-source predicted lineups;
- CRPS/interval/CVaR calibration by position, captain and bench; and
- prospective price/liquidity scenarios scored on net points.

See [`sota-evidence-framework.md`](sota-evidence-framework.md). Do not use “SOTA” as a factual claim
until those gates pass.

### P2: product completeness

- Build a better live-Gameweek view of the immutable submitted team and provisional scoring.
- Surface post-event attribution and prospective regret in the web app.
- Persist durable chat sessions only after the decision data model is stable.
- Add mini-league context late in the season, with a strict expected-points sacrifice cap.
- Design per-user identity/session storage and security before any hosted multi-user release.

## 16. Recommended next-session execution order

1. Read this handoff, `git status`, the latest weekly pipeline manifest and active weekly receipt.
2. Do not discard or overwrite the dirty worktree. There are about 9,700 changed source lines plus
   important untracked modules and reports beyond the current `main` commit.
3. Make the test environment independent from live mutable data; fix all 16 tests.
4. Fix `deadline-status` to select and validate the current weekly family in-season.
5. Add a regression test proving CLI status, refresh state and workspace evidence all reference the
   same weekly receipt/hash.
6. Fix the UI's saved-lineup versus optimised-roll delta distinction and test it.
7. Score or explicitly account for GW1/GW2 prospective decisions and rebuild the scoreboard.
8. Start MCP and the web stack, reconnect, and run a fresh GW3 decision close to the deadline.
9. Manually inspect all 15, the strongest rejected route, Richarlison's forced-sale route, captain,
   bench, chips, prices, market/lineup freshness and transfer affordability.
10. Only after the operational loop is green, resume model/challenger work in the order dictated by
    prospective point value.

## 17. Command reference

### Current weekly operation

```bash
uv run fplagent deadline-run --manager-entry-id YOUR_ENTRY_ID
uv run fplagent deadline-run --manager-entry-id YOUR_ENTRY_ID --reuse-latest-official
uv run fplagent rehearse-weekly-decision --event 3 --horizon 5
uv run fplagent schedule-status
uv run fplagent participation-scoreboard
uv run fplagent prospective-scoreboard
uv run fplagent challenger-registry
```

### Final event learning loop

```bash
uv run fpl-data collect-event-outcome --event EVENT
uv run fplagent score-weekly-event --event EVENT
uv run fplagent prospective-scoreboard
uv run fplagent distribution-scoreboard
uv run fplagent challenger-registry
```

### Data and forecast inspection

```bash
uv run fpl-data refresh-current
uv run fpl-data snapshot-status
uv run fpl-data collect-participation-consensus
uv run fplagent collect-current-market-goals --horizon 5
bash scripts/refresh_current_forecasts.sh
uv run fplagent gpu-check
```

The forecast-only script does not produce a complete weekly decision. Use `deadline-run` for a
recommendation that is safe to present.

### Chip evidence

```bash
uv run fplagent calibrate-chip-strategy
uv run fplagent build-chip-schedule-history
uv run fplagent build-rearrangement-model
uv run fplagent replay-squad-chips
uv run fplagent replay-team-chips
```

### Quality gate

```bash
uv run ruff check src tests llm
uv run pytest -q
cd web
npm run lint
npm run build
```

### Documentation rebuilds

```bash
uv run python scripts/build_algorithm_whitepaper.py
uv run python scripts/build_interactive_model_story.py
```

## 18. Git and artefact safety

Current committed branch:

```text
main tracking origin/main
HEAD 67df2e2 docs: publish evidence-backed decision whitepaper
remote git@github.com:lewis-king/fpl-agent.git
```

The worktree is heavily modified and contains many untracked source modules. Treat all of it as user
work. Before editing, inspect `git diff` for overlap. Never use destructive reset/checkout commands.

The following must remain out of Git:

- `.env*`, credentials, tokens and keys;
- `llm/.venv`, adapters, checkpoints and model outputs;
- `web/node_modules` and build output;
- raw/downloaded data, mutable databases and generated manager/decision state; and
- bulky generated media unless Lewis explicitly chooses to version it.

The chip calibration receipt is intentionally allow-listed under `data/model/chip_strategy_v2/`.
Review `.gitignore` before staging `data/model/` because that directory currently has both a broad
ignore and a narrow tracked exception.

Commit source, tests, stable configuration and durable docs in coherent units. Verify that no model
weights or account/session material are staged before pushing.

## 19. Definition of a trustworthy deadline recommendation

A future agent should not tell Lewis “this is the team” until all of the following are true:

- official snapshot, fixture schedule and manager state are fresh and aligned;
- current-season finalized history has no schema/player-set mismatch;
- direct and component forecasts reference the same source generation;
- participation and market evidence clearly state their authority and freshness;
- every proposed transfer is legal and exactly affordable using selling values;
- the selected route beats the optimised roll route after costs and uncertainty;
- XI, bench, captain and vice were selected from all 15 under exact rules;
- severe retained role risks received protected sale counterfactuals;
- chip use/retention was evaluated jointly under the current rules and schedule;
- the strongest rejected route and key assumptions are visible;
- the publication/evidence hash is valid and the CLI/API/UI agree;
- the full automated quality suite is green; and
- a human-readable final instruction distinguishes model expectation from football certainty.

That is the standard to keep iterating toward: not a magical claim that variance has disappeared,
but the strongest legal decision the available evidence can support, with a complete audit trail.
