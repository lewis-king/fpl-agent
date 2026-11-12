# FPLAgent project status

## 21 October: fresh forecast diagnosis and live availability correction

The fresh Scout comparison exposed two live date-indexing defects: absolute preseason
availability branches and preference for last-round over next-round chance. These are fixed
for all players, with source-independent official-zero handling, correct zero component ratios
and an independent publication check. Eighteen unavailable players previously retained nonzero
GW8 forecasts; rebuilt direct/components have no such violations. Returning players are also
handled correctly. Release: `points_first_release_20261021_v5`.

The new error diagnosis is automatic during normal finalized-outcome scoring. Broader three-season
legal replays and a paired GPU input-refit were completed; learned weights remain unchanged because
the results do not establish a reliable policy improvement. Current forecast artifacts are fresh,
but the published recommendation is still GW7: no stale manager state was promoted as new advice.
See [the full report](../reports/forecast-diagnosis-and-corrections-2026-10-21.md) and
[handoff](agent-continuation-handoff.md) for evidence, limits and reproduction commands.

## Follow-up completed — Scout benchmark and gate/search challenge, 21 October

Added optional authorized Scout comparison capture to ordinary weekly runs, private immutable
receipts, strict identity/freshness checks and finalized-outcome scoring. Measurements cannot
change advice or train a model. First 25-player GW8 capture is **unmatched** because our local
forecast is four days old; no fresh GW8 advice was generated. The next full refresh captures
both near the same time. No ongoing subscription is required for our engine or archive scoring.

Completed five-arm chronological gate/search experiment (17m14s). Wider incumbent search:
**+26/−5** points versus narrow control in 2024/25 and 2025/26 opening ten events. Mean-points
policy: **+12/−3** narrow and **+12/−21** wide. Isolated configuration veto removal: **0/0**.
All fail the fixed two-fold promotion screen. Keep current live gates/risk; this does not prove
our forecasts or incumbent are optimal. Production search was already wider than the old
historical control. Independent audit verified all 100 new arm-events. Release is now
`points_first_release_20261021_v4`; [full audit](../reports/scout-product-audit-and-gw7-review-2026-10-21.md)
and [handoff](agent-continuation-handoff.md) distinguish deployed measurement from rejected policies.

Final verification: **883 non-LLM tests passed**, targeted lint/whitespace checks passed;
all processing completed and the published GW7 recommendation remains unchanged.

## Latest completed work — 21 October 2026

Priorities **2–5** (premium reinvestment, points/risk, future transfers/chips, score distributions)
have completed this implementation/validation/release-review pass. See the
[full audit and results](../reports/scout-product-audit-and-gw7-review-2026-10-21.md) and
[continuation handoff](agent-continuation-handoff.md) for authoritative engineering status.

- Fixed real chip-calendar errors: no retention beyond half-season expiry and no more saved-chip
  uses than remaining unseen deadlines. Both fixes apply automatically in normal weekly decisions.
- Added automatic exact BB/TC opportunity measurements, with autosubs and vice fallback; these
  measurements do not independently authorize a new chip-timing policy.
- Completed a prefix-fitted three-world GW1–10 replay in 2024/25 and 2025/26. Premium search
  scored 0/0 versus its control, guarded future transfers +36/−1, score-shape remapping +21/0;
  none of the alternative risk weights improved both seasons. All fail the declared promotion
  screen. Retain risk 0.25 and the current selector rather than promote unproven experiments.
- **854 non-LLM tests passed**; 140 independent strategy/gameweek ledger checks passed. Historical
  data gaps and bounded searches prevent any complete production-replication or SOTA claim.

Release `points_first_release_20261021_v3` records the concluded decisions. The **published receipt
is still GW7**; this research did not refresh GW8 or change the saved squad. New code is used by
the next process/run, not retrospectively applied to saved advice. No LLM work was run.

## Earlier September status (historical)

**September audit:** [9 September deeper weekly search](../reports/weekly-deep-search-2026-09-09.md)
expanded the search from 16 to 100 legal current-transfer routes and evaluated 540 frozen five-week
policies. Both independent holdouts rejected its Gonzalo challenger on the predeclared points-based
acceptance test. The published Richarlison → Evanilson action, XI, captaincy and no-chip instruction
remain unchanged. This is a reusable research command, not an automatically promoted app selector.

**September release:** [9 September merit-based promote/reject review](../reports/points-first-promotion-decisions-2026-09-09.md)
adds the admissible-only regret-reference correction and explicit deployment decisions enforced in
weekly receipts. Rejected experiment versions cannot promote themselves. Read its final handoff
for that dated refresh rather than the older August runs below.

**Historical workstream update:** 9 September 2026. At that point we were approaching GW4. See the
[ordered improvement programme](decision-improvement-roadmap-2026-09-09.md) and
[latest round-two validation/publication](../reports/points-first-validation-round2-2026-09-09.md)
for live status. The August sections below are retained as historical engineering notes and must
not be used as today's team recommendation; the current runtime receipt is authoritative.

**Historical status date for the sections below:** 19 August 2026
**Active objective:** maximise season points through reliable forecasts and legal, robust FPL
decisions.

## Current GW1 deadline recommendation

The fresh 19 August transactional pipeline and corrected final handoff are both publishable. The
canonical receipt selects `R-01afc86b1b`: a £100.0m, £0.0m-bank 3-4-3 projected for 64.29 central
GW1 points, with Bruno Fernandes captain and Mbeumo vice-captain.

- XI: Donnarumma; Lacroix, Tarkowski, Maguire; Bruno Fernandes, Semenyo, Mbeumo, Szoboszlai;
  Igor Thiago, Calvert-Lewin, Watkins.
- Bench order: Milenković, Truffert, McAteer; Verbruggen as reserve goalkeeper.
- A fresh search considered 537,804 legal candidates, reduced them through residual/component
  holdouts, solved open/rolled transfer policies and promoted the eight-week leader over the
  provisional five-week winner. The final squad then won all three independent 25,000-world
  production seeds and all 45 bounded horizon/minimax weight-grid cells; maximum selected grid
  regret was zero.
- The exact bench audit evaluated 68 targeted squads in 25,000 new worlds plus 272 legal five/eight-
  week transfer policies. It retained this squad as a rotation solution, not as a generic rule to
  spend heavily on the bench.
- The isolated participation audit watches Lacroix, McAteer, Mbeumo and Watkins. A post-run causal
  audit found that the same GW1-only challenger already wins at every live production anchor, so
  none is a valid player-minute break-even. Those routes are monitor-only: the alternative's best
  severe-role GW1 floor is +0.589 points, but it carries +4.125 multiweek synthesis regret. Any new
  role evidence requires a complete rerun rather than an already-true `≤ minutes` trigger.
- The active forecast is checksum-bound to one complete 10/10-fixture Betfair generation. The
  promoted bounded market layer is present in the published bytes: a 20% defender feature and a
  separately calibrated 5% forward goal-environment feature. A checksum-valid ready market
  generation may survive a transient provider failure for at most six hours; stale, wrong-event,
  fixture-mismatched or checksum-mismatched data still fails closed.
- The explicit chip action remains `NO_CHIP`. Bench Boost has the strongest immediate signal, with
  a +13.34 cross-model mean floor versus the retained policy's 8-point threshold, but that timing
  policy failed its historical authority gate. It is reported as strong but non-actionable rather
  than promoted from one attractive Gameweek.
- All canonical execution checks pass, including byte-level decision lineage, exact central
  route identity, legal contingencies, chip candidate identity, published pipeline, current
  prospective contract and exact £100m accounting.
- FPL-authored `ep_this`, `ep_next` and `xP` remain runtime-denied model inputs. Production comes
  from the project's own forecast and legal simulation/search system; external challengers only
  receive weight after their declared time-forward decision gates pass.

The exact manual instruction is in the
[standalone execution receipt](../reports/gw1-deadline-execution.html), with evidence in the
[GW1 deadline pack](../reports/gw1-deadline-pack.md). This is not a permanent lock: rerun
`fplagent gw1-deadline-run` and `fplagent build-deadline-handoff` after material news and at the
deadline cadence. Any checksum or gate failure retains the last valid receipt.

## Simulation-authoritative GW1 configuration

The pipeline now separates two decisions that had previously been coupled too loosely. The robust
and horizon search selects the best legal 15; a new post-synthesis gate then selects how that 15 is
actually used in GW1. It simulates every legal XI, all six legal orders of the three outfield
substitutes, and captain/vice choices. Goalkeepers, defenders, midfielders and forwards therefore
compete through legal formations, autosubs and captain fallback rather than being sorted by their
displayed mean xP.

The gate balances two deliberately different model families: calibrated forecast-residual worlds
and explicit football-component worlds with correlated team goals, clean sheets, conceded goals,
attacking returns, bonus and defensive contributions. A configuration is promotable only if the
selection champion remains first on independent holdout seeds; disagreement fails closed and
preserves the prior complete decision.

A read-only production-data validation against the currently published 15 selected Milenković as
first outfield substitute ahead of Truffert and Mbeumo as vice-captain ahead of Lacroix. The same
configuration won selection and the 25,000-world-per-family holdout, improving the declared robust
criterion by 0.094. The component family gained 0.194 mean GW1 points while the residual family lost
0.040, which is precisely the fixture-structure disagreement that the minimax selector is intended
to resolve. This validation did not mutate the active receipt: the configuration becomes active
only through the next complete transactional deadline refresh, where all downstream lineage and
falsification gates are regenerated together.

## LLM work frozen after the final bounded cycle

Lewis explicitly reopened the prepared V9 experiment for one final train-and-evaluate cycle. It
completed in 97 minutes 56 seconds and was rejected by the locked application chat, legacy, safety,
blind qualitative and held-out screenshot promotion gate. No checkpoint hunting or further LoRA
iteration is authorised; implementation has returned to the points-first roadmap.

The current state is:

- Qwen3.5-4B remains the text-chat base model behind the application's system policy, typed tools
  and deterministic decision guards.
- No text LoRA from the v5-v9 experiments was promoted. V9 preserved all 50 no-tool boundaries and
  improved grounded application routing from 4/8 to 8/8, but tied base at only 16/58 strict full
  contracts, fell below the legacy reference and failed the safety and blind qualitative gates.
- V9 extracted both supplied real screenshots exactly and improved the held-out synthetic suite
  from 2/10 to 5/10, but that is still not safe enough to import squads without deterministic
  validation and user review.
- The separately scoped v3 screenshot adapter remains available for screenshot research; it is not
  the authority for squad, transfer, lineup, captain or chip decisions.
- All existing corpora, configs, checkpoints and reports are retained as research artifacts. Their
  presence does not make them production candidates, and the app defaults were not changed.

The detailed measurements and exact earlier state are in
[the V5-V9 experiment handoff](../reports/fpl-llm-v5-experiment.md). The next product priorities are
in the [points-first product roadmap](points-first-roadmap.md).

## What is already built on the points-first path

- The current-player contract now hard-fails if any officially selectable player is absent from
  the model grid. The 15 August refresh contains 568 selectable players over eight events, including
  all ten newly listed FPL elements since the prior generation.
- The final selector is historically gated end to end. A 48-path legal horizon replay retained
  GW1–8/0.88, and a separate leave-one-season-out selector replay retained the equal family weight
  and 20% worst-family surcharge. Both decisions were challenged on untouched 2025/26 rather than
  inferred from the current squad.
- Participation coverage now spans the entire synthesis frontier, with exposure-weighted player,
  starter and captain diagnostics. Missing official, forecast or role evidence for any jointly
  tested finalist is a publication error; third-party predicted XIs remain a visible zero-weight
  shadow.
- A new final scoring-structure audit challenges all synthesis finalists and five bench-proxy
  settings using exact legal autosubs/captain fallback while removing and doubling bonus and
  defensive-contribution layers. A supported reversal blocks the deadline-ready receipt.

- Leakage-safe historical/current features and promoted direct and component forecasts.
- Legal full-squad optimisation with budget, position and club constraints.
- Robust GW1 candidate search, shared scenario simulations and decision receipts.
- Exact autosubs, captain fallback, full 15-player lineup comparison and bench-to-XI promotion.
- Immutable official-data generations with checksums, freshness and lineage gates.
- Strict authenticated-manager snapshot validation, an exact weekly-state adapter and immutable
  derived contracts linked to the raw snapshot, official event, forecast and rules generations.
- Roll, one-transfer, multi-transfer and paid-transfer routes with selling prices, bank, hits and a
  historically calibrated value for retained free transfers.
- A weekly decision receipt and web UI contract covering the selected route, rejected alternative,
  transfers, XI, bench, captain, confidence interval and model-world downside.
- Immutable per-event weekly decision archives and prospective scoring against official finalized
  outcomes, including exact autosubs/captaincy, hit costs, roll comparison, opportunity cost and
  player-level forecast errors.
- The web application now serves the last validated workspace immediately, syncs the authenticated
  MCP squad, and launches one persisted single-flight GW1/weekly decision refresh on every app open.
  It polls a typed stage-progress contract, joins duplicate requests, exposes the successful
  pipeline hash in provenance, and retains the prior receipt on blocked, failed or interrupted
  runs. GW1 now validates and, when necessary, refreshes checksum-bound preseason role evidence
  before any expensive tournament starts. Deterministic evidence blocks pause automatic retries
  until the source generation changes or the manager requests a manual retry. The daemon worker
  also prevents a long tournament from blocking local server shutdown.
- The same coordinator now owns automatic T−72h, T−24h, T−6h, T−60m and T−10m runs. A lightweight
  semantic probe detects material public FPL status/news, price, rule and fixture changes between
  windows on a deadline-sensitive cadence; ordinary transfer-counter movement is deliberately left
  for the cheaper price telemetry stream.
- That probe now also archives and compares the current Betfair goal-rate generation. Coverage or
  provider changes, a 0.10 inferred team-goal move, or a 0.025 clean-sheet-probability move triggers
  the full decision pipeline; smaller price noise does not. The first live comparison saw only
  0.0493 goals / 0.0131 clean-sheet probability of movement and correctly retained the decision.
  Scheduled deadline windows still run regardless of the materiality threshold.
- A separate daemon now archives the public FPL market fields every 15 minutes without invoking the
  decision engine. Each immutable player observation includes current price, official
  `price_change_percent`, ownership, event/total transfers, net flow and availability with raw,
  Parquet and receipt checksums. The first live 8 August generation contains 573 players. This is
  evidence collection only: no early-transfer recommendation is authorized until a net-points
  policy beats waiting under historical and prospective gates.
- Once two within-event observations exist, the stream automatically derives interval net/gross
  transfer velocity, ownership-normalised velocity, ownership change, acceleration, current
  predictor percentage and time to UK midnight. Counter resets are rejected rather than interpreted
  as mass selling. Two live 8 August observations now exist 17.6 minutes apart, so the first
  573-player feature generation is `ready`. All current preseason transfer velocities and predictor
  percentages are zero; that honest no-signal result is retained rather than manufacturing price
  pressure before the game starts.
- The stream now scores the official indicator against actual price changes using only tight
  observation pairs around UK midnight. Its frozen first gate requires 14 nights, 30 rise and 30
  fall threshold calls, and at least 75% precision in each direction. It currently reports
  `not_ready` with zero nights, as expected while preseason prices are locked.
- Every selected weekly transfer route now receives an exact price-threshold affordability stress:
  incoming rises add £0.1m, outgoing falls use the manager's actual purchase price and FPL's
  half-profit selling rule, and the route is rechecked against its post-transfer bank. Evidence
  older than 45 minutes or missing player rows fails closed. This remains zero-authority and always
  advises waiting until a separate move-now-versus-wait net-points replay passes.
- A tempting historical price model was rejected before promotion because public adjacent weekly
  snapshots label prices 3.6–5.1 days after the deadline and therefore include post-deadline
  transfers. The clean prospective design and gate are documented in the
  [early-transfer policy](early-transfer-policy.md).
- The workspace is no longer hard-coded to stop at the GW1 deadline. Its official-calendar resolver
  separates the event currently being played from the next actionable decision event. During live
  GW1 the submitted context remains event 1 while the deadline scheduler targets GW2 and invokes
  the weekly pipeline for event 2; once GW1 is data-checked the product becomes the GW2 decision
  desk. Regression tests cover both transitions.
- The presentation layer now completes that handoff too: event-specific forecasts and fixtures feed
  the pitch, and a matching weekly receipt supplies the actual post-transfer 15, legal XI, ordered
  bench, captain, vice-captain, projected points and forward lineups. The captain card, pitch and
  weekly action therefore share one authority instead of independently reconstructing answers.
  Stale receipts for a different gameweek are ignored.
- Weekly receipts now expose the operational chip and execution calls alongside the move. WC, FH,
  BB and TC shadows remain visible as evidence but resolve to `Save the chips` until their retained-
  value gates pass. Price pressure can flag that a route may become unaffordable, while the action
  remains `Wait` until prospective price calibration and lost-information replay justify moving
  early.
- The first full post-GW1 rehearsal now converts the published GW1 squad into an explicitly
  synthetic, zero-authority manager snapshot and runs the real weekly optimiser across GW2–GW6.
  The exercised route legally rolled its transfer, selected its XI from all 15 and kept the chip
  shadows non-operational. This rehearsal exposed and fixed string-to-`Path` checksum handling in
  both chip-retention loaders before a genuine weekly receipt can depend on them. Run it with
  `fplagent rehearse-weekly-decision`; it writes only under the rehearsal namespace and cannot
  replace the active decision.
- Double-gameweek fixture identity now survives all the way to the player card and player-focus
  view. The web workspace stores every fixture for a club/event in kickoff order instead of
  silently overwriting one match, while the compatibility `fixture` field remains the first match.
  A regression fixture covers a home-plus-away double.
- Participation Confidence v2 is now a first-class web contract. Every player carries explicit
  DNP, 1–59, 60–89 and 90+ probabilities plus separately labelled official/lineup evidence. The
  squad view reports evidence coverage and only shows legal scenario reversals as counterfactual
  stress tests; it never presents them as availability probabilities.
- Long app-open work is safer operationally: post-synthesis GW1 stages resume from their staged
  artifacts, orphaned in-process refresh state is failed closed by a liveness watchdog, and browser
  opens within six hours reuse the latest terminal check unless a manual, scheduled or material-
  change run is requested.
- Exact Bench Boost and Triple Captain shadow scoring paired to every ordinary weekly route. It
  subtracts a visible retained-chip proxy, requires cross-model paired evidence and automatically
  returns `no_chip` when the remaining chip half extends beyond the forecast horizon or fixture
  scheduling is unresolved.
- Wildcard and Free Hit now have separate exact legal squad searches in the same shared residual and
  match-component worlds. Wildcard permanently carries the optimised squad through the horizon;
  Free Hit uses its optimised squad only for the current event and restores the original squad,
  bank and entering transfer balance afterward. GW1 and consecutive-Free-Hit restrictions remain
  enforced by the state machine.
- The WC/FH receipt reports raw paired gain against the strongest ordinary route, model-world
  downside, every transfer, bank and event-specific squad. It cannot recommend spending a chip:
  retained-chip option value has not yet passed point-in-time blank/double replay, so the
  operational output is always `no_chip`. See the
  [squad-chip shadow contract](squad-chip-shadow.md).
- A leakage-safe historical chip-schedule ledger is now built from the latest archived fixture
  snapshot observed before each deadline. It contains 1,771 future-event rows across 83 decision
  snapshots (37 in 2023/24, 35 in 2024/25 and 11 in the available 2025/26 archive), preserving
  blanks, doubles, unassigned fixtures and schedule certainty exactly as known then. It is the
  retained-value replay foundation, not a promoted chip policy.
- A point-in-time rearrangement shadow reconstructs 17 unassigned-to-assigned fixture episodes and
  preserves nine correlated announcement batches. It is integrated into weekly schedule
  diagnostics but rejected for authority because only two seasons are represented and the frozen
  20-batch/three-season evidence gate is not met.
- Continuous WC/FH replay now preserves squad, bank, selling prices, free transfers, hits and Free
  Hit restoration across 38 deadlines. The 2023/24-selected trigger gained 79 points in untouched
  2024/25, but its four-Gameweek downside lower bound was −1.053 points/GW, so the historical gate
  rejects it and the weekly engine does not apply its retained-value threshold.
- Continuous BB/TC timing replay gained 24 points on the untouched season and finished two points
  above an offline best-forecast-opportunity comparator. Its timing-regret lower bound was still
  −0.474 points/GW against a frozen −0.25 bar, so that policy is also rejected. Both receipts are
  checksum-bound into weekly decision lineage with zero decision authority.
- A single forecast-challenger registry now inventories five production-relevant experiments,
  verifies their artifact bytes and combines frozen historical gates with paired prospective
  policy outcomes. Direct xP remains the champion; no challenger currently passes its historical
  gate and automatic promotion is structurally disabled.
- Final-event prospective scoring now separates regret to the best considered action from a legal
  hindsight XI/captain upper bound, captain regret inside the frozen XI, player expected-points
  error and appearance Brier score. It also scores form-reversion and market-policy choices frozen
  in the weekly receipt. A season scoreboard selects the latest valid pre-deadline receipt per GW;
  it correctly reports `awaiting_final_events` before GW1.
- A late-season mini-league shadow can use the immediately prior GW's rival lineups and league gap
  to compare exposure distance among already-generated legal actions. It applies a bounded expected-
  points sacrifice cap only from GW31, has zero authority and leaves the points-first action
  operational pending historical rank simulations and prospective league receipts.
- A checksum-bound schedule receipt classifies confirmed, provisional and unassigned fixtures,
  records every blank/double team-event without speculatively assigning postponements, detects
  schedule changes and is bound into weekly decision lineage.
- Match-component simulation now scores each fixture independently before gameweek aggregation:
  blanks are zero, doubles receive separate appearance/clean-sheet/bonus opportunities, goals
  conceded are rounded per match, and event-level appearance probability is preserved using the
  historical 70.2% both-fixtures / 29.8% one-fixture rotation split conditional on appearing.
- The 2026/27 outfield BPS correction has an independent advisory validation against a public
  537-player, 380-fixture reconstruction. Its player-season MAE is 0.535 versus 0.693 for no
  correction and 0.752 for a position-only correction, with 0.625 rank correlation. The source
  also contains one duplicated Junior Kroupi fixture row, so it is archived with provenance and
  used as corroboration only; it does not replace the production model or justify a goalkeeper
  correction without complete save context.
- A provenance-bound preseason lineup collector now archives confirmed friendly lineups and
  derives join-date-aware listing/start/appearance evidence without changing forecasts. The first
  receipt covers 52 confirmed events and 352 current FPL players across 18 clubs. Source minute
  coverage is only 33.5%, Brentford and Brighton have no confirmed feed, and all missing minutes
  remain null, so the layer is scenario-only.
- The checksum-bound preseason role sensitivity audit exhaustively reoptimizes all 550 legal XIs
  for the published 15 and screens the full synthesis frontier on selection and independent holdout
  worlds per model family. In the current generation, baseline deep replay prefers
  `R-1ca68907f5` by +0.952 residual and +1.184 component points; moderate, severe and repeated-
  absence scenarios prefer `R-0aec115e14`. These are material verification triggers derived from
  zero-authority role evidence, not automatic promotions, and are exposed in the deadline pack.
- The fresh-seed threshold audit supports `R-0aec115e14` through the top of the tested coupled path
  (75% general conditional retention / 90% role-watch retention). That means the alert cannot be
  dismissed as a knife-edge result; the three current role-watch players must be verified close to
  the deadline before treating the active squad as a submission lock.
- The threshold run also exposed and fixed an unordered historical residual-bootstrap query. The
  pool is now explicitly ordered by season, event and player, making identical seeded simulations
  byte-reproducible across separate processes.
- A checksum-bound availability watch now joins the current 15 to official FPL status/news, aligned
  GW1 `p_play`, preseason role evidence and the supported stress boundary. The current receipt finds
  zero official doubts, three role-verification players (Watkins, Calvert-Lewin and Bruno
  Fernandes) and zero uncovered-feed players.
  Its action is `retain_decision_and_verify_flagged_players`; advisory evidence is structurally
  unable to authorize a production change. A compact view is included in `deadline-status`.
- A timestamped predicted-lineup subsystem now captures FFScout and RotoWire, archives raw bodies,
  aligns only complete XIs to the exact official event/fixture/player generation and exposes its
  votes through the same availability watch. On 10 August both providers were captured, but
  FFScout's advertised 20 July modification time failed the seven-day freshness gate; RotoWire is
  therefore the only eligible source and includes all 15 published players. Production weight is
  zero. The immutable prospective scoreboard requires six two-source events with positive,
  non-negative-downside lineup-hit lift before it can even request an exact legal replay. Ambiguous
  team-only predictions are excluded for double-gameweek teams.
- The GW1 publisher now creates the squad-specific role scenario, stress threshold and availability
  watch inside the same fingerprinted staging transaction as synthesis. Publication requires a
  current aligned watch, final checksums are revalidated after the atomic switch, and any failure
  restores the complete previous artifact set. The live lineup source was refreshed on 9 August:
  it currently has 71 confirmed lineup events and coverage for all 20 clubs.
- A full-pool one-swap audit now enumerates all 2,259 legal same-position replacements around the
  published squad. It found a genuine horizon-membership omission, Mukiele to Senesi. Equal
  full-field replay ranks the challenger second of 49 over the eight-week horizon (+0.316 central
  points versus the published squad, 95% CI +0.181 to +0.452), but only 27th of 65 in the five-week
  robustness family (-0.783, -0.928 to -0.637). Its synthesis regret is 1.498 versus 0.906 for the
  incumbent, so the challenger is rejected and production remains unchanged. The horizon audit
  now protects 32 deterministic legal neighbours drawn across the top eight robust seeds; a live
  generation check includes the exact Senesi squad. This closes the membership gap for the next
  complete deadline run without allowing a fixed-squad winner to bypass synthesis.
- Planning horizon and future discounting now have a deadline-safe rolling calibration rather than
  judgment alone. Sixteen 1/3/5/8-week policies were replayed through GW1–8 of 2023/24–2025/26,
  with a new decision at every deadline, historically legal free-transfer banks, no future player
  outcomes, and realised autosub/captain scoring. The two-season selector chose 5 weeks/0.88, but
  the candidate tied rather than beat 8 weeks/0.88 on the sealed 2025/26 path and its selection
  advantage reduced to one different opening goalkeeper. It failed the local-stability and frozen
  test gates, so production correctly remains at 8 weeks/0.88 pending broader point-in-time data.
- A provenance-bound pre-closing market goal-rate challenger now maps 2,660 historical Premier
  League fixtures to FPL IDs and uses only de-vigged non-closing 1X2 and over/under prices. On the
  frozen 2023/24–2025/26 set it improves Poisson deviance from 1.0892 to 1.0514, goal MAE from
  0.9331 to 0.9179 and clean-sheet Brier from 0.1702 to 0.1678. A blend selected on 2024/25 gains
  5.00 realised points/GW on the untouched 2025/26 independent-gameweek legal selection replay
  (95% interval +1.34 to +8.66), including +2.18/GW versus the internal component signal at the
  same weight. A public delayed Betfair Exchange fallback now discovers the exact Match Odds and
  O/U 2.5 market IDs and provides complete, timestamp-safe coverage for all 10/10 GW1 fixtures;
  its raw JSON books are archived immutably and explicit aliases bridge four provider team names.
  The English Premier League competition ID is now itself discovered from Betfair's exact-name
  competition facet rather than hard-coded from a changeable URL suffix.
  It nevertheless remains shadow-only because an independent-gameweek rebuild is not a sequential
  transfer-policy result. The completed continuous replay selected a conservative 25% market
  weight on 2024/25 (+145 net points)
  but lost the untouched 2025/26 path by two points (`2005` versus `2007`), with a four-GW block
  interval of -3.18 to +2.87 points/GW. Market odds are therefore rejected for weekly transfer
  authority and retained only as a GW1 shadow candidate.
  A separate Betfair-only reconstruction reaches 99.2% historical fixture coverage in 2024/25 and
  94.7% in 2025/26. It beats the internal fixture model on untouched Poisson deviance (`1.0501`
  versus `1.0848`) but trails the broad market average (`1.0472`). Its independently selected 20%
  player-component weight again finishes two points behind on the untouched continuous legal path,
  so the provider-specific gate also rejects production authority. Runtime support for a bounded
  provider-specific blend exists but fails closed to 0% under this receipt.
- A distribution-aware player-return challenger now targets the largest measured decision gap:
  ordering the already-good players competing for the XI, captaincy and transfers. Its three
  season-forward bands are under five points, 5–9 and 10+. Validation chose a 25% blend, improving
  the continuous 2024/25 path by 99 net points; the untouched 2025/26 path improved by 94. The same
  frozen blend improved independent legal selection by 41, 94 and 60 points across the three OOF
  seasons. It remains `HOLD_SHADOW`, because the frozen four-GW interval (-0.211 to +5.132/GW)
  missed the predeclared -0.10 downside floor. Production forecasts and decisions are unchanged.
- The same return signal has now been isolated to captain/vice selection while holding the legal
  squad, XI and bench fixed. It gained 21 points on untouched 2025/26 (+0.553/GW), but its four-GW
  interval was -0.421 to +1.526/GW and the separate 2023/24 replication gained only one point.
  The captain-only policy is therefore also `HOLD_SHADOW`; direct xP remains armband authority.

## Immediate delivery order

### Historical implementation chronology (superseded)

The chronology below records earlier generations and the defects or policy questions they exposed.
Candidate IDs, squads, role-watch counts and test totals in this subsection are historical; the
15 August recommendation at the top of this document is the only current handoff.

The first four-class appearance challenger was evaluated without changing production. No position
passed the full statistical and policy gate. A separate 76-gameweek legal-squad replay then showed
that the previously promoted FWD appearance calibration cost an estimated **0.789 points per
gameweek** versus raw forecasts, with a paired 95% interval of **-1.569 to -0.010**. It has therefore
been retired with its original bytes and replay receipt archived.

Direct and component forecasts were regenerated under the restored raw appearance policy, and the
complete candidate, robust-search, horizon and synthesis funnel was rebuilt from that coherent
generation. The rebuild also found and fixed a residual-simulator assumption that failed when an
official fixture contained team ID 20 but the selectable-player subset's maximum team ID was 19;
official IDs are now mapped to dense simulation indices and covered by a regression test.

The first manual post-retirement rebuild retained the old squad, but the new end-to-end deadline
runner exposed a separate reproducibility defect: the current feature query lacked a final order,
so unchanged logical rows received different physical Parquet and forecast hashes on every refresh.
The grid is now ordered by event and player, component inference requires exact key order rather
than equal row counts, and two complete feature builds produce byte-identical output.

An earlier complete live runner published `R-e80223d1fc`: 5-3-2, Bruno Fernandes captain,
Tarkowski vice-captain, £100.0m spent and £0.0m bank, with 58.557 projected GW1 points. It is bound
to direct forecast `955b8082…`, component forecast `e860770e…`, decision `37dd264b…` and pipeline
fingerprint `219e232a…`. The evidence gate has zero issues. The XI is Donnarumma; Tarkowski,
Collins, Maguire, Mukiele and Truffert; Bruno Fernandes, Mbeumo and Gibbs-White; Igor Thiago and
Watkins. The bench order is Calvert-Lewin, Szoboszlai, Groß and Verbruggen. An immediate identical-
input invocation completed in approximately 4.5 seconds with `reused: true` and started no
optimisation stage. The decision remains provisional and must be refreshed as material news or the
deadline window changes.

That generation's role audit found no supported alternative on its tested stress path. The availability
watch is current and cannot authorize a decision change: all 15 players are officially available,
while Watkins, Truffert, Calvert-Lewin and Bruno require attributable role verification and the
four Brentford/Brighton selections have no confirmed structured preseason feed. These are explicit
deadline checks rather than hidden assumptions.

That published 15 also passed a checksum-bound, read-only local-decision audit. Its exact XI,
bench order, Bruno captaincy and Tarkowski vice-captaincy were independently recovered as the top
robust holdout configuration. A numerically tiny baseline squad-screen alternative was not
supported by either model-family holdout, so it cannot mutate the published decision.

A later controlled 9 August run exercised the expanded global, five-week and eight-week funnel on
fresh aligned inputs. It completed every expensive stage and selected staged synthesis candidate
`R-d8cf2f79ad` (4-3-3, Bruno captain, £21.5m bench), but the then-current final gate retained the
last valid published receipt because independent role replay preferred Hill/McAteer to be replaced
by Sadiki/Senesi in its baseline and moderate counterfactuals. That run exposed a classification
bug rather than stale evidence: the role artifacts themselves declare those alternatives read-only
verification triggers. The availability gate now returns `scenario_attention`, `current: true` and
`decision_change_authorized: false` for this case; only missing, stale or checksum-mismatched
evidence returns `refresh_required`. Replaying the fixed gate against the exact staged artifacts
produces no issues and preserves all four counterfactual impacts for inspection. The failed run did
not replace the previously validated production decision.

The then-current validated generation superseded those earlier chronology points. A fresh official run
followed by a post-match role refresh now publishes `R-dc7de17def`: 4-3-3, Bruno Fernandes captain,
Tarkowski vice-captain, £100.0m spent, £0.0m bank and 57.449 projected GW1 points. The XI is
Donnarumma; Tarkowski, Maguire, Senesi and Truffert; Bruno Fernandes, Mbeumo and Gibbs-White; Igor
Thiago, Watkins and Calvert-Lewin. Its bench order is Szoboszlai, Hill, Tanaka and Verbruggen.
An independent current-squad holdout exactly reproduced the formation, XI, bench order and both
armbands in the residual and component families.

The refreshed advisory lineup feed now covers 20/20 clubs, 71 confirmed lineup events and 76
confirmed club-event rows. Brentford is no longer an unknown and Igor Thiago carries no observed-role
flag. Watkins, Senesi, Bruno Fernandes and Tanaka remain verification items, but friendly evidence
has zero direct weight in production xP and cannot change the squad. This is particularly important
after the 2026 World Cup: phased returns and experimental friendly teams are not injury or
loss-of-place claims. Supported alternatives remain read-only. Under the unperturbed role world,
the leading alternative replaces Gibbs-White, Hill and Tanaka with Collins, McAteer and Semenyo;
it is 11th in synthesis and carries 0.739 more regret. Under moderate counterfactual stress the
alternative is fourth but still carries 0.199 more synthesis regret. The UI presents these costs
alongside the scenario-only gain.

GW1 is also ready for prospective evaluation. The latest contract freezes `R-dc7de17def`, its
serious alternatives, relevant player forecasts, decision/shortlist/forecast/bootstrap hashes and
the official 21 August deadline. It is stored under `data/decisions/weekly/event-1/` without
mutating the live decision. Future changed generations create this contract inside
`gw1-deadline-run`; a failed freeze rolls the publication and evidence receipt back.

The connected-squad web critique now compares all 15 players with this published benchmark. For
the current authenticated squad it surfaces the Tanaka/Senesi versus Truffert/Groß structural
difference, the 0.91 projected-point gap and the captaincy difference instead of reducing the
assessment to a single player card. The post-GW1 sync action now runs authenticated MCP squad sync
and then the correct next-decision-event pipeline rather than opening a dead control.

The refreshed GW2–GW6 synthetic rehearsal against this exact published squad passed again at full
10,000/25,000 residual/component simulation sizes. It selected a legal roll route, carried two free
transfers forward, chose a 4-3-3 from all 15 and kept Bruno captain. A separate phase-boundary test
proves the promoted 20% preseason defender-market feature becomes a zero-weight weekly feature as
soon as the official GW1 deadline passes.

The full repository regression suite now passes all 447 collected tests, with one upstream
Starlette TestClient deprecation warning. Python lint, frontend lint and the production frontend
build also pass. The web API launcher was exercised separately and returns to the shell after one
`Ctrl+C` without a lingering worker.

Current-season feature parity is now enforced. The app-open weekly refresh automatically archives
each newly final/data-checked official event-live payload and rolls its xG, xA, minutes, points, BPS
and defensive-contribution rows into future forecasts. Final fixture scores also update the online
opponent-adjusted team model. A new checksum-bound contract reconciles event rows to FPL cumulative
totals and proves that the latest event reached the forward matrix; missing/schema-changed data
blocks publication. It also fixes the weekly horizon to move forward (for example GW2–GW6 after
GW1) instead of remaining anchored to GW1. See the
[live feature availability contract](../reports/live-feature-availability-contract.md).

The first mean-reversion policy audit is also complete. Recent FPL points have only about 9.1%
next-event persistence in the historical regular-player sample, and process confirmation materially
separates useful form from noisy returns. A conservative process-confirmed correction improved the
untouched 2025/26 exact policy replay by 23 net points with less churn, but its block-bootstrap
downside interval still crossed zero. It therefore runs as a zero-authority shadow world; direct xP
remains production champion. See the
[form-reversion policy replay](../reports/form-reversion-policy-replay.md).

The first attacking chance-quality challenger is complete and rejected. It added strictly lagged
10- and 38-event goals, assists, xG, xA and minutes; derived shrunk per-90 rates, team attacking
shares and finishing/assist surplus; and reused the champion appearance probabilities so minutes
could not confound the comparison. A 10% blend lost 50 continuous-path points in 2023/24 while
gaining 34 in 2024/25; a 20% blend gained 67 in 2023/24 while losing 41 in 2024/25. The preregistered
multi-season maximin rule therefore selected zero. The raw challenger also reduced top-player
capture for both MID and FWD in the untouched 2025/26 season. It has zero decision authority and
cannot alter or invalidate the current forecast cache. See the
[attacking chance-quality report](../reports/attacking-chance-quality-challenger.md).

Three further forecast/decision attacks are now complete. A role-aware appearance residual
calibrator improved selected probability metrics but lost 23 points in its selection policy season
and eight in the untouched season, so production participation remains unchanged. A separate
lead-specific GW+1–GW+7 XGBoost model gained ten exact-policy points in both forward seasons and is
recorded as `PASS_HISTORICAL_HOLD_SHADOW`; it cannot serve production xP without prospective
replication. Its current-season 10,000-world adaptive tournament nominated a Collins/Semenyo/Yates
variant of the published squad. That variant passed the bounded request gate, was injected as a
forecast-scoped protected seed, and received the complete robust, horizon and synthesis tests. It
then recorded 3.617 regret in the independent robust family and 0.488 in the horizon family;
synthesis retained `R-dc7de17def`. The adaptive receipt is therefore closed as
`FULL_PIPELINE_RETAIN_INCUMBENT`, and stale challengers automatically lose seed protection when the
forecast checksum changes.

### Delivery order

1. Poll `fplagent collect-current-market-goals` at the scheduled refresh windows. It reads the
   provider's upcoming-fixture feed, verifies the page upload timestamp precedes the FPL deadline,
   and requires all ten GW1 fixtures plus complete non-closing 1X2/totals odds. Until that receipt
   says `ready`, production is unchanged. Once ready, archive it and run the market challenger
   through the complete shadow GW1 funnel before considering promotion.
2. Repeat the proven `gw1-deadline-run` command at the scheduled refresh windows, after material
   news and immediately before the deadline. It owns the full
   anchor, residual tournament, component selection/holdout, global search, horizon audit and staged
   synthesis sequence; unchanged generations are reused and failed evidence cannot replace the
   active decision.
   After a changed decision is published, run `fplagent audit-current-squad` to revalidate its exact
   XI, bench priority and captaincy against every legal use of the selected 15.
3. Exercise the implemented immutable manager-state contract on the first complete authenticated
   post-GW1 response and publish its first real weekly decision receipt. Preseason or incomplete
   fields already report `not_ready`; they are never invented.
   The publisher now archives every successful event receipt. The normal weekly refresh
   automatically collects any missing finished/data-checked event outcomes and rebuilds live
   features. Then run `fplagent score-weekly-event`; the explicit `fpl-data
   collect-event-outcome` command remains available for repair/inspection. These paths fail closed
   and cannot receive a real 2026/27 outcome before GW1 has been played.
4. Continue evaluating every weekly action against all 15 players and the same forecast worlds so
   transfers, formation, bench order and captaincy cannot contradict one another.
   The blunt sequential market-rate replacement remains rejected after losing two points on its
   untouched season. A second policy that learns Betfair scoring and clean-sheet prices as player
   features improved defender MAE/top-k points in all three forward seasons and legal season totals
   by +64, +76 and +90. Its bounded 20% blend now has preseason squad/XI authority on fully covered
   events. Direct xP remains the weekly transfer champion because the pooled downside interval
   narrowly missed the declared gate; do not expose the market feature signal to weekly transfer
   generation yet. The first player-return challenger has now produced
   positive validation, untouched sequential and three-season independent results, but remains a
   25% shadow blend because its block downside gate missed narrowly. Freeze its current-season
   scores prospectively at each deadline; production direct xP remains the authority until that
   receipt stream demonstrates stable value.
5. Improve participation and minutes forecasts under frozen forward tests, then improve team and
   player event rates only when challengers beat the current champions in decision replay. The
   broad attacking chance-quality expansion has now failed that standard, so the next player-rate
   experiment is narrower role-aware empirical shrinkage rather than another larger black-box
   attack model.
   The first historical role-feature challenger has now been rejected: only GK passed its
   statistical screen, then lost 0.013 points/GW in the exact policy replay with a confidence
   interval crossing zero and a negative season floor. The current preseason lineup layer is
   collected with provenance and covers 20/20 clubs, but remains scenario-only because complete-
   minute coverage is only 36.6% and post-World-Cup friendlies are unusually noisy. The current
   published squad remains the production champion; its leading role-stress alternative is only
   ninth in the multi-gameweek synthesis and carries more aggregate regret. Next, prioritise
   attributable official availability, manager comments and competitive-role evidence. A friendly
   observation may trigger verification, but only an explicit, corroborated participation change
   should enter a staged forecast and complete deadline-funnel rebuild.
6. Accumulate prospective rearrangement and chip receipts, improve the rejected retained-timing
   policies, and replay WC, FH, BB and TC jointly. The exact searches, point-in-time schedule model
   and separate continuous replays are present; neither historical downside gate passed. Every chip
   output remains operationally `no_chip` until stronger policies pass untouched and prospective
   tests without weakening the declared bounds.

The acceptance metrics and release gates live in the
[points-first season roadmap](../reports/points-first-season-roadmap.md). The web app and chat are
interfaces onto these deterministic outputs; neither is allowed to invent the numeric decision.
