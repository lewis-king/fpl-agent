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
holdout simulations, audits the longer horizon, synthesises the decision, runs role scenarios and
publishes atomically. Do not pass `--reuse-latest-official` for a deadline run.

The browser can close without cancelling a server-owned refresh. Progress is stored in
`data/manifests/fpl-gw1-deadline-pipeline.json`; post-synthesis evidence stages can resume from
checksum-valid staged artifacts. A failed run retains the previous published decision.

## Final falsification and pack

After the transactional pipeline publishes:

```bash
.venv/bin/fplagent audit-bench-allocation
.venv/bin/fplagent audit-structure-stress
.venv/bin/fplagent build-deadline-pack
```

The pack is ready only when `data/manifests/gw1-deadline-pack.json` says
`"verdict": "DEADLINE_READY"`. Its human-readable counterpart is
`reports/gw1-deadline-pack.md`.

The independent gates mean:

- `data_quality`: every official selectable player exists in the current model grid and all
  historical/current feature contracts pass;
- `transactional_pipeline`: the active decision is byte-identical to the atomically published
  artifact;
- `availability_and_frontier`: every player in every synthesis finalist has official, forecast and
  role evidence;
- `historical_selector`: live horizon-family and minimax weights match the historically gated
  production values;
- `scoring_formation_autosubs`: no supported challenger wins after exact autosubs and bounded
  bonus/defensive-contribution misspecification;
- `bench_allocation`: the visible GW1 bench is justified as a rotating 15-player squad rather than
  by an arbitrary bench-spend preference;
- `betting_market`: all ten GW1 fixtures have one coherent, checksum-bound Betfair generation; and
- `global_search`: the run included genuinely distant MILP/evolution candidates, not only local
  swaps around an old answer.

## Deadline cadence

While the local API is running, validate on a six-hour cadence until T-24h, every two hours from
T-24h to T-3h, and every 30 minutes inside T-3h. A material official status/news, price, fixture,
forecast or market semantic change starts an immediate run between cadence slots. An app open
reuses the last validated receipt inside the same deadline-aware interval; a manual check bypasses
that reuse window.

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
