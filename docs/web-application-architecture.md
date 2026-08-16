# FPLAgent web application architecture

Status: implemented preseason vertical slice and season-long product contract, 6 August 2026

## Product contract

FPLAgent is one continuous manager workspace whose emphasis changes with the FPL calendar. It is
not a squad picker, screenshot utility and chatbot placed beside each other. The pitch, numeric
engine, multimodal importer and FPL-tuned Qwen assistant all read or change the same active manager
state.

The durable product promise is:

1. The pitch always represents the manager's current submitted squad or active proposal.
2. Numeric recommendations come from the deterministic decision engine, not from LLM arithmetic.
3. Post-GW1 action advice is read from a versioned weekly decision receipt. The workspace presents
   the selected route and strongest rejected alternative with transfer cost, retained free-transfer
   state and paired uncertainty; a missing or invalid receipt is shown as pending or blocked rather
   than reconstructed in the browser.
4. Chat can explain a decision or request a new constrained scenario through typed tools.
5. Every recommendation exposes freshness, caveats, inputs and a receipt.
6. Nothing writes to the real FPL account in this application version.

## Season narrative

The backend publishes a phase and its available decision modules. The browser should never infer
product state from its own clock.

| Phase | Manager's primary question | Dominant modules |
| --- | --- | --- |
| `preseason` | What should my GW1 squad be? | Full-squad generation, screenshot import, structure, bench and captaincy |
| `pre_deadline` | What should I change before lock? | Roll versus transfer, hits, XI, bench, captaincy and chips |
| `live_gameweek` | How are my submitted decisions doing? | Immutable submitted XI, live points, autosubs, rank exposure and watchlist |
| `review` | What did we learn and what is next? | Outcome attribution, forecast error and next-deadline planning |

The implemented UI is fully testable for preseason. The phase resolver now reads the complete
official event calendar: it advances from preseason to the live submitted event, keeps the next
decision event/deadline separately actionable, switches to the next pre-deadline desk once the prior
event is data-checked, and reaches season review after the final deadline. The remaining work is the
phase-specific presentation and live-score/submitted-snapshot ingestion, not calendar inference.

During a live gameweek the submitted snapshot must remain immutable even if a future squad proposal
exists. Proposed transfers belong to the next deadline and must not rewrite the team whose points
are currently being tracked.

## Preseason journeys

### Start from the model

The published robust GW1 recommendation is precomputed by the expensive search pipeline and can be
activated immediately. A manager can then request a fast scenario with:

- a balanced, safer or upside scoring policy;
- a three-, five- or eight-gameweek horizon;
- players locked into the result;
- players excluded from the result; or
- a minimum number of players from a named club.

These scenarios use the latest prepared forecasts and solve only the constrained selection problem.
On the current machine a three-gameweek scenario takes roughly one second, five gameweeks roughly
three seconds and eight gameweeks roughly eight seconds. This preserves a responsive product while
keeping the expensive global robust search as a background publishing concern.

### Bring an existing draft

```text
drop, browse or paste screenshot
              │
              ▼
image signature, size check and preview
              │
              ▼
Qwen vision extraction + optional OCR evidence
              │
              ▼
current-catalog resolution + deterministic legality checks
              │
              ▼
visual review and explicit confirmation
              │
              ▼
active squad snapshot + deterministic critique
```

The vision model reads the layout and visible labels. It is not trusted to invent player IDs or
decide whether a squad is legal. Those steps use the current catalog and strict rules. An upload
only becomes the active squad after confirmation.

Screenshot upload is primarily onboarding. Once an FPL entry and authenticated connection exist,
later gameweeks refresh from the account integration instead of asking the manager to upload the
same team repeatedly. A screenshot remains useful for a manager joining mid-season or analysing a
third-party draft.

### Converse and reshape

The Qwen assistant receives the active state through `get_manager_state`, resolves names with
`search_players`, and requests new legal builds through `optimize_squad`. For example, “keep Watkins
but use three Liverpool players” becomes explicit player locks and a club minimum. The optimiser
changes the active candidate; chat then explains the result and the pitch refreshes.

The LLM is the language and orchestration layer. It does not replace budget rules, club limits,
forecast calculations, optimisation, freshness checks or decision receipts.

### Whole-squad selection and captaincy

An XI or captain recommendation always begins with the complete 15-player squad. The deterministic
engine finds the highest-scoring legal XI (one goalkeeper, three to five defenders, two to five
midfielders and one to three forwards), including the extra value of the captain score, and then
ranks captain and vice-captain inside that recommended XI. A player stored on the current bench can
therefore be promoted into the XI and can become captain; the displaced starter is reported as an
explicit swap.

The submitted/current XI and armband remain visible as account state and are never silently
rewritten. The decision receipt separately reports current versus recommended lineup, captain and
vice-captain. A chat request naming two players creates an additional pairwise comparison only; its
winner cannot replace the full-squad recommendation. Open questions such as “Who should I captain?”
do not apply a candidate filter.

The pitch therefore has an explicit `Your FPL squad` / `Recommendation` state control.
`Your FPL squad` preserves the authenticated XI, bench order and badges. In preseason,
`Recommendation` is the validated 15-player optimiser result and is the default, authoritative
view; in-season it is the selected legal transfer/XI/captain action. The deadline cockpit reports
the exact incoming and outgoing players, same-event xP delta, publication-gate count, candidate ID,
churn-protection state and next automatic validation time. The UI also separates the FPL squad sync
time from forecast observation and model-build times, so syncing an account cannot make older
decision evidence appear fresh.

The application now renders the last validated read model first, silently syncs the authenticated
squad when MCP is connected, and requests one persisted single-flight decision refresh. That daemon
job refetches the official FPL bootstrap and fixtures and invokes the existing GW1 or weekly
deadline pipeline. Content hashes reuse unchanged stages; changed generations stay in staging until
the evidence gate passes and publication is atomic. A failed or interrupted run cannot replace the
active decision and cannot hold local server shutdown open. Its successful pipeline receipt and
hash appear in the evidence dialog. While a run is active, the refresh endpoint reports the current
stage, completed-stage count and total-stage count; the browser renders that receipt as a progress
bar rather than an indefinite spinner.

The local API also runs persisted automatic windows at T−72h, T−24h, T−6h, T−60m and T−10m.
Between windows it compares the public FPL bootstrap and fixture feed with the active snapshot at a
deadline-sensitive cadence (six hours when distant, tightening to 30 seconds in the final ten
minutes). Only decision-relevant semantic changes trigger the expensive single-flight run;
continuously moving transfer counters do not. Scheduler state is available from
`GET /api/v1/workspace/refresh/schedule`.

For GW1, publication stages the squad-specific preseason role scenario, fresh-seed stress threshold
and availability watch alongside synthesis. Every artifact must describe the same decision and
official generation before any byte becomes active. The pipeline checks the cheap role-evidence
lineage immediately after the official refresh and recollects the public preseason lineup layer if
the FPL player mapping changed. If that repair cannot produce a coherent receipt, simulation never
starts and the scheduler circuit-breaks repeated automatic attempts. Runtime tournament prose is
written beneath the ignored decision staging directory, so application refreshes cannot rewrite
the versioned research reports. A change during the final recheck rolls every published artifact
back.

`scripts/refresh_current_forecasts.sh` remains a forecast-only maintenance command. Refreshing does
not retrain models: the UI reports input observation, trained-model creation and manager sync times
separately. Inputs are fresh for six hours, need attention from six to 24 hours, and are stale after
24 hours; final deadline confirmation remains explicit.

## Experience and visual identity

The interface deliberately borrows only the interaction grammar that makes an FPL product
immediately legible: gameweek/deadline language, a football pitch, positional rows, a separate
bench, captain markers and fixture labels.

Its own identity is an editorial “decision room”: stone and forest colours, asymmetric information
density, restrained motion, evidence receipts, crisp typography and a dark intelligence rail. It
does not reuse official FPL gradients, navigation, logos, illustrations or card treatment. The
result should feel related to fantasy football without looking like an unofficial clone.

On wide screens the squad remains central and decision/chat intelligence stays visible beside it.
On phones, the pitch remains primary, the navigation becomes a thumb-reachable bottom rail and
dialogs become full-width sheets. Reduced-motion preferences are respected.

## Active manager state

All capabilities converge on a single point-in-time candidate:

```text
published model build ─┐
custom constrained run ├──► active manager decision ───► workspace/pitch
confirmed screenshot ──┤               │
authenticated MCP sync ┘               ├──► deterministic critique
                                       ├──► captain/decision receipts
                                       └──► grounded Qwen tools
```

The local prototype persists:

| Concept | Current representation | Long-lived design |
| --- | --- | --- |
| User profile and entry ID | `data/web/state/local-manager-profile.json` | `UserProfile` and `ManagerConnection` |
| Active squad/proposal | `data/web/state/active-manager-decision.json` | versioned `SquadSnapshot` rows |
| Exact weekly manager state | `data/model/manager-states/2026-27/<entry>/<snapshot>/<event>/<generation>/` | immutable `ManagerState` plus source lineage |
| Uploaded source and analysis | `data/web/uploads/<id>/` | object storage plus `UploadImport` |
| Forecasts and FPL snapshots | Parquet and DuckDB | immutable observed source snapshots |
| Decision evidence | decision JSON and source hashes | immutable `AnalysisRun` and `DecisionReceipt` |
| Chat session | Qwen sidecar memory | `ChatSession`, turns and tool-call receipts |

Atomic local JSON writes are adequate for the single-user research build. Multi-user hosting needs
a transactional database, immutable snapshot/event tables, object storage and per-user access
control.

Authenticated sync deliberately has two outcomes. The squad can be adopted for the pitch as soon
as the MCP returns 15 legal picks. Weekly optimisation becomes ready only when FPL also exposes
bank, free transfers, committed transfer cost, purchase/selling prices and the relevant chip
inventory. The derived contract records the exact raw-snapshot, forecast and rules hashes. Missing
preseason fields are surfaced as `not_ready`; they are never replaced with zeros or guessed prices.

## Service boundaries

```text
React client :5173
       │ typed HTTP only
       ▼
FPLAgent API :8000
       ├── workspace, profile, uploads and scenario orchestration
       ├── deterministic data/forecast/optimisation engine
       ├── Qwen/Unsloth sidecar :8011
       └── narrow MCP gateway
                  │ streamable HTTP, localhost only
                  ▼
       FPL MCP :8021 ─────► local login page :8020 ─────► FPL
```

The browser never talks directly to the MCP protocol endpoint, Qwen, DuckDB or the optimiser. The
one deliberate exception is the cross-origin login document embedded from port `8020`: credentials
are posted from that document directly to its local MCP web service, so React and the FPLAgent API
cannot inspect them. The browser never receives an FPL access token. The application gateway calls
only four structured MCP tools:

- `get_auth_status` reports in-memory connection state without an FPL network request;
- `begin_web_login` creates the request for the embedded login form;
- `poll_web_login` observes whether it succeeded; and
- `get_manager_snapshot` returns the authenticated 15-player state, bank, value and transfer data.

The sibling MCP server still contains mutation tools for its other clients. FPLAgent does not call
them. Its streamable HTTP mode is bound to `127.0.0.1` and must not be exposed to a network.

## Local authentication lifecycle

1. Run the sibling MCP process separately, then open FPLAgent.
2. FPLAgent discovers MCP and calls the lightweight `get_auth_status` tool.
3. If the process is already authenticated, FPLAgent silently syncs the squad and opens normally.
4. Otherwise, the account connection view opens automatically and asks MCP for a login request.
5. The application embeds the local auth page from port 8020 in a cross-origin frame; there is no
   second browser page and no preliminary Connect step.
6. Playwright completes FPL authentication and the MCP process retains the session in memory.
7. FPLAgent polls through its backend, accepts the authenticated `/me` entry ID as authoritative,
   reads a structured manager snapshot and adopts it.
8. The active pitch, profile and grounded chat now share that authenticated squad.

The login page and MCP transport run on separate asyncio event loops. After authentication, the web
loop reads `/me` and closes its HTTP connection pool. Only the bearer token and inert manager metadata
remain in the in-memory session; the MCP loop lazily creates and owns a fresh HTTP pool for squad
reads. Async clients, locks and events must never be carried from the web loop into MCP tools.

This session currently disappears when the MCP process restarts. FPLAgent automatically presents
the embedded login again, but deliberately does not retain or replay the password. The entry ID
remains in the local profile but is not itself authentication.

## Hosted deployment boundary

The local topology is intentionally a bridge, not a deployable authentication design. A hosted
version cannot assume that the server can reach an MCP process on the visitor's laptop. It must
choose one of two explicit products:

1. A server-side FPL integration service with per-user authentication, encrypted durable session
   material, scoped read capabilities, audit logs and revocation; or
2. A signed local companion application that establishes an authenticated outbound channel to the
   hosted product.

The current general-purpose MCP endpoint, in-memory global session and Playwright login page must
never be exposed publicly. Before real FPL writes are added, require previewable commands, explicit
human confirmation, idempotency keys, post-write verification and a dedicated security review.

## Delivery sequence from here

1. Complete the pre-deadline decision-desk presentation against the implemented weekly receipt.
2. Derive and validate the early-transfer policy from the implemented 15-minute telemetry without
   making transfer-counter noise rerun the whole tournament.
3. Add transfer bundle, XI, bench and chip tools against the same manager state.
4. Add live submitted-team snapshots and post-gameweek attribution.
5. Add durable chat sessions around immutable snapshot/decision records.
6. Design the hosted identity and FPL-session architecture before opening access to others.
