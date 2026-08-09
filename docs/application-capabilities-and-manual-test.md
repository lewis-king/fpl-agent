# FPLAgent capabilities and manual test guide

**Updated:** 8 August 2026  
**Product mode today:** local, read-only, preseason-first FPL decision workspace

## What the application does

### Opens on the correct FPL phase

The application reads the official event calendar rather than hard-coding GW1. Before the opening
deadline it is a squad-building and squad-critique product. After GW1 its existing weekly panel and
engine become a roll/transfer/hit, XI, bench, captain and chip decision workspace. During a live GW
it keeps the submitted event as context while preparing the next actionable deadline; after final
data checking it can score the frozen decision.

The last validated workspace appears immediately. A persisted single-flight refresh then checks the
authenticated squad and public evidence, rebuilds only when inputs changed, and atomically replaces
the visible decision only after lineage and evidence gates pass. A failed refresh preserves the last
good result.

### Connects the manager's real FPL squad

The sibling MCP server owns Premier League authentication. Its login form is embedded inside the
FPLAgent modal, but credentials go directly to `127.0.0.1:8020`; neither React nor the FPLAgent API
receives or stores them. Once authenticated, FPLAgent reads the entry ID and current 15-player squad,
archives the snapshot, derives exact manager state when FPL exposes it, and makes the squad active.

The integration is read-only. The application cannot submit transfers, change a lineup or activate
a chip on FPL.

### Generates and edits legal preseason squads

The published robust GW1 squad is instant. The candidate builder can instead solve a legal squad
using:

- balanced, safer or upside risk profiles;
- three-, five- or eight-GW horizons;
- players that must remain locked;
- players that must be excluded; and
- up to three club-minimum rules.

Every build enforces budget, 2/5/5/3 positions, three players per club and a legal XI. Generated,
uploaded and MCP-synced squads all become the same persisted active workspace.

### Imports a Pick Team screenshot

JPEG, PNG and WebP screenshots can be dropped into the upload flow. Qwen's vision path extracts
names and layout, while deterministic current-catalog resolution maps names to player IDs and checks
squad legality. The user sees resolved players and errors before explicitly confirming the draft.
The image model is never allowed to invent a legal squad silently.

### Shows the whole 15-player decision

The responsive pitch and list views show starters, bench order, captain and vice-captain. The
analysis rail provides:

- recommended legal XI changes involving bench players;
- captain and vice comparison over the recommended XI;
- robust xP, expected minutes and play probability for the selected player;
- strongest model signals and the priority review queue;
- availability, favourable-fixture, bench-xP and bench-spend summaries;
- position-unit summaries and all 15 ranked model scores;
- deterministic strengths, concerns and delta to the published benchmark;
- opening-horizon xP, main uncertainty, freshness and source hashes; and
- current versus recommended pitch preview.

### Answers grounded FPL questions

The persistent local Qwen sidecar supplies conversational explanations. Guarded tools provide the
active squad, player comparison, captaincy and constrained rebuild facts so chat does not own the
numeric recommendation. Base Qwen remains the promoted text configuration; the parked FPL LoRA is
documented and optional, while the V3 vision adapter remains the screenshot default.

Chat can explain a player choice, compare players, discuss captaincy, critique squad structure and
request a constrained rebuild in natural language. If the model or grounding service is still
loading, the rest of the application remains usable.

### Runs the deterministic points engine

The engine builds point-in-time player/event features and direct xP from official and archived
evidence, including minutes, availability, xG/xA, BPS/bonus, team/opponent strength, fixtures and
live event outcomes. Pre-closing betting goal rates, lineup evidence, return-distribution and
mean-reversion models are challengers unless their declared tests pass.

GW1 selection uses legal optimisation followed by residual and match-component simulations,
independent selection/holdout seeds, global mixed-integer/evolutionary search, eight-GW horizon
stress and cross-family robust-regret synthesis. It models formation-valid autosubs, captain
fallback and match-level blanks/doubles.

The weekly engine carries exact squad, bank, purchase/selling prices, free transfers and hits. It
generates roll, free-transfer and paid-transfer routes, optimises every route's XI/bench/captain,
and compares them in shared residual and component worlds. A move must clear the roll comparator
and downside gates; otherwise the operational recommendation remains roll.

### Models prices, schedules and all chips conservatively

Official transfer telemetry is archived every 15 minutes. Incoming-rise and outgoing-sale-loss
affordability stresses are exact, but advice remains `wait` until enough UK-midnight outcomes and a
move-now-versus-wait points replay pass.

Fixture receipts distinguish confirmed, provisional and unassigned matches. Match-component
simulation scores blanks and each fixture of a double separately. A historical rearrangement model
adds correlated probabilities as a shadow only; it cannot convert an unassigned match into a
confirmed double.

Bench Boost, Triple Captain, Wildcard and Free Hit are all legal exact counterfactuals. Wildcard
persists its new squad; Free Hit restores the original squad and bank state after the event. Current
retained-timing policies failed their historical downside gates, so every chip route remains
`no_chip` operationally even when its immediate raw gain looks attractive.

### Learns prospectively without chasing outcomes

Every final, data-checked GW can score the immutable pre-deadline selected action and all frozen
alternatives. The receipt reports action regret, a legal hindsight XI/captain upper bound, captain
regret inside the frozen XI, xP error, appearance Brier score and realized deltas for frozen
form-reversion/market challenger choices. These counterfactuals overlap and are never added together.

The season scoreboard keeps the latest valid pre-deadline receipt per GW. The challenger registry
currently tracks five experiments and requires historical success plus ten paired prospective GWs
and a downside bound before even opening a manual review. It cannot promote automatically. Before
GW1 the correct scoreboard state is `awaiting_final_events`.

From GW31, an optional mini-league shadow can compare already-legal actions with prior-GW rival
lineups, the points gap and rival-exposure distance. It enforces a small expected-points sacrifice
cap. It is not yet a web screen, has no decision authority and cannot replace the points-first call.

## Start the complete local product

Terminal 1:

```bash
cd /home/lewis/Workspace/fpl-mcp-server
FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src uv run python -m fpl_server.main
```

Terminal 2:

```bash
cd /home/lewis/Workspace/fpl-agent
bash scripts/run_local_web.sh
```

Open <http://127.0.0.1:5173>. Supporting ports are API `8000`, private Qwen `8011`, embedded login
`8020` and MCP `8021/mcp`.

## Manual test sequence

1. **Cold open:** confirm the skeleton resolves into the cached squad without waiting for Qwen.
   Check that the header says preseason/GW1 and that freshness has an observed/model timestamp.
2. **Embedded login:** open Season identity. Complete the MCP form inside the modal. Confirm the
   modal reports connection, returns to the workspace, and the pitch source becomes `FPL synced`.
3. **App-open refresh:** reload once. An existing MCP session should sync silently, then show a
   published, reused, attention or blocked refresh message without blanking the prior squad.
4. **Whole-squad audit:** switch pitch/list, click starters and bench players, inspect all 15 scores,
   review availability and bench metrics, and preview any recommended XI/armband changes.
5. **Published model squad:** choose Generate/Improve, activate the published baseline and confirm
   the pitch, captain, critique and chat context all change together.
6. **Constrained build:** choose a horizon and risk profile, lock at least one current player, exclude
   another and add a club minimum. Confirm a legal candidate appears in seconds and respects every
   constraint.
7. **Screenshot:** upload a Pick Team screenshot. Wait for extraction, check the resolved count and
   legality, then confirm it. Confirm the uploaded draft becomes the active pitch and receives a
   full 15-player critique.
8. **Chat grounding:** ask “Who should I captain and why?”, “Should any bench player start?”, “What
   is the weakest position in this 15?” and “Rebuild around three Liverpool players while keeping
   X”. Numerical answers should agree with the active pitch/receipt or state why data is missing.
9. **Evidence:** open “Inspect sources and receipt”. Confirm paths and SHA-256 hashes are visible and
   freshness warnings are explicit.
10. **Manual refresh:** use Refresh workspace. Repeated clicks should join one run. An unchanged run
    should reuse the content-addressed result; a failure must retain the previous decision.
11. **Preseason weekly boundary:** the weekly transfer card may correctly say pending/not ready.
    FPL has not yet exposed truthful post-GW1 transfer-bank and purchase-price state.
12. **Shutdown:** press `Ctrl+C` once in the web launcher terminal and once in MCP. Both should return
    to the shell without a lingering daemon.

Useful health checks:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/v1/workspace/refresh
curl -s http://127.0.0.1:8000/api/v1/workspace/refresh/schedule
curl -s http://127.0.0.1:8000/api/v1/market/telemetry
```

## New evidence commands

```bash
.venv/bin/fplagent prospective-scoreboard
.venv/bin/fplagent challenger-registry
```

After a final GW, score its frozen decision first:

```bash
.venv/bin/fplagent score-weekly-event --event 2
.venv/bin/fplagent prospective-scoreboard
.venv/bin/fplagent challenger-registry
```

The late-season shadow uses a manually or MCP-produced `mini_league_context_v1` file:

```bash
.venv/bin/fplagent mini-league-shadow \
  --decision data/decisions/weekly/event-32/DECISION.json \
  --context data/web/state/mini-league-context.json
```

## Honest current boundaries

- No FPL writes; all recommendations must be applied manually.
- A genuine weekly end-to-end run cannot be tested until official post-GW1 manager state exists.
- Rival context is not yet collected or configured in the web UI.
- Rejected price, fixture, chip and forecast challengers remain diagnostics, not hidden inputs.
- The local MCP login/session and Qwen process are single-user localhost services, not hosted
  multi-user architecture.
- Screenshot analysis uses a separate GPU process; production concurrency still needs a shared GPU
  queue.
