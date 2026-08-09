# FPLAgent project status

**Status date:** 8 August 2026  
**Active objective:** maximise season points through reliable forecasts and legal, robust FPL
decisions.

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
  It polls a typed status contract, joins duplicate requests, exposes the successful pipeline hash
  in provenance, and retains the prior receipt on blocked, failed or interrupted runs. The daemon
  worker also prevents a long tournament from blocking local server shutdown.
- The same coordinator now owns automatic T−72h, T−24h, T−6h, T−60m and T−10m runs. A lightweight
  semantic probe detects material public FPL status/news, price, rule and fixture changes between
  windows on a deadline-sensitive cadence; ordinary transfer-counter movement is deliberately left
  for the cheaper price telemetry stream.
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
- The first checksum-bound preseason role sensitivity audit now exhaustively reoptimizes all 550
  legal XIs for the published 15 and screens all 37 cross-family synthesis finalists on 5,000
  selection and 25,000 independent holdout worlds per model family. Baseline and moderate stress
  retain the published squad and configuration. Severe stress first screens `R-5043bb75d6`, then
  confirms it after both squads receive the same exhaustive configuration search: +0.079 residual
  points (95% CI +0.042 to +0.116) and +0.162 component points (+0.079 to +0.245). The deliberately
  extreme repeated-absence DNP boundary also confirms the challenger and changes the within-15
  configuration. These are verification triggers, not promotions, and production remains
  unchanged.
- A fresh-seed threshold audit now narrows that severe result. Along the declared coupled path,
  `R-5043bb75d6` remains supported only through 51.0% conditional appearance retention for
  three-plus-lineup absences (75.6% for role-watch players); at 51.5%/75.9%, the component-family
  interval crosses zero. At the supported edge the paired gain is +0.066 residual points (95% CI
  +0.028 to +0.103) and +0.086 component points (+0.002 to +0.169). This is an extreme, knife-edge
  verification trigger, not an inferred availability probability or a reason to change the squad.
- The threshold run also exposed and fixed an unordered historical residual-bootstrap query. The
  pool is now explicitly ordered by season, event and player, making identical seeded simulations
  byte-reproducible across separate processes.
- A checksum-bound availability watch now joins the current 15 to official FPL status/news, aligned
  GW1 `p_play`, preseason role evidence and the supported stress boundary. The current receipt finds
  zero official doubts, four role-verification players (Watkins, Bruno Fernandes, Truffert and
  Calvert-Lewin) and four explicit uncovered-feed players (Collins, Igor Thiago, Verbruggen and
  Groß).
  Its action is `retain_decision_and_verify_flagged_players`; advisory evidence is structurally
  unable to authorize a production change. A compact view is included in `deadline-status`.
- The GW1 publisher now creates the squad-specific role scenario, stress threshold and availability
  watch inside the same fingerprinted staging transaction as synthesis. Publication requires a
  current aligned watch, final checksums are revalidated after the atomic switch, and any failure
  restores the complete previous artifact set. The live lineup source was refreshed on 8 August:
  it currently has 53 confirmed lineup events and coverage for 18 of 20 clubs; Brentford and
  Brighton remain explicit unknowns.
- A full-pool one-swap audit now enumerates all 2,259 legal same-position replacements around the
  published squad. It found a genuine horizon-membership omission, Mukiele to Senesi. Equal
  full-field replay ranks the challenger second of 49 over the eight-week horizon (+0.316 central
  points versus the published squad, 95% CI +0.181 to +0.452), but only 27th of 65 in the five-week
  robustness family (-0.783, -0.928 to -0.637). Its synthesis regret is 1.498 versus 0.906 for the
  incumbent, so the challenger is rejected and production remains unchanged. The horizon audit
  now protects 32 deterministic legal neighbours drawn across the top eight robust seeds; a live
  generation check includes the exact Senesi squad. This closes the membership gap for the next
  complete deadline run without allowing a fixed-squad winner to bypass synthesis.
- A provenance-bound pre-closing market goal-rate challenger now maps 2,660 historical Premier
  League fixtures to FPL IDs and uses only de-vigged non-closing 1X2 and over/under prices. On the
  frozen 2023/24–2025/26 set it improves Poisson deviance from 1.0892 to 1.0514, goal MAE from
  0.9331 to 0.9179 and clean-sheet Brier from 0.1702 to 0.1678. A blend selected on 2024/25 gains
  5.00 realised points/GW on the untouched 2025/26 independent-gameweek legal selection replay
  (95% interval +1.34 to +8.66), including +2.18/GW versus the internal component signal at the
  same weight. It remains shadow-only: the live feed currently covers zero of ten GW1 fixtures,
  and an independent-gameweek rebuild is not a sequential transfer-policy result. The completed
  continuous replay then selected a conservative 25% market weight on 2024/25 (+145 net points)
  but lost the untouched 2025/26 path by two points (`2005` versus `2007`), with a four-GW block
  interval of -3.18 to +2.87 points/GW. Market odds are therefore rejected for weekly transfer
  authority and retained only as a GW1 shadow candidate.
- A distribution-aware player-return challenger now targets the largest measured decision gap:
  ordering the already-good players competing for the XI, captaincy and transfers. Its three
  season-forward bands are under five points, 5–9 and 10+. Validation chose a 25% blend, improving
  the continuous 2024/25 path by 99 net points; the untouched 2025/26 path improved by 94. The same
  frozen blend improved independent legal selection by 41, 94 and 60 points across the three OOF
  seasons. It remains `HOLD_SHADOW`, because the frozen four-GW interval (-0.211 to +5.132/GW)
  missed the predeclared -0.10 downside floor. Production forecasts and decisions are unchanged.

## Immediate delivery order

### Current handoff

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

The latest complete live runner now publishes `R-e80223d1fc`: 5-3-2, Bruno Fernandes captain,
Tarkowski vice-captain, £100.0m spent and £0.0m bank, with 58.557 projected GW1 points. It is bound
to direct forecast `955b8082…`, component forecast `e860770e…`, decision `37dd264b…` and pipeline
fingerprint `219e232a…`. The evidence gate has zero issues. The XI is Donnarumma; Tarkowski,
Collins, Maguire, Mukiele and Truffert; Bruno Fernandes, Mbeumo and Gibbs-White; Igor Thiago and
Watkins. The bench order is Calvert-Lewin, Szoboszlai, Groß and Verbruggen. An immediate identical-
input invocation completed in approximately 4.5 seconds with `reused: true` and started no
optimisation stage. The decision remains provisional and must be refreshed as material news or the
deadline window changes.

The live role audit finds no supported alternative on its tested stress path. The availability
watch is current and cannot authorize a decision change: all 15 players are officially available,
while Watkins, Truffert, Calvert-Lewin and Bruno require attributable role verification and the
four Brentford/Brighton selections have no confirmed structured preseason feed. These are explicit
deadline checks rather than hidden assumptions.

The published 15 has also passed a checksum-bound, read-only local-decision audit. Its exact XI,
bench order, Bruno captaincy and Tarkowski vice-captaincy were independently recovered as the top
robust holdout configuration. A numerically tiny baseline squad-screen alternative was not
supported by either model-family holdout, so it cannot mutate the published decision.

GW1 is also ready for prospective evaluation. The current contract freezes `R-e80223d1fc`, its
serious alternatives, relevant player forecasts, decision/shortlist/forecast/bootstrap hashes and
the official 21 August deadline. It is stored under `data/decisions/weekly/event-1/` without
mutating the live decision. Future changed generations create this contract inside
`gw1-deadline-run`; a failed freeze rolls the publication and evidence receipt back.

The connected-squad web critique now compares all 15 players with this published benchmark. For
the current authenticated squad it surfaces the Tanaka/Senesi versus Truffert/Groß structural
difference, the 0.91 projected-point gap and the captaincy difference instead of reducing the
assessment to a single player card. The post-GW1 sync action now runs authenticated MCP squad sync
and then the correct next-decision-event pipeline rather than opening a dead control.

Static checks and the explicitly selected non-LLM engine, data and web suite pass: 303 tests, with
one upstream Starlette TestClient deprecation warning. Parked LLM and chat test modules are excluded
from this points-first regression command.

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
   The first sequential market-signal gate is complete and rejected: validation-selected shrinkage
   did not improve the untouched season. Direct xP remains the weekly champion; do not expose the
   market signal to transfer generation. The first player-return challenger has now produced
   positive validation, untouched sequential and three-season independent results, but remains a
   25% shadow blend because its block downside gate missed narrowly. Freeze its current-season
   scores prospectively at each deadline; production direct xP remains the authority until that
   receipt stream demonstrates stable value.
5. Improve participation and minutes forecasts under frozen forward tests, then improve team and
   player event rates only when challengers beat the current champions in decision replay.
   The first historical role-feature challenger has now been rejected: only GK passed its
   statistical screen, then lost 0.013 points/GW in the exact policy replay with a confidence
   interval crossing zero and a negative season floor. The current preseason lineup layer is now
   collected with provenance, but remains scenario-only because its minute coverage is 35.3% and
   two clubs are missing. The first explicit late-return/uncertain-role audit is complete: baseline
   and moderate stress are stable. Equal exhaustive configuration replay confirms
   `R-5043bb75d6` under severe and DNP-boundary assumptions, but public context indicates Watkins
   and Bruno Fernandes are late World Cup returners rather than confirmed injury absences. The
   refined curve shows that the challenger needs approximately half of their already-modelled
   appearances to be removed alongside the coupled role-watch stress before both families support
   it. Next, refresh their remaining friendlies and attributable press-conference evidence. Only if
   those observations justify an explicit forecast change should it enter a staged forecast and
   complete deadline-funnel rebuild.
6. Accumulate prospective rearrangement and chip receipts, improve the rejected retained-timing
   policies, and replay WC, FH, BB and TC jointly. The exact searches, point-in-time schedule model
   and separate continuous replays are present; neither historical downside gate passed. Every chip
   output remains operationally `no_chip` until stronger policies pass untouched and prospective
   tests without weakening the declared bounds.

The acceptance metrics and release gates live in the
[points-first season roadmap](../reports/points-first-season-roadmap.md). The web app and chat are
interfaces onto these deterministic outputs; neither is allowed to invent the numeric decision.
