# FPLAgent data and decision foundation

> **Active objective — in-season:** maximise season points through the deterministic data,
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

## Run the app and refresh the next Gameweek

**Routine workflow, verified 11 September 2026.** Use the existing installed environments. These
commands do not train models, start Qwen, or submit transfers/chips to the official FPL account.
If the services are already running, skip startup—do not launch duplicate copies on the same ports.

### 1. Start the three services in separate terminals

**Terminal 1 — local FPL MCP/login service:**

```bash
cd /home/lewis/Workspace/fpl-mcp-server
FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src .venv/bin/python -m fpl_server.main
```

**Terminal 2 — FPLAgent API and background decision worker:**

```bash
cd /home/lewis/Workspace/fpl-agent
.venv/bin/fplagent-web --host 127.0.0.1 --port 8000
```

**Terminal 3 — frontend:**

```bash
cd /home/lewis/Workspace/fpl-agent/web
npm run dev -- --host 127.0.0.1
```

Open **<http://localhost:5173>**. The API is on 8000, MCP on 8021 and its embedded login service on
8020. Leave the service terminals open. The optional `scripts/run_local_web.sh` launcher also starts
Qwen; it is not needed for the decision-only workflow above.

The MCP uses the optional saved credentials in
`/home/lewis/Workspace/fpl-mcp-server/.local/fpl-credentials.json`. The file is local, owner-only,
Git-ignored **plaintext**; never paste it into a terminal command, chat or a report. See
[saved-login setup and security](docs/local-saved-fpl-login.md). Missing credentials or account
verification may still require the embedded login flow.

### Automation first; player comparisons are optional

The normal workflow is **connect once → refresh decisions → act on one published plan**:
transfers or roll, any hit, chip or no chip, XI, ordered bench, captain and vice-captain.
You do not need to screen players, inspect Scout, pick a model, run research commands or open
the comparison view. The normal weekly pipeline scores finalized decisions automatically and
rebuilds scouting explanations from the **same immutable official snapshot and final forecasts**.
This adds no external requests. An optional explanation failure is recorded, preserves the saved
board and does not stop the decision engine. Existing decision-evidence safety gates still apply.

New evidence/model changes must improve time-forward legal decisions before gaining production
authority. More charts, better probability metrics or a competitor's reputation alone do not
prove more FPL points. Scout informs independent benchmarks and feature research; the automated
workflow must not depend on the manager maintaining a subscription or copying its projections.

The automatic research checks also examine joint premium-sale/reinvestment routes and compare
future moves against holding at the same future state. Finalized results aggregate only policy
choices frozen before their deadlines. These checks do not silently override the published plan:
new search/forecast/timing authority still requires validation. See the
[21 October points-first follow-up](reports/scout-product-audit-and-gw7-review-2026-10-21.md#follow-up-premium-capital-objective-future-actions-and-distributions)
for the measured results and remaining sequential-policy work. A minutes-model overhaul and LLM
improvements are currently parked.

Developer-only chronological policy validation (not a live decision refresh):

```bash
FPLAGENT_ACCELERATOR=cpu .venv/bin/python scripts/replay_sequential_policies.py \
  --output data/research/points-priorities/NEW-SEQUENTIAL-RUN.json
```

This carries independent squads, selling prices, banks, free transfers and hits through GW1–10
of 2024/25 and 2025/26. It prints progress and saves a checksummed research receipt; existing
receipts cannot be overwritten. The earlier-season-fitted residual-world experiment is **not**
the complete live three-world/chip policy. Its results cannot publish recommendations or tune
risk weights. See the [sequential test and release call](reports/scout-product-audit-and-gw7-review-2026-10-21.md#chronological-follow-up-four-policy-paths-across-two-seasons).

The expanded research replay adds all three simulation families, exact legal XI/bench/C/VC
configuration, earlier-season free-transfer opportunity values, and consistent risk settings
at both configuration and route selection:

```bash
.venv/bin/python scripts/replay_multiworld_policies.py \
  --output data/research/points-priorities/NEW-MULTIWORLD-RUN.json
```

Run this separately from GPU-heavy test suites/audits to avoid competing for VRAM.
It uses the GPU when available, reports progress, and never refreshes or publishes the live
workspace. Seven independent policies carry their actual squads, prices, cash, FTs and hits
through two opening-ten-GW windows. Outcomes also score frozen distributions by position,
captain and bench. Historical lineup/market snapshots and a pre-2025 defensive-contribution
prior are not available: this is an architecture ablation, **not a complete production clone
or proof of a whole-season edge**. Do not infer authority from a passing experiment.
The receipt's `archive_preflight` explicitly lists missing same-event metadata and lagged-price
coverage; 2025/26 GW8 currently relies on the earlier GW7 fixture archive. That gap must not be
presented as an exact, verified historical execution-price backtest.

Normal weekly refreshes now also record `diagnostics.exact_chip_opportunities`: BB scoring
with actual autosub displacement and TC scoring with captain/vice fallback, compared against
the existing future-opportunity proxies. This adds no external requests or manual manager
workflow. The comparison cannot spend a chip: new timing inputs require matching retained-value
calibration and chronological policy validation first.

The [completed 21 October results and release decisions](reports/scout-product-audit-and-gw7-review-2026-10-21.md#completed-three-world-results-and-release-decisions)
retain the current selection policy: none of these experimental variants improved both historical
folds. Demonstrated chip expiry/capacity bugs are fixed in normal decisions; unvalidated research
cannot promote itself. This work did not refresh or replace the saved live squad.

### Optional player scouting and comparisons

Open **Player scouting** in the navigation to compare two players using our own official data:
recent versus earlier xG/xA, minutes/starts, actual defensive-contribution awards, set-piece order,
six upcoming gameweeks and separately dated model forecasts. Filter the shortlist by position and
minimum minutes; order it by chance creation, minutes or defensive-contribution hit rate.
The normal decision refresh updates this board for you. **Update scouting** is an optional
inspection-only refresh of the public catalogue/fixtures, not your team or decision engine.
Standalone use requires archived completed results; use the normal decision refresh if missing.
The following commands are for inspection/repair, not part of the routine manager workflow:

```bash
.venv/bin/fplagent review-gameweeks --entry-id 2754976  # public final outcomes
.venv/bin/fplagent scouting-refresh                   # evidence board; JSON output
```

The optional probability display preserves model xP but gives blanks and hauls their own probability
mass. It earned **diagnostic-only** activation on historical probability scoring, not authority
to change transfers or captaincy. Reproduce the experiment and activate only if its gates pass:

```bash
.venv/bin/fplagent replay-score-shapes --activate-diagnostics
```

See the [Scout gap-closure implementation and validation](reports/scout-product-audit-and-gw7-review-2026-10-21.md#implementation-follow-up-closing-the-first-gaps).
Stale forecasts remain explicitly stale even when today's catalogue has been refreshed; use
**Refresh decisions** for current recommendations. These comparisons are not a paid Scout data
feed, and a price difference alone is not proof that a transfer is affordable or legal.

### 2. Refresh from the browser (recommended)

Let the app connect and sync your squad, then click **Refresh decisions** (or **Sync FPL & retry**
if prompted). Successful app-open sync also requests a refresh; if one is running, join it rather
than starting a separate engine command.

The server refreshes public evidence, forecasts and your exact archived manager state, then compares
transfers, rolling, the starting XI/bench, captaincy and chip policies. It uses FPL's official next
event automatically: no Gameweek number needs changing by hand. The weekly forecast horizon is
currently five Gameweeks starting with that event, not five promises to execute future transfers.

**Simulation-based lineups (16 October 2026):** normal weekly refreshes now search every legal XI,
outfield bench order and captain/vice pair for each proposed roster and horizon event. This includes
the no-transfer comparator, exact Bench Boost/Triple Captain scoring and Free Hit's restored squad.
The search uses the existing three model worlds and 0.25 worst-world risk weight; it does not
change player forecasts, force named players to start, or expand the transfer shortlist. Within
each fixed roster, the configuration is selected jointly over the horizon using its own attainable
frontier. This is not a proof of a global adaptive transfer-policy optimum.

Selection uses at least 50,000 samples per model family. The selected ordinary route and any
recommended chip route are frozen before a separate 100,000-sample-per-family validation. A changed
configuration must have a positive paired lower confidence bound over its original configuration
and no model-world mean loss greater than 0.05 points over the discounted horizon. These intervals
measure Monte Carlo error, **not** football forecast uncertainty. Raw and anchored component samples
are correlated and their covariance is preserved in the paired calculation. On failure, the entire
original selection/configuration is retained and explicitly labelled in the browser and CLI; we
never select a replacement on the holdout or weaken gates to obtain a particular player.

The weekly JSON receipt records this under `diagnostics.configuration_optimisation`, including
original/refined lineups, counts, frozen hashes, seeds and validation results. The browser's
recommended pitch and terminal report consume the same published lineup. The routine command
remains `.venv/bin/fplagent decisions --refresh`. This is separate from the older, rejected
**wider-roster** deep-search research programme.

Wait for successful validation/publication, then open **View recommended squad / Recommended squad**.
“Your FPL squad” is the team actually synced from FPL; “Best lineup” rearranges those existing 15;
the recommended squad can include proposed transfers. Review the transfers, XI, bench, captain,
vice and chip instruction together before making changes manually in FPL.

**Chip configuration contract:** new receipts include an `execution_plan` when a chip is recommended.
The browser/CLI use that exact transfer parent, XI, bench and captain pair, including chip-adjusted
scalar projections. The ordinary no-chip benchmark remains separately auditable. Older receipts
without this contract still require care: do not combine a chip with an unrelated transfer route.
The [11 September diagnosis](reports/gw4-refresh-2026-09-11.md) describes the earlier mismatch.

### 3. Readable terminal decisions (no frontend required)

With the API running, show the same saved weekly plan as the browser:

```bash
cd /home/lewis/Workspace/fpl-agent
.venv/bin/fplagent decisions
```

To connect via MCP/saved login, sync your actual squad, request a full refresh, wait for completion,
and print the resulting plan in one command:

```bash
.venv/bin/fplagent decisions --refresh
```

This needs the API and MCP services, **not** Vite or Qwen. If another refresh is already running, it
joins that job without replacing its input snapshot. To only join a running job without requesting
anything new:

```bash
.venv/bin/fplagent decisions --wait
```

During a longer calculation, a timed-out progress request is retried within `--timeout`; the
server-owned job is not cancelled. Only read-only status polls are retried, never a sync or refresh
POST. A timeout during those operations requires checking the running job before trying again.

The plain-text report includes transfers and their point cost, captain/vice, chip instruction,
the complete starting XI, three outfield substitutes in priority order and the reserve goalkeeper
separately. It also shows fixtures, individual undoubled model xP, expected minutes, appearance
probability, the saved team projection, horizon gain versus rolling, chip opportunities and evidence
timestamps. Future chip windows are estimates, not fixed bookings. The model's player xP and saved
team scoring basis can differ; the CLI does not invent a new team total by summing displayed rows.

The CLI uses the same validated `/api/v1/workspace` response as the web app; it neither runs a
second optimizer nor submits any transfer, lineup or chip to FPL. An incomplete, stale, wrong-event
or inconsistent decision is shown as **NEEDS REVIEW**, with execution instructions withheld. In
particular, an active chip must be traceable to the same transfer route—mismatched or missing
chip-parent metadata is not silently combined. APIs started before this command was added need a
restart **after any current refresh finishes** to expose that metadata.

Optional output modes:

```bash
# Narrow terminal or phone SSH session.
.venv/bin/fplagent decisions --width 70

# Machine-readable workspace + refresh/schedule status + readiness issues.
.venv/bin/fplagent decisions --json

# Allow up to one hour of waiting (default: 30 minutes).
.venv/bin/fplagent decisions --refresh --timeout 3600
```

Progress goes to stderr, so stdout can be redirected to a text report or JSON file without progress
noise. No ANSI styling is required. Exit codes are `0` for a ready report, `2` for a retrieved report
that needs review, `1` for connection/sync/schema/wait errors, and `130` if you interrupt the CLI.
Ctrl+C or a wait timeout **does not cancel** the API's background job. Read-only `decisions` calls do
not start refreshes; the independently running API scheduler may still do so.

### 4. Low-level refresh API calls from a fourth terminal

These are the API calls used for the recent refresh. They use the same single-flight worker and
progress state as the browser. Start in the project directory:

```bash
cd /home/lewis/Workspace/fpl-agent
```

First check authentication; this also starts saved-file login when needed:

```bash
curl --fail --silent --show-error --max-time 20 \
  http://127.0.0.1:8000/api/v1/integrations/fpl \
  | .venv/bin/python -m json.tool
```

Wait for `"status": "connected"` before continuing. If it is `not_authenticated`, allow the browser
login to finish and repeat the check; resolve a failed login in the app instead of repeatedly
submitting credentials. Then archive the current squad, bank, selling prices, FT and chip state:

```bash
curl --fail --silent --show-error --max-time 60 -X POST \
  http://127.0.0.1:8000/api/v1/integrations/fpl/sync \
  | .venv/bin/python -m json.tool
```

Require `"manager_state_status": "ready"`. **A failed sync is not permission to use stale manager
data.** Once ready, request the full decision refresh:

```bash
curl --fail --silent --show-error --max-time 30 -X POST \
  -H 'Content-Type: application/json' \
  --data '{"reason":"manual"}' \
  http://127.0.0.1:8000/api/v1/workspace/refresh \
  | .venv/bin/python -m json.tool
```

HTTP 202 / `"status": "running"` means accepted, not finished. Watch progress with **GET only**:

```bash
watch -n 3 'curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/api/v1/workspace/refresh | .venv/bin/python -m json.tool'
```

Success is `published` or `reused`, with a successful completion timestamp and the intended event.
`blocked`, `not_ready` or `failed` require reading `message`/`failure_code`; do not treat an older
recommendation as newly validated. Press Ctrl+C to stop **watching**; that does not cancel the worker.
The five stage percentages are stage counts, not a time-based ETA. Recent ordinary runs took about
two minutes; deeper research audits take longer and do not automatically replace production.

Inspect the next scheduled check, or read the full workspace without starting another run:

```bash
curl --fail --silent --show-error --max-time 20 \
  http://127.0.0.1:8000/api/v1/workspace/refresh/schedule \
  | .venv/bin/python -m json.tool

curl --fail --silent --show-error --max-time 30 \
  http://127.0.0.1:8000/api/v1/workspace \
  | .venv/bin/python -m json.tool
```

Keep the API running for jobs to finish and scheduled checks to occur. Closing the browser is fine;
stopping the API interrupts its worker. Validated decisions persist across restarts in
`data/decisions/2026-27-weekly-current.json`, with immutable archives in
`data/decisions/weekly/event-N/`. Current cadence is six hours, two hours in the last day, and thirty
minutes in the final three hours; material evidence changes can trigger an earlier run. A temporary
view block during a new forecast generation is not proof that its replacement decision is ready.

### Engine-only alternative (advanced)

The underlying weekly engine command is:

```bash
cd /home/lewis/Workspace/fpl-agent
.venv/bin/fplagent deadline-run --manager-entry-id 2754976 --horizon 5
```

`2754976` is Lewis's entry ID; other users must substitute theirs. This CLI uses the latest
**already archived** authenticated manager snapshot—it does not log in or sync private FPL data.
Sync first, then stop the API before using this alternative. Do not run it alongside the API's
worker/scheduler or another refresh: they share mutable forecast/publication artifacts, and this
CLI bypasses the web worker's single-flight coordination and run-status tracking. Restart the API
afterward to inspect the persisted result in the browser. For normal use, prefer the API sequence.

Omit `--reuse-latest-official` when you want newly fetched evidence. That flag is for replaying a
captured generation, not fetching the latest news. Do not use `gw1-deadline-run`, `build-gw1`,
`train`, or the development commands below for the routine in-season refresh.

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

## Data/model development commands (not the routine weekly refresh)

The following are setup, historical research and preseason/model-development commands. Some build
large datasets or train models. For normal in-season use, follow
[Run the app and refresh the next Gameweek](#run-the-app-and-refresh-the-next-gameweek) above instead.

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
archives any missing event outcomes, rebuilds the live xG/xA/minutes/points feature stream, and
scores frozen decisions for finalized events. Scoring failures are recorded for review without
blocking the next decision or automatically promoting a model. The explicit commands remain
available for repair or inspection:

```bash
uv run fpl-data collect-event-outcome --event 1  # optional if deadline-run already synced it
uv run fplagent score-weekly-event --event 1
uv run fplagent review-gameweeks --entry-id YOUR_ENTRY_ID
```

`review-gameweeks` fetches public, finalized FPL results and reconciles your actual locked team
against the recommendation saved before each deadline. Its JSON output includes all 15 players,
forecast/actual points and minutes, captain contributions, hit costs, rank and calibration
diagnostics. It does **not** start an optimisation, change forecasts or write to your FPL account.
The saved review lives under `data/model/gameweek_review_v1/<entry-id>/current.json`.
In the web app, open **Season review** in the navigation and use **Refresh results**. This is
separate from **Refresh decisions**; failures retain the previous verified review.

The collector archives the official event-live bytes only after exact finality, player-set and
production-stat validation. The scorer selects the last frozen pre-deadline decision, verifies it was created before
the official deadline, and scores the selected action, roll comparator and every considered route
with exact autosubs, captain fallback and incremental hit costs. It records realized decision rank,
gain versus roll, opportunity cost, forecast error and player-level points/minutes errors. Receipts
are immutable under `data/model/prospective_weekly_scoring_v4/`; previous versions are retained.
V4 binds chip results to their exact executable XI/captain configuration and records short
appearances separately from merely playing. A single noisy Gameweek is never a model-promotion
gate by itself. See the [21 October season and Scout audit](reports/scout-product-audit-and-gw7-review-2026-10-21.md)
for the current evidence, limitations and points-first priorities.

The weekly engine pairs chip candidates with their actual squad/transfer routes and scores exact
chip rules in shared residual and component worlds. Under the current
[joint chip strategy v2](docs/chip-strategy-v2.md), Bench Boost and Triple Captain are eligible for
live recommendations after historical, schedule, opportunity-cost and uncertainty gates pass.
Wildcard/Free Hit mechanics are implemented, but their timing remains research-only. Older
`chip_shadow` diagnostics are retained and must not be confused with the joint v2 operational
recommendation. `uv run fplagent schedule-status` records confirmed, provisional and unassigned
fixtures without inventing rearrangements; the component simulator scores each double-Gameweek
fixture separately before aggregating. Read the current release/receipt rather than assuming all
chips are either permanently disabled or automatically approved.

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

### Optional private Scout benchmark

The [21 October forecast diagnosis](reports/forecast-diagnosis-and-corrections-2026-10-21.md)
documents the matched comparison and live availability repairs. Upcoming decisions now use
**next-round**, event-relative official availability; a previous-round flag cannot silently
override it. Publication independently rejects nonzero direct/component projections for an
officially unavailable player in that round. Future injury recovery remains an explicitly
uncertain assumption, not a known return date.

Normal finalized-outcome scoring also updates
`data/model/forecast_diagnosis_v1/current.json`: verified frozen forecast errors by position,
selected squad and captain, separating nonappearance from conditional-return errors. No extra
weekly manual step is required. This diagnosis and private Scout comparisons do not automatically
retrain models or override recommendations.

Normal weekly deadline runs now capture a bounded, private comparison with Scout when an
authorized session is saved in `.local/ffscout-cookie.txt` (permissions `600`). No new manual
gameweek workflow is required. Missing/expired membership or changed source schemas do not
block the decision engine. This is evaluation, not a dependency of our forecasts or advice.

Receipts stay outside Git in `.local/scout-benchmarks/`. Stale local inputs, mismatched player
identities/prices or missing projections cannot masquerade as a fair head-to-head result.
Eligible same-squad controls are scored against finalized official outcomes automatically;
they are not Scout's proprietary optimizer or a proof of season-long superiority.

One-off private capture and the separate historical gate/search study:

```bash
.venv/bin/python scripts/capture_scout_benchmark.py --manager-contract PATH_TO_MANAGER_STATE_JSON --event 8 --horizon 4
.venv/bin/python scripts/replay_gate_search.py --output data/research/points-priorities/NEW_UNIQUE_RUN.json
.venv/bin/python scripts/verify_policy_ledger.py data/research/points-priorities/gate-search-20261021-v1.json
.venv/bin/python scripts/audit_search_coverage.py data/research/points-priorities/gate-search-20261021-v1.json
```

The study never publishes advice. Do not edit engine code or run competing GPU-heavy jobs
during its hash-frozen execution. See the [Scout audit](reports/scout-product-audit-and-gw7-review-2026-10-21.md)
for definitions, limitations and completed results.
