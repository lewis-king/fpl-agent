# FPLAgent local web application

This is the cohesive local product over the GW1 optimiser, multimodal team importer and grounded
FPL-tuned Qwen assistant. The preseason experience is implemented now; its shell and data contracts
are designed to become the transfer, XI, captaincy, chip, live and review workspace after GW1.

## Routine weekly use (existing installation)

Follow the root README's [startup and next-Gameweek refresh commands](../README.md#run-the-app-and-refresh-the-next-gameweek).
It covers MCP + API + frontend startup without Qwen, optional saved-file login, authenticated squad
sync, the background refresh request, progress monitoring and persisted decisions. Use that path
for the current in-season workflow; you do not need the model installation/training steps below.

Prefer a terminal report? From the repository root, `.venv/bin/fplagent decisions` prints the same
saved weekly recommendation. Use `decisions --refresh` to sync, request a background refresh, wait
and print it, or `decisions --wait` to join an existing job. Only the API (and MCP for a fresh sync)
is required; the frontend and Qwen are optional for this workflow.

Authentication alone is not a squad sync, and a successful sync is not a completed decision run.
Wait for successful publication and check the event/timestamp. See the
[refresh lifecycle](../docs/decision-refresh-lifecycle.md) and
[saved-login security guide](../docs/local-saved-fpl-login.md). The root guide also documents the
unresolved chip-parent display mismatch; never combine instructions from different transfer routes.

## First-time setup

Install the main and isolated model environments:

```bash
uv sync
bash llm/install_qwen35.sh
cd web
npm install
cd ..
```

Install the sibling MCP server and its login browser once:

```bash
cd ../fpl-mcp-server
uv sync
uv run playwright install chromium
cd ../fpl-agent
```

## Run with authenticated FPL sync

Use two terminals. Start the local MCP integration first:

```bash
cd ../fpl-mcp-server
FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src uv run python -m fpl_server.main
```

It serves the local login page on `127.0.0.1:8020` and MCP on
`http://127.0.0.1:8021/mcp`. Leave it running.

Then start the FPLAgent API, persistent Qwen sidecar and React client:

```bash
cd ../fpl-agent
bash scripts/run_local_web.sh
```

Open <http://127.0.0.1:5173>. FPLAgent detects the running MCP process automatically. If it is not
authenticated, the account connection view opens immediately with the local MCP login form embedded
inside the application—there is no second tab, separate page or preliminary Connect step. Enter your
FPL email and password there. The form is still served directly from `127.0.0.1:8020`: React and the
FPLAgent API cannot read or store those fields. FPLAgent detects the resulting session, reads the
current squad and makes it the active pitch. The authenticated `/me` response supplies the
authoritative entry ID, so entering an ID manually is optional. If MCP is already authenticated when
the app opens, the squad is refreshed silently first. The last validated workspace renders
immediately; a persisted single-flight job then refetches official evidence, runs the GW1 or weekly
deadline pipeline, and swaps in a result only after its evidence gate passes. The green status means
either a new receipt was published or the existing content-addressed generation was revalidated.
Blocked and failed runs retain the previous receipt and explain what is missing.

The FPLAgent workspace is usable while Qwen is still loading. Chat reports an offline state until
the model is ready. Press `Ctrl+C` in each launching terminal to stop its processes.

### Automatic and manual refresh

Opening the application now performs account sync followed by the complete read-only decision
refresh. It never writes changes to FPL. Repeated browser requests join the same in-process run, and
the daemon worker does not hold the local server open during shutdown. The engine continues to own
content hashes, staged artifacts, rollback and atomic publication.

While the API remains open it also owns T−72h, T−24h, T−6h, T−60m and T−10m deadline runs. A
lightweight public-feed probe catches material player, price, rules or fixture changes between those
windows. Its cadence tightens toward the deadline and excludes ordinary transfer-counter movement,
so it does not repeatedly launch the expensive tournament. Inspect its persisted state at
`GET http://127.0.0.1:8000/api/v1/workspace/refresh/schedule`.

Price/transfer telemetry is deliberately cheaper and separate. While the API runs it stores one
append-only official market observation every 15 minutes and exposes its status at
`GET http://127.0.0.1:8000/api/v1/market/telemetry`. These rows are research evidence for a later
`move now` versus `wait` policy; they do not currently alter the squad or transfer recommendation.

For maintenance or debugging, the forecast-only path remains available:

```bash
bash scripts/refresh_current_forecasts.sh
```

This rebuilds the current eight-gameweek feature grid and forecast artifacts without running the
complete decision tournament. It does not retrain the models. A recently refreshed input snapshot
can be `fresh` while the recommendation still correctly says that a final pre-deadline run is
required.

### Publish the canonical pre-GW1 squad

Run the complete preseason decision funnel with:

```bash
uv run fplagent gw1-deadline-run --reuse-latest-official
```

Omit `--reuse-latest-official` when a new public snapshot should be fetched. The command performs
the stable-squad anchor, residual tournament, component selection and independent holdout, global
robust search, eight-week horizon audit, cross-family synthesis, squad-specific preseason role
scenarios, stress threshold and availability watch. Final outputs are built in a fingerprinted
staging directory and become active only after every evidence check passes. If the
official snapshot, forecast, rules, implementation and configuration are unchanged, the command
reuses the active receipt instead; the verified local reuse path completes in roughly four seconds.

### Publish a post-GW1 weekly decision

Once the authenticated FPL endpoint exposes the complete transfer state, run the entire read-only
weekly decision path with:

```bash
uv run fplagent deadline-run --manager-entry-id YOUR_FPL_ENTRY_ID
```

For a deterministic replay of the already captured official snapshot, add
`--reuse-latest-official`. The command never writes to FPL. It publishes
`data/decisions/2026-27-weekly-current.json` only after manager, forecast, component and decision
lineage all pass. During preseason it will deliberately stop at `not_ready`, because FPL does not
yet provide the exact free-transfer and purchase-price state needed for a truthful weekly action.

## Ports and trust boundaries

| Port | Process | Browser contract? |
| --- | --- | --- |
| `5173` | Vite/React client | yes |
| `8000` | FPLAgent application API and OpenAPI | yes |
| `8011` | private Qwen sidecar | no |
| `8020` | local FPL login page | embedded only for authentication |
| `8021` | local MCP streamable HTTP endpoint | no; backend-only |

FPL credentials and tokens never enter React or the FPLAgent API. The browser submits the embedded,
cross-origin login form directly to the local service on port `8020`; the application talks to its
own API, which adapts four structured MCP read/authentication tools. No FPL mutation tool is invoked.

## Run FPLAgent processes separately

```bash
# Terminal 1: application API
uv run fplagent-web --reload

# Terminal 2: persistent local GPU model
llm/.venv/bin/python llm/serve_chat_qwen35.py

# Terminal 3: React client
cd web
npm run dev
```

To test the v3 FPL LoRA adapter in chat as well as screenshot extraction:

```bash
FPLAGENT_WEB_ADAPTER=llm/outputs/qwen35-4b-fpl-lora-v3/adapter \
  bash scripts/run_local_web.sh
```

V3 remains the default adapter for screenshot extraction. Base Qwen plus grounded tools is still
the promoted text-chat configuration until the next text evaluation gate.

## What can be tested now

- Activate the precomputed robust GW1 recommendation instantly.
- Generate a legal balanced, safer or upside candidate over three, five or eight gameweeks.
- Lock current players into a rebuild and require up to three players from a club.
- Upload a JPEG, PNG or WebP team screenshot, inspect extraction/legality and explicitly confirm it.
- See a deterministic critique, benchmark delta, captain recommendation, risks and evidence.
- Ask Qwen to explain the active squad or naturally request a constrained rebuild.
- Save an FPL entry ID manually.
- Authenticate through the locally running MCP process and sync the current 15-player squad.
- Use the responsive pitch, list, upload, builder, identity and chat experiences on desktop or phone.

Confirmed screenshots, generated candidates and MCP snapshots all update the same active workspace
at `data/web/state/active-manager-decision.json`. The local identity is stored at
`data/web/state/local-manager-profile.json`.

## Current boundaries

- Preseason is the only phase that can be exercised end-to-end before the real GW1 deadline. The
  post-GW1 weekly panel and deterministic engine are implemented—roll, transfers, hits, XI, bench,
  captain and chip shadows—but a genuine full run correctly waits for FPL to expose complete
  purchase-price/free-transfer state after GW1.
- Prospective attribution, the challenger registry and late-season mini-league strategy currently
  publish engine receipts/reports rather than dedicated web screens. Mini-league context is not yet
  collected through the UI; its shadow cannot override the points-first weekly action.
- The MCP authentication session lives only in its process memory, so restarting MCP requires a new
  login. FPLAgent presents it automatically, but does not retain or replay the password. The saved
  entry ID remains but does not authenticate.
- Custom squad scenarios are synchronous. Expected local times are approximately one second for a
  three-GW horizon, three seconds for five and eight seconds for eight.
- Chat sessions live in the Qwen sidecar memory and GPU generation is serialized.
- Screenshot analysis launches a separate GPU process; a shared GPU work queue is still required
  for production concurrency.
- There are no real FPL writes. Transfers, lineups and chips remain advisory.
- The localhost MCP mode is not safe to expose publicly. Hosting requires a dedicated per-user
  session and authorization architecture.

## Quality commands

```bash
cd web
npm run lint
npm run build

cd ..
uv run ruff check src tests llm
uv run pytest -q
```

See [the application architecture](../docs/web-application-architecture.md) and
[the LLM architecture](../docs/fpl-llm-architecture.md) for the longer-lived system design.
