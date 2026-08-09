# FPLAgent data and decision foundation

> **Active objective — 7 August 2026:** maximise season points through the deterministic data,
> forecast, squad-selection and weekly decision engine. LoRA/LLM improvement work is parked; no
> training or adapter experiments should run unless Lewis explicitly reopens it. See the
> [current project status](docs/project-status.md) and
> [points-first season roadmap](reports/points-first-season-roadmap.md).

This repository builds a reproducible, point-in-time data foundation for FPLAgent. It
downloads only publicly retrievable files and no-login endpoints, preserves raw payloads,
records provenance and produces analysis-ready Parquet tables.

The repository now also contains the first vertical slice of the decision engine: strict
point-in-time feature construction, CUDA-only position models, rolling out-of-season tests,
current-rules validation and a transfer-aware GW1 squad optimiser.

The initial build contains four complementary evidence layers:

- the complete 2025/26 Solio manager outcome index;
- factual decision trails for the 2025/26 top 100 from FPL Genius;
- multi-season veteran-manager spreadsheets published by Mike Croft;
- historical player, fixture and top-manager data from Vaastav and smaller public archives.

## Project technical documentation

- [Technical documentation index](docs/README.md)
- [FPL LLM architecture: Qwen base, LoRA fine-tune, Unsloth/PEFT runtime and grounded tools](docs/fpl-llm-architecture.md)
- [Web application architecture and phase model](docs/web-application-architecture.md)
- [Local web application run guide](web/README.md)
- [LLM training and command reference](llm/README.md)

The FPL Genius integration is deliberately isolated. Its endpoint is public and requires no
login, but it is undocumented and is not treated as a production dependency or a licensed
bulk-data source. Raw responses are cached and factual fields are separated from its modelled
scores.

## Research reports

- [Canonical algorithm technical whitepaper — standalone, email-ready HTML](reports/fplagent-algorithm-technical-whitepaper-standalone.html)
- [Canonical algorithm technical whitepaper — Markdown](reports/fplagent-algorithm-technical-whitepaper.md)
- [Interactive GW1 model story — standalone, email-ready HTML](reports/gw1-model-story-standalone.html)
- [Visual GW1 picker whitepaper — standalone, email-ready HTML](reports/gw1-picker-whitepaper-standalone.html)
- [Visual whitepaper source](reports/gw1-picker-whitepaper.html)
- [Full 2026/27 GW1 picker technical report and improvement programme](reports/gw1-picker-technical-report.md)
- [Decision-engine foundation](reports/decision-engine-blueprint.md)
- [Adversarial review of the foundation](reports/decision-engine-adversarial-review.md)
- [Points-first 2026/27 season roadmap](reports/points-first-season-roadmap.md)
- [Historical edge study](reports/historical-edge.md)
- [Executable model-data quality gate](reports/data-quality.md)
- [Historical GW1 picker backtest](reports/picker-backtest.md)
- [Initial 2026/27 GW1 squad receipt](reports/gw1-initial-squad.md)
- [GW1 adversarial acceptance audit](reports/gw1-adversarial-audit.md)
- [GW1–5 128-squad survival tournament](reports/gw1-squad-tournament.md)
- [GW1–5 match-component tournament](reports/gw1-component-tournament.md)
- [Season-forward player-component backtest](reports/component-player-backtest.md)
- [2026/27 BPS reconstruction](reports/2026-27-bps-reconstruction.md)
- [2026/27 BPS external validation](reports/2026-27-bps-external-validation.md)
- [Selectable-player appearance reliability audit](reports/appearance-reliability-audit.md)
- [2026/27 preseason lineup and role evidence audit](reports/preseason-role-evidence-audit.md)
- [Preseason role scenario sensitivity audit](reports/preseason-role-scenario-audit.md)
- [Preseason availability-retention threshold audit](reports/preseason-role-threshold-audit.md)
- [Bench and formation adversarial review](reports/bench-and-formation-adversarial-review.md)
- [Promoted provisional GW1 squad](reports/gw1-promoted-squad.md)
- [GW1 scalable robust-search funnel](reports/gw1-robust-search.md)
- [GW1 global robust-search funnel](reports/gw1-global-robust-search.md)
- [GW1 horizon-adequacy audit](reports/gw1-horizon-adequacy-audit.md)
- [GW1 synthesized five/eight-week decision](reports/gw1-synthesized-decision.md)
- [Current published 15: exhaustive XI, captain and bench audit](reports/current-squad-xi-captain-bench-audit.md)
- [Full-pool one-swap membership audit](reports/gw1-one-swap-adversarial-audit.md)
- [One-swap forced robust/horizon/synthesis replay](reports/gw1-one-swap-full-pipeline-replay.md)
- [Pre-closing market goal-rate challenger](reports/market-goal-rate-challenger.md)
- [Market goal-rate legal selection replay](reports/market-goal-policy-replay.md)
- [Market goal-rate sequential transfer replay](reports/market-goal-sequential-transfer-replay.md)
- [Distribution-aware player-return challenger](reports/return-distribution-challenger.md)
- [Multimodal FPL LLM foundation, measured baseline and training plan](reports/fpl-llm-foundation.md)
- [Grounded FPL chatbot runtime v1](reports/fpl-llm-chat-runtime-v1.md)
- [V5-V9 application-conversation LoRA experiments and pause hand-off](reports/fpl-llm-v5-experiment.md)

## Quick start

```bash
uv sync
uv run fpl-data build
uv run fpl-data validate
uv run fpl-data analyse
uv run fpl-data refresh-current
uv run fpl-data snapshot-status
uv run fpl-data collect-preseason-lineups
uv run fplagent deadline-status
uv run fplagent availability-status
uv run fplagent gw1-deadline-run --reuse-latest-official
```

Build and interrogate the first squad picker:

```bash
uv run fplagent prepare --horizon 8
uv run fplagent gpu-check
uv run fplagent train
uv run fplagent backtest-picker
uv run fplagent audit-appearances
uv run fplagent audit-role-appearance
uv run fplagent replay-role-appearance
uv run fplagent audit-preseason-role
uv run fplagent audit-preseason-threshold
uv run fplagent availability-status
uv run fplagent reconstruct-bps --simulations 400 --seed 20260803
uv run fplagent validate-bps --refresh
uv run fplagent forecast
uv run fplagent squad --stability-samples 20
uv run fplagent tournament --candidates 128 --selection-simulations 5000 --holdout-simulations 25000
uv run fplagent train-components
uv run fplagent train-component-events --force-targets
uv run fplagent forecast-components
uv run fplagent backtest-components
uv run fplagent audit-market-goals
uv run fplagent replay-market-goals
uv run fplagent replay-market-transfers
uv run fplagent backtest-return-distribution
uv run fplagent collect-current-market-goals
uv run fplagent component-tournament --simulations 5000 --seed 20260802
uv run fplagent component-candidates
uv run fplagent component-tournament --simulations 25000 --seed 20260803
uv run fplagent bench-audit --simulations 25000 --seed 20260803
uv run fplagent promote-gw1
uv run fplagent robust-search --discovery-candidates 10000 --screen-simulations 2000 --shortlist 512 --selection-simulations 5000 --finalists 64 --holdout-simulations 25000
uv run fplagent horizon-audit --horizon-candidates 128 --selection-simulations 5000 --finalists 48 --holdout-simulations 25000
uv run fplagent synthesize-gw1 --horizon-family-weight 0.50 --family-worst-weight 0.20
uv run fplagent gw1-deadline-run --reuse-latest-official
uv run fplagent deadline-status --manager-entry-id YOUR_FPL_ENTRY_ID
uv run fplagent deadline-run --manager-entry-id YOUR_FPL_ENTRY_ID
uv run python scripts/build_interactive_model_story.py
uv run python scripts/build_algorithm_whitepaper.py
```

Build and inspect the multimodal LLM foundation:

```bash
uv run fplagent-llm validate-benchmarks --image-root /home/lewis/Downloads
uv run fplagent-llm build-data
bash llm/install_qwen35.sh
llm/.venv/bin/python llm/evaluate_screenshot.py \
  --image /home/lewis/Downloads/fpl-team.jpeg \
  --output data/llm/generated/fpl-team-001-base-extraction.json
uv run fplagent-llm score-screenshot \
  --extraction data/llm/generated/fpl-team-001-base-extraction.json \
  --case-id fpl-team-001
```

Qwen3.5-4B remains multimodal; team uploads are handled as images, with OCR as optional
cross-check evidence. Player IDs and squad legality come only from current-catalog resolution and
deterministic validation, followed by explicit user confirmation. See [llm/README.md](llm/README.md)
for the isolated local training workflow.

For authenticated squad sync, first leave the sibling MCP integration running in another terminal:

```bash
cd ../fpl-mcp-server
FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src uv run python -m fpl_server.main
```

Then run the cohesive local web application—GW1 pitch, fast constrained builds, deterministic
critique, grounded Qwen chat and guarded screenshot import—with:

```bash
bash scripts/run_local_web.sh
```

Open <http://127.0.0.1:5173>. See [the web application guide](web/README.md) for the login/sync
journey, separate process commands, local ports and hosting boundaries.

The global robust search is the definitive challenger funnel. The canonical 7 August run expanded
its seed optima into 527,195 legal local squads, added 256 distant mixed-integer restarts and 19,964
legal evolutionary squads, and reduced a combined 547,415-squad universe with progressively more
expensive simulation. The final 64 squads receive identical 25,000-world base and high-scoring holdouts under
fixed, open-transfer and forced-GW2-bank policies. This is diversified global search, not a claim to
enumerate the roughly 10^27 position-valid rosters that exist before budget and club constraints.

The horizon audit then refuses to assume that five gameweeks are enough. It carries all 64 finalists
into GW1–8, adds 128 horizon-native challengers, and evaluates short, decayed long, GW6–8-only,
fixed-squad and forced-GW2-bank views. The final synthesis gives equal prior weight to the scoring/model
stress family and the horizon/transfer family, with a penalty for a squad that is brittle in either.
The resulting decision remains provisional until the complete funnel is refreshed at the deadline.

Before GW1, `gw1-deadline-run` is the single safe orchestration command. It refreshes or reuses the
public generation, rebuilds the eight-week feature and forecast grids, generates the legal anchor
and 128 residual candidates, performs separate component selection and holdout passes, runs global
robust search, runs the independent horizon audit, synthesises both families in staging and publishes
only after the deadline evidence gate passes. Its fingerprint includes forecast, rules,
implementation and simulation configuration hashes. An unchanged, still-fresh generation is reused;
a failed staged gate leaves the active decision untouched, and a failed final recheck restores the
previous decision, results, report and freshness receipt.
The production path has been exercised end-to-end; an immediate identical invocation completed in
4.15 seconds with `reused: true` and did not start any optimisation stage.

Audit every legal use of the currently published 15 without changing it:

```bash
uv run fplagent audit-current-squad
```

This checksum-binds itself to the current synthesis and forecast generation, enumerates every legal
XI, bench order and robust captain/vice option, selects under 5,000 shared worlds per residual and
component family, and tests finalists on separate 25,000-world holdouts. The current canonical run
recovered the exact published 5-3-2, Bruno captain, Tarkowski vice and bench priority as its
selection champion. Results are written to
`data/model/current_squad_adversarial_v1/results.json`; the command is read-only.

Freeze the current GW1 decision and its strongest alternatives for honest post-GW scoring:

```bash
uv run fplagent freeze-gw1-prospective
```

The production GW1 pipeline now performs this freeze automatically after its final evidence check
and rolls publication back if the evaluation contract cannot be created. The current contract
contains selected `R-ee60e45c6d`, strongest rejected `R-5043bb75d6`, 30 further synthesis
finalists and frozen player forecasts. It lives under `data/decisions/weekly/event-1/` and does not
change the active squad.

`deadline-status` is the fail-closed publication gate. It verifies that the current official and
authenticated manager snapshots are complete and fresh, that the direct/component forecast grids
agree, that forecasts were built from the pointed official snapshot, and that the decision's
content-addressed source artifacts reference the current forecast generation. A newer data fetch
therefore makes an older forecast/decision visibly non-publishable until the downstream pipeline
has been rerun.

After GW1, `deadline-run` is the separate authenticated weekly orchestration command. It collects or
reuses the official snapshot, validates and preprocesses it, rebuilds the feature horizon, applies the frozen
direct/component models, derives the exact authenticated manager state, generates all transfer/XI/
bench/captain routes, simulates shared worlds and publishes only after the evidence gate passes.
Use `--reuse-latest-official` to replay an existing capture. Exact forecast-input manifests prevent
unchanged model generations from being rewritten with new timestamps, and an identical pipeline
fingerprint reuses the active decision byte-for-byte. Failed staged evidence leaves the existing
active receipt untouched; an unexpected final recheck restores the previous decision and status.
Before FPL exposes post-GW1 finance fields the command returns `not_ready` without inventing them.

Every published weekly decision is also copied into a content-addressed, immutable event archive.
Once FPL marks that Gameweek both finished and data-checked, the normal `deadline-run` automatically
archives any missing event outcomes and rebuilds the live xG/xA/minutes/points feature stream. The
explicit collector is still available for repair or inspection. Close the prospective scoring loop:

```bash
uv run fpl-data collect-event-outcome --event 1  # optional if deadline-run already synced it
uv run fplagent score-weekly-event --event 1
```

The collector archives the official event-live bytes only after exact finality, player-set and
production-stat validation. The scorer selects the last frozen pre-deadline decision, verifies it was created before
the official deadline, and scores the selected action, roll comparator and every considered route
with exact autosubs, captain fallback and incremental hit costs. It records realized decision rank,
gain versus roll, opportunity cost, forecast error and player-level points/minutes errors. Receipts
are immutable under `data/model/prospective_weekly_scoring_v1/`; a single noisy Gameweek is never a
model-promotion gate by itself.

The weekly engine also evaluates Bench Boost and Triple Captain in shadow mode. Each available chip
is paired with the identical no-chip squad/transfer route and scored with exact chip rules in the
same residual and component worlds. The receipt compares current simulated uplift with the best
visible retained opportunity before the chip-half expiry. An incomplete half-season forecast,
unresolved fixture schedule, scenario reversal or confidence interval crossing zero forces
`no_chip`. `uv run fplagent schedule-status` writes an immutable official-schedule receipt that
separates confirmed, provisional and unassigned fixtures and reports blanks/doubles without
inventing a rearrangement. The component simulator scores every match in a double independently
before aggregating the Gameweek. These routes cannot yet drive the live recommendation; Wildcard/
Free Hit search, probabilistic rearrangement scenarios and historical chip-option calibration are
still required.

`train` and `forecast` deliberately fail when CUDA is unavailable; there is no silent CPU
training path. The promoted model must also pass rolling MAE, ranking, top-shortlist and GW1
shortlist gates before an artifact is written. The squad optimiser applies the live £100m,
2/5/5/3, formation, three-per-club and five-free-transfer carry rules across GW1–GW8.

The component tournament is a deliberately gated challenger. CUDA models predict fixture goals
and player scoring, assisting and bonus propensities; the simulator then generates goal times,
on-pitch intervals, clean sheets, concessions, the remaining FPL components, exact autosubs and
captaincy. A raw-component/xP weight is selected only on 2024/25, frozen for 2025/26, and used to
generate independent legal challengers. The literal 100% component result remains a visible stress
test. An independently selected challenger can replace the residual recommendation only when it
improves both raw and anchored means and its paired evidence-weighted 95% interval excludes zero.

The build also creates `data/fpl_history.duckdb`, a lightweight query catalog whose views
read the normalized Parquet files directly. For example:

```bash
uv run python -c "import duckdb; print(duckdb.connect('data/fpl_history.duckdb').sql('select * from dataset_catalog').fetchall())"
```

Individual stages and sources can be rerun:

```bash
uv run fpl-data fetch --source solio
uv run fpl-data preprocess --source solio
uv run fpl-data fetch --source vaastav
uv run fpl-data preprocess --source vaastav
uv run fpl-data fetch --source fpl_current --force
uv run fpl-data preprocess --source fpl_current
uv run fpl-data catalog
```

See [data/README.md](data/README.md) for schemas, provenance and source caveats.
