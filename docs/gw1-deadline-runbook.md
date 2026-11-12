# GW1 deadline runbook

This is the operational path for producing the current GW1 recommendation. It is intentionally
stricter than opening the web app: no squad is called deadline-ready until the complete search and
the independent falsification audits all describe the same forecast and decision bytes.

## Normal full run

From the repository root, with the project environment installed:

```bash
.venv/bin/fplagent gw1-deadline-run --as-of "$(date -Iseconds)"
```

The command captures a new immutable official generation, refreshes market and participation
evidence, rebuilds forecasts, searches the legal squad universe, runs independent selection and
holdout simulations, audits the longer horizon and synthesises the selected 15. It then exhaustively
configures that squad in simulated GW1 worlds before running the remaining role and falsification
scenarios and publishing atomically. Do not pass `--reuse-latest-official` for a deadline run.

The browser can close without cancelling a server-owned refresh. Progress is stored in
`data/manifests/fpl-gw1-deadline-pipeline.json`; post-synthesis evidence stages can resume from
checksum-valid staged artifacts. A failed run retains the previous published decision.

## Final falsification and executable handoff

After the transactional pipeline publishes:

```bash
.venv/bin/fplagent audit-bench-allocation
.venv/bin/fplagent audit-structure-stress
.venv/bin/fplagent build-deadline-handoff
```

The final command checksum-reuses the player-specific minutes audit when it is still current, then
reruns the five leading squads on three independent 25,000-world seeds and a bounded objective
weight grid, rebuilds exact legal contingencies, the shared-world GW1 chip comparison, the deadline
pack and a single canonical entry receipt. It is ready only when both
`data/manifests/gw1-deadline-pack.json` says `"verdict": "DEADLINE_READY"` and
`data/model/deadline_execution_receipt_v1/results.json` says `"verdict": "READY_TO_ENTER"`.
Use [the standalone execution receipt](../reports/gw1-deadline-execution.html) for the final manual
entry check; the deeper evidence remains in `reports/gw1-deadline-pack.md`.

A successful browser-owned GW1 refresh performs this same handoff automatically. If any handoff
check fails, the web refresh is marked blocked and the last complete ready receipt remains active.

The independent gates mean:

- `data_quality`: every official selectable player exists in the current model grid and all
  historical/current feature contracts pass;
- `transactional_pipeline`: the active decision is byte-identical to the atomically published
  artifact;
- `availability_and_frontier`: every player in every synthesis finalist has official, forecast and
  role evidence;
- `historical_selector`: live horizon-family and minimax weights match the historically gated
  production values;
- `multi_seed_decision_stability`: the selected squad wins the declared production objective on
  all three independent simulation seeds and remains within 0.25 synthesis-regret points of every
  winner across the bounded horizon/minimax weight grid. This detects Monte Carlo accidents and
  material objective brittleness without pretending that a small weight change must preserve the
  exact rank order;
- `simulation_configuration`: every legal XI from the selected 15, every legal outfield bench
  order, and captain/vice combinations are evaluated in residual and explicit football-component
  worlds. The selection champion must remain the champion on independent holdout seeds before it
  may replace the synthesized configuration; disagreement blocks publication;
- `scoring_formation_autosubs`: no supported challenger wins after exact autosubs and bounded
  bonus/defensive-contribution misspecification;
- `bench_allocation`: the visible GW1 bench is justified as a rotating 15-player squad rather than
  by an arbitrary bench-spend preference;
- `betting_market`: all ten GW1 fixtures have one coherent, checksum-bound Betfair generation;
- `market_generation_matches_forecast`: the published forecast names the exact active receipt and
  rate-artifact hashes, including the historically promoted 20% defender and 5% forward signals;
- `global_search`: the run included genuinely distant MILP/evolution candidates, not only local
  swaps around an old answer;
- `player_specific_participation_break_even`: watched squad players have isolated expected-minutes
  curves on independent selection and holdout worlds rather than one arbitrary injury threshold;
- `causal_participation_boundaries`: an actionable threshold exists only when the central squad is
  supported at the live anchor and a monotone deterioration creates a bracketed reversal below it.
  A challenger already supported at the live anchor is a general GW1/multiweek trade-off, not a
  future news trigger;
- `executable_contingencies`: every central and fallback route is a named, budget-valid 15, XI,
  bench order and captain/vice configuration, and an actionable fallback's one-GW floor must repay
  its declared multiweek synthesis regret; and
- `gw1_chip_decision`: no-chip, Bench Boost and Triple Captain are compared on identical worlds,
  while a one-week uplift cannot spend a scarce chip without an authority-bearing retained-value
  policy.

The current participation boundaries and chip result are decision inputs, not generic folklore.
If attributable evidence crosses a causal named minutes boundary, regenerate the complete pipeline
before using the precomputed legal route. A monitor-only route is never an instruction to change
the official squad. A strong immediate chip signal is reported even when it remains non-actionable,
so option-value uncertainty is visible rather than silently discarded.

## Deadline cadence

While the local API is running, validate on a six-hour cadence until T-24h, every two hours from
T-24h to T-3h, and every 30 minutes inside T-3h. A material official status/news, price, fixture,
forecast or market semantic change starts an immediate run between cadence slots. An app open
reuses the last validated receipt inside the same deadline-aware interval; a manual check bypasses
that reuse window.

A transient market-provider failure cannot erase a ready generation collected within the same
six-hour cadence. Retention is allowed only when the active receipt is ready for the decision event,
its checksum and exact official fixture set still match, its provenance predates the deadline and
its collection age is at most six hours. The failed observation is written separately. Any stale,
wrong-event or incoherent generation still fails closed.

The final 30-minute runs should favour freshness and deterministic reuse over starting research
experiments. Do not change model code, weights or rule assumptions between the last completed
calibration and the final transaction.

## What to do when blocked

Read the failed gate in the pack or the pipeline receipt. Fix or refresh the named evidence layer,
then rerun the complete affected command. Never edit a decision JSON by hand and never promote a
staged candidate around a failed role, lineage, market or scoring gate.

Predicted lineups and preseason friendlies remain advisory even when fresh. An official FPL or
attributable club/manager update can justify a full rerun; a third-party disagreement alone cannot
silently rewrite production minutes.

The SofaScore friendly-lineup archive is checksum-validated but is not recollected by a normal
deadline run. It is an optional, zero-weight research stress input, not an operational dependency.
The separate FFScout/RotoWire predicted-lineup consensus is refreshed fail-soft after official
data and remains shadow-only until its prospective legal-policy gate passes.
