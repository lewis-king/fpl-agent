# FPLAgent technical documentation

This directory contains the stable, project-level explanation of how FPLAgent is assembled. The
`reports/` directory contains dated research, experiments and decision receipts; `docs/` describes
the architecture that application and model work should continue to follow.

## Active workstream

**Latest audit — 21 October:** [GW1–7 results and Fantasy Football Scout product review](../reports/scout-product-audit-and-gw7-review-2026-10-21.md).
Includes authenticated feature inspection, official results, prospective calibration warnings,
the new Season review screen and the next points-first experiments. This supersedes the dated
September status below. No GW8 recommendation was regenerated during that audit.

**Latest search audit:** [GW4 deep search, exact configurations and independent holdouts](../reports/weekly-deep-search-2026-09-09.md).
The completed 100-route / 540-policy audit retained Richarlison → Evanilson: the expanded-search
Gonzalo challenger failed the predeclared points-based holdout acceptance test. The report includes
reproduction commands, exact search scope, the production/research boundary and next priorities.

**Latest release review:** [explicit promote/reject decisions, 9 September](../reports/points-first-promotion-decisions-2026-09-09.md).
The current experiment versions have concluded deployment decisions, not pending approvals.
This includes the additional admissible-risk-reference fix and its frozen-decision replay.

The current implementation and evidence priorities are in the
[9 September points-first improvement plan](decision-improvement-roadmap-2026-09-09.md).
It distinguishes shipped correctness fixes, integrated research diagnostics and unproven changes
that must still earn promotion. GW4 is now the actionable deadline.

The latest [round-two implementation, validation and publication report](../reports/points-first-validation-round2-2026-09-09.md)
records shared-world transfer/chip planning, the full-season chip-state audit, role-change rejection,
allocation/risk comparisons, prospective capture and the final refreshed GW4 recommendation.

The [adaptive-transfer follow-up](../reports/adaptive-transfer-replay-2026-09-09.md) records the
paired historical test, its failed activation screen, prospective challenger scoring and fresh
GW4 publication. It supplements the first implementation batch rather than replacing its receipts.

Start a new engineering or AI-agent session with the
[continuation handoff](agent-continuation-handoff.md). Its dated addenda record the current state,
service commands, subsystem authority, validation failures, dirty-worktree warning and prioritised
next actions. It supersedes dated preseason status paragraphs where they conflict with current
runtime receipts.

The final bounded V9 LoRA experiment concluded on 8 August 2026 and was rejected by the locked
promotion gate. It improved application tool routing and screenshot extraction, but did not improve
strict response contracts, legacy coverage, held-out vision reliability or blind qualitative
quality enough to ship. Application defaults remain base Qwen for guarded chat and the separately
scoped V3 path for guarded screenshot research. Further LLM training is parked. The active objective
is points-first engineering: fresh and reproducible inputs, stronger participation and points
forecasts, exact weekly state, and robust roll/transfer/lineup/captain/chip decisions. The V5-V9
history is preserved in the [experiment hand-off](../reports/fpl-llm-v5-experiment.md). The
full user-facing priority board is in the [points-first product roadmap](points-first-roadmap.md),
with the deeper research log in the
[points-first season roadmap](../reports/points-first-season-roadmap.md).

## Architecture guides

- [Local saved FPL login](local-saved-fpl-login.md): optional owner-only credentials file, automatic
  MCP sign-in, retry limits, plaintext storage trade-off and validation.
- [Application capabilities and manual test guide](application-capabilities-and-manual-test.md):
  complete current product behavior, process topology, manual browser journey, health checks and
  honest boundaries.
- [Points-first product roadmap](points-first-roadmap.md): prioritised full-season plan covering
  app-open refresh, GW1, weekly transfers, prices, chips, blanks/doubles and prospective validation.
- [GW1 deadline runbook](gw1-deadline-runbook.md): exact full-run, falsification and deadline-pack
  commands, publication gates, deadline cadence and fail-closed recovery.
- [Price-change and early-transfer policy](early-transfer-policy.md): 15-minute official market
  telemetry, UK-midnight outcome calibration, exact affordability stress and the zero-authority
  promotion boundary for move-now-versus-wait advice.
- [Participation and predicted-lineup evidence](participation-evidence.md): attributable source
  capture, freshness and player matching, zero-authority consensus, double-gameweek safeguards and
  the live promotion scoreboard.
- [Forecast source authority](forecast-source-authority.md): the hard ban on FPL-authored xP,
  ownership of the production hurdle forecast, bounded bookmaker authority and the promotion gate
  for independently sourced player statistics.
- [Chip decision and retention shadow](squad-chip-shadow.md): exact permanent/temporary squad
  search, probabilistic rearrangements, continuous historical WC/FH and BB/TC timing replays, and
  historical shadow evidence. For current BB/TC authority and the WC/FH limits, use
  [joint chip strategy v2](chip-strategy-v2.md).
- [FPL LLM architecture](fpl-llm-architecture.md): base model, locally trained LoRA adapters,
  Unsloth/PEFT loading, multimodal team import, grounded tools, future RAG and promotion policy.
- [Interactive LLM technical explainer](../reports/fpl-llm-technical-summary.html): standalone HTML
  walkthrough of the exact CLI runtime, system prompt, optional LoRA loading, fine-tuning mechanics,
  RAG/tool boundaries, context-window trade-offs and measured adapter results.
- [Web application architecture](web-application-architecture.md): phase-aware product experience,
  screenshot onboarding, active manager state, local MCP topology and hosted security boundary.
- [Local web application run guide](../web/README.md): process topology, commands, implemented
  preseason journeys, authenticated squad sync and current limits.
- [Decision-engine blueprint](../reports/decision-engine-blueprint.md): deterministic forecasting,
  simulation, optimisation and decision-receipt foundation.
- [Points-first season roadmap](../reports/points-first-season-roadmap.md): ordered work to improve
  live data, minutes, weekly transfers, chips, forecasts and prospective decision quality.
- [Project status](project-status.md): explicit LLM freeze, completed decision-engine foundations
  and the next points-first milestones.
- [2026/27 BPS external validation](../reports/2026-27-bps-external-validation.md): provenance-bound
  advisory comparison of the live outfield correction with a public 537-player reconstruction.
- [2026/27 preseason role evidence](../reports/preseason-role-evidence-audit.md): archived friendly
  lineups, conservative player resolution, current-squad flags and the scenario-only promotion
  boundary.
- [Preseason role scenario audit](../reports/preseason-role-scenario-audit.md): checksum-bound
  conditional-DNP sensitivity across the published 15 and all 37 synthesis finalists, with
  independent selection and holdout worlds.
- [Preseason availability threshold](../reports/preseason-role-threshold-audit.md): a read-only,
  selection/holdout curve locating how severe the declared role-retention stress must become before
  the strongest scenario challenger has support in both simulation families.
- [Full-pool one-swap audit](../reports/gw1-one-swap-adversarial-audit.md) and
  [forced full-pipeline replay](../reports/gw1-one-swap-full-pipeline-replay.md): exhaustive legal
  neighbour coverage followed by equal robust, horizon and synthesis testing of the strongest
  omitted candidate.
- [Free-transfer option-value calibration](../reports/terminal-free-transfer-value.md): frozen
  historical state construction, held-out promotion gate and the terminal flexibility curve used
  by weekly roll-versus-transfer decisions.
- [Planning-horizon and decay calibration](../reports/horizon-decay-policy-replay.md): deadline-safe
  GW1–8 receding-horizon replay across 1/3/5/8-week policies, historically legal free-transfer
  banks, realised autosub/captain scoring and a sealed-season promotion gate. The first run retains
  the 8-week/0.88 incumbent because the 5-week challenger did not generalise.
- [Final synthesis-selector replay](../reports/synthesis-selector-policy-replay.md): realised
  GW1–5/GW1–8 regret families, leave-one-season-out weight selection and a sealed 2025/26 gate for
  the live 0.50 family balance and 0.20 minimax surcharge.
- [GW1 scoring/formation/autosub stress](../reports/gw1-scoring-formation-autosub-stress.md): exact
  autosubs across every synthesis finalist and five bench-proxy challengers under bounded bonus
  and defensive-contribution misspecification.
- [GW1 deadline pack](../reports/gw1-deadline-pack.md): the final human-readable squad plus the
  checksum-bound official, market, search, participation, scoring and bench publication gates.
- [GW1 multi-seed decision stability](../reports/gw1-deadline-stability.md): the five leading legal
  squads rerun on independent simulations and a bounded synthesis-weight grid, with a fail-closed
  publication gate for seed sensitivity and material objective brittleness.
- [GW1 canonical execution receipt](../reports/gw1-deadline-execution.html): the exact 15, XI,
  bench order, captaincy and chip instruction that may be entered only after every machine gate
  passes.
- [Player-specific participation break-even](../reports/gw1-participation-break-even.md): isolated
  expected-minutes curves for the watched squad players, with cross-model holdout boundaries for
  switching away from the incumbent.
- [GW1 deadline contingencies](../reports/gw1-deadline-contingencies.md): complete legal fallback
  squads and configurations tied to the supported participation triggers.
- [GW1 chip decision](../reports/gw1-chip-decision.md): exact no-chip, Bench Boost and Triple
  Captain uplift on shared worlds, separated from the retained-option authority required to spend
  a chip.
- [Role-residual policy replay](../reports/role-residual-policy-replay.md): a position-aware
  participation challenger whose probability calibration improved for GK/FWD but lost points in
  both legal policy seasons, so it was rejected with zero production authority.
- [Lead-time forecast replay](../reports/lead-time-forecast-policy-replay.md): separate GW+1 to
  GW+7 player forecasts using only deadline-safe origin information. It gained ten historical
  points in both forward seasons, which authorises a current-season shadow—not production use.
- [Adaptive preseason stress](../reports/adaptive-preseason-lead-stress.md): paired base/lead
  transfer policies across 10,000 correlated worlds and role downside. Its initial challenger
  passed the bounded request gate, then lost the complete robust/horizon/synthesis funnel; the
  published squad was retained.
- [Pre-closing market goal-rate challenger](../reports/market-goal-rate-challenger.md) and
  [legal selection replay](../reports/market-goal-policy-replay.md): provenance-bound fixture
  probabilities, frozen forecast metrics, exact squad/XI/bench/captain scoring and the strict live
  feed readiness boundary.
- [Sequential market transfer replay](../reports/market-goal-sequential-transfer-replay.md): a
  continuous 38-deadline validation/test path with exact bank, selling prices, carried free
  transfers and hits; it rejects the market signal as weekly transfer authority.
- [Distribution-aware player-return challenger](../reports/return-distribution-challenger.md): a
  season-forward three-band return model, validation-only blend choice and exact independent plus
  continuous policy replays; strong positive point estimates remain shadow-only because the
  predeclared block-uncertainty gate did not pass.
- [Attacking chance-quality challenger](../reports/attacking-chance-quality-challenger.md): a
  deadline-safe MID/FWD test of longer-horizon xG/xA, per-90 rates, team attacking share and
  finishing regression. Its conflicting development-season legal paths selected zero weight, so
  the production forecast remains unchanged.
- [Understat preseason feature challenger](../reports/understat-preseason-feature-challenger.md):
  immutable prior-season independent player data, deterministic FPL mapping, season-forward
  forecast tests and exact legal transfer replays. The first run selected zero production weight.
- [Data documentation](../data/README.md): source extraction, normalized schemas, provenance and
  point-in-time safeguards.

## Current implementation reports

- [Grounded chat runtime v1](../reports/fpl-llm-chat-runtime-v1.md)
- [Multimodal LLM foundation](../reports/fpl-llm-foundation.md)
- [V3 fine-tuning report](../reports/fpl-llm-training-v3.md)
- [V4 correction experiment](../reports/fpl-llm-training-v4.md)
- [V5-V9 application-conversation experiments and pause hand-off](../reports/fpl-llm-v5-experiment.md)
- [Canonical 2026/27 decision-engine whitepaper](../reports/fplagent-algorithm-technical-whitepaper-standalone.html):
  self-contained, printable version 2.0 account of the published squad, source authority,
  point-in-time forecast, bookmaker calibration, simulation, legal global search, season-long
  engine, evidence ledger and honest state-of-the-art claim boundary. The maintainable source is
  [Markdown](../reports/fplagent-algorithm-technical-whitepaper.md).
- [Earlier generated GW1 paper](../reports/fplagent-gw1-2026-27-whitepaper.html): retained as a
  historical presentation artifact; it is no longer the canonical methodology receipt.
- [State-of-the-art readiness audit](../reports/fplagent-sota-readiness-audit.md): machine-derived
  production and research-frontier gates behind the white paper.
- [SOTA evidence framework](sota-evidence-framework.md): implementation and promotion contracts
  for independent player-event data, the matched OpenFPL benchmark, untouched 2026/27 outcomes,
  predicted lineups, full-distribution calibration and price/liquidity scenarios.

The canonical training and command reference remains in [the LLM workspace README](../llm/README.md).
