# Live feature availability contract

**Implemented:** 8 August 2026  
**Purpose:** guarantee that features proven on historical data are also available, timely and
traceable during the live 2026/27 season.

## Outcome

The weekly engine now has a complete serving path for player xG, xA, minutes, points, goals,
assists, BPS, clean sheets and defensive contributions. The first completed event is not available
before GW1 by definition. Once FPL marks an event both `finished` and `data_checked`, the normal
weekly refresh automatically downloads its official event payload, archives the exact bytes,
normalizes the player-event rows and adds them to the rolling priors used for future forecasts.

This closes a real training/serving gap. Previously, those current rolling priors were populated
only from the historical Vaastav tables, so a live 2026/27 result would not have advanced form,
minutes, xG or xA without a code change.

## Production source map

| Signal | Historical training | Live 2026/27 serving | Validation/fallback |
| --- | --- | --- | --- |
| Player points, minutes, goals, assists, xG, xA, BPS, clean sheets, defensive contributions | Point-in-time player Gameweek archive | [Official FPL event-live endpoint](https://fantasy.premierleague.com/api/event/1/live/), one immutable payload per final event | Reconciled to cumulative fields in [official bootstrap-static](https://fantasy.premierleague.com/api/bootstrap-static/); [element-summary](https://fantasy.premierleague.com/api/element-summary/426/) is a per-player repair/reconciliation route, not the primary bulk feed |
| Prices, availability, ownership, transfers in/out, set-piece order | Deadline-safe historical snapshots/proxies | Current official bootstrap snapshot | Snapshot freshness and lineage gate |
| Fixture allocation, blanks/doubles, scores and kickoffs | Point-in-time fixture archive | [Official fixtures endpoint](https://fantasy.premierleague.com/api/fixtures/) | Versioned schedule receipt; final scores feed online team ratings |
| Opponent-adjusted team attack/defence | Leakage-safe sequential match updates | Prior-season terminal state plus every official result knowable before the next deadline | One shared pre-deadline information set per event |
| Manager squad, bank, transfers, chips and selling prices | Manager replay datasets | Authenticated local MCP snapshot | Exact manager-state completeness/freshness contract |

The event-live endpoint currently returns an empty `elements` list because GW1 has not been played.
That is a valid preseason state, not missing data. Its first non-empty 2026/27 payload can only be
verified after GW1. The collector therefore validates the required field names and numeric values
at that moment and blocks publication if the API schema has changed.

## Weekly path

1. Collect and validate one immutable official bootstrap/fixtures generation.
2. Discover every event marked both final and data-checked.
3. Verify and reuse already archived outcomes; download only missing event-live payloads.
4. Require an exact official player set and numeric values for every production event statistic.
5. Exclude a club blank from form windows rather than recording it as a zero-minute appearance.
6. Build a contiguous current-season player-event Parquet file with source hashes.
7. Union those events with historical player history by stable player code.
8. Recompute 3/5/10-event points and minutes, 5-event xG/xA and participation priors.
9. Update opponent-adjusted team ratings from scores known before each target deadline.
10. Emit the next actionable forward horizon—GW2–GW6 after GW1, rather than GW1–GW5 forever.
11. Run the live feature contract before any forecast or decision can publish.

## Fail-closed checks

After at least one event is final, a model rebuild is blocked when any of these are true:

- a finalized event outcome is missing or events are non-contiguous;
- a finished event is still awaiting FPL's `data_checked` finality flag;
- the archived event or its official bootstrap lineage changed;
- xG, xA, minutes, points or another required statistic is missing/non-numeric;
- normalized event totals do not reconcile to official cumulative player totals;
- the latest live points did not reach the forecast feature matrix;
- the forecast or team-strength grids do not cover the requested forward horizon; or
- an official snapshot is stale under the deadline-aware freshness rules.

The receipt is [`data/manifests/fpl-live-feature-contract.json`](../data/manifests/fpl-live-feature-contract.json).
The normalized live history will first appear at
`data/processed/fpl/2026-27/current-history/player-events.parquet` after GW1 is final.

## Operational commands

The normal authenticated weekly run performs outcome synchronization automatically:

```bash
.venv/bin/fplagent deadline-run --manager-entry-id <id> --horizon 5
```

The explicit collector remains useful for inspection or repair, and prospective scoring remains a
separate immutable step:

```bash
uv run fpl-data collect-event-outcome --event 1
.venv/bin/fplagent score-weekly-event --event 1
```

No model is promoted because the data exists. This contract only guarantees feature parity and
lineage; the existing forward validation, sequential policy replay and prospective promotion gates
still decide whether a feature/model is useful enough to influence FPL actions.
