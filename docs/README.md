# FPLAgent technical documentation

This directory contains the stable, project-level explanation of how FPLAgent is assembled. The
`reports/` directory contains dated research, experiments and decision receipts; `docs/` describes
the architecture that application and model work should continue to follow.

## Active workstream

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

- [Application capabilities and manual test guide](application-capabilities-and-manual-test.md):
  complete current product behavior, process topology, manual browser journey, health checks and
  honest boundaries.
- [Points-first product roadmap](points-first-roadmap.md): prioritised full-season plan covering
  app-open refresh, GW1, weekly transfers, prices, chips, blanks/doubles and prospective validation.
- [Price-change and early-transfer policy](early-transfer-policy.md): 15-minute official market
  telemetry, UK-midnight outcome calibration, exact affordability stress and the zero-authority
  promotion boundary for move-now-versus-wait advice.
- [Chip decision and retention shadow](squad-chip-shadow.md): exact permanent/temporary squad
  search, probabilistic rearrangements, continuous historical WC/FH and BB/TC timing replays, and
  the evidence explaining why every chip policy still has zero authority.
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
- [Data documentation](../data/README.md): source extraction, normalized schemas, provenance and
  point-in-time safeguards.

## Current implementation reports

- [Grounded chat runtime v1](../reports/fpl-llm-chat-runtime-v1.md)
- [Multimodal LLM foundation](../reports/fpl-llm-foundation.md)
- [V3 fine-tuning report](../reports/fpl-llm-training-v3.md)
- [V4 correction experiment](../reports/fpl-llm-training-v4.md)
- [V5-V9 application-conversation experiments and pause hand-off](../reports/fpl-llm-v5-experiment.md)
- [Algorithm technical whitepaper](../reports/fplagent-algorithm-technical-whitepaper.md)

The canonical training and command reference remains in [the LLM workspace README](../llm/README.md).
