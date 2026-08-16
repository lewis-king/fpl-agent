# Data layout

Generated data is intentionally not committed. Every artifact can be rebuilt from the source
catalog and the raw-file provenance log.

```text
data/
  raw/          immutable HTTP responses and downloaded source files
  processed/    normalized Parquet tables
  model/        feature contracts, CUDA model artifacts, forecasts and audits
  decisions/    content-addressed recommendation receipts
  llm/          generated SFT/RAG data and reproducibility manifests
  manifests/    checksums, URLs, timestamps and build validation
  fpl_history.duckdb  generated views and table catalog for interactive analysis
```

Run `uv run fpl-data catalog` after preprocessing. Query `dataset_catalog` to see every
available view, its source path, row count and column count. View names are stable and
source-prefixed, such as `vaastav_player_gameweeks`, `solio_manager_outcomes`,
`fpl_genius_captaincy` and `fpl_current_players`.

## Historical coverage

| Source/table family | Seasons or dates available |
| --- | --- |
| Vaastav player-gameweeks and player snapshots | 2016/17–2025/26 (10 seasons) |
| Vaastav fixtures | 2018/19–2025/26 (the two older files are not in the public repository) |
| Vaastav teams | 2019/20–2025/26 (the three older files are not in the public repository) |
| Mike Croft veteran posts/workbooks | Public post archive exhausted, April 2016–May 2026 |
| Solio complete manager outcome population | 2025/26 |
| FPL Genius top-100 decision histories | 2025/26, events 1–38 |
| Vaastav/Paul top-manager records | 2019/20 |
| Titan manager cohort | 2022/23 |
| Soong seven-manager histories | 2025/26 |
| Official FPL preseason snapshot and rules | 2026/27 |
| SofaScore confirmed preseason lineups (third-party advisory) | 2026/27, refreshed during preseason |
| SofaScore independent player-event feed | 2023/24–2025/26 complete; 2026/27 live collector armed |
| Vaastav deadline-proxy snapshots | 2023/24: 37 GWs; 2024/25: 35 GWs; 2025/26: 11 GWs |
| Football-Data pre-closing market odds | 2019/20–2025/26 historical; upcoming-fixture feed polled for 2026/27 |

## Principal processed tables

| Path | Grain | Purpose |
| --- | --- | --- |
| `processed/solio/manager_outcomes.parquet` | manager/season | All 2025/26 manager outcomes and Solio projections |
| `processed/solio/top100.parquet` | manager | Exact top-100 IDs used to seed decision retrieval |
| `processed/fpl_genius/managers.parquet` | manager | Top-100 result and score metadata |
| `processed/fpl_genius/transfers.parquet` | manager/transfer | GW, player in/out and factual transfer cost |
| `processed/fpl_genius/captaincy.parquet` | manager/GW | Actual and comparator captain names |
| `processed/fpl_genius/decisions.parquet` | manager/decision | Modelled decision fields; never treated as ground truth |
| `processed/veterans/candidates.parquet` | manager | Public veteran candidates and recency score |
| `processed/veterans/posts.parquet` | Reddit post | Post metadata and linked workbook IDs |
| `processed/veterans/rows.parquet` | workbook row | Lossless normalized spreadsheet records |
| `processed/vaastav/player_gameweeks.parquet` | player/fixture/GW/season | Historical player state and returns; double gameweeks retain multiple rows |
| `processed/vaastav/fixtures.parquet` | fixture/season | Historical fixture context |
| `processed/vaastav/players.parquet` | player/season | Season player snapshots |
| `processed/vaastav/top_manager_*.parquet` | manager/GW/player | 2019/20 top-10 manager archive |
| `processed/supporting/soong_*.parquet` | manager/GW or final pick | Seven-manager 2025/26 histories, chips and final squads |
| `processed/fpl/2026-27/preseason/rules.parquet` | season snapshot | Budget, transfer carryover, squad and scoring rules |
| `processed/fpl/2026-27/preseason/chips.parquet` | chip availability window | The eight first-/second-half chip instances |
| `processed/fpl/2026-27/preseason/positions.parquet` | position | Squad and lineup constraints by position |
| `processed/supporting/sofascore/2026-27/preseason_events.parquet` | club/friendly | Confirmed preseason team-event coverage |
| `processed/supporting/sofascore/2026-27/preseason_lineups.parquet` | club/friendly/source player | Confirmed lineup, starter and nullable minute evidence |
| `processed/supporting/sofascore/2026-27/preseason_role_evidence.parquet` | current FPL player | Join-date-aware listing/start/appearance evidence; advisory only |
| `processed/supporting/sofascore/player-events/<season>/player_events.parquet` | source player/match | Independent role, chance and defensive events with post-match availability timestamps |
| `processed/supporting/sofascore/player-events/<season>/player_mapping.parquet` | source player/season | Club-restricted, fail-closed FPL identity mapping |
| `processed/vaastav_deadlines/player_snapshots.parquet` | player/decision GW | Latest public commit observed before the inferred deadline |
| `processed/vaastav_deadlines/fixture_snapshots.parquet` | fixture/decision GW | Point-in-time schedule and FDR proxy |
| `model/features/player_deadlines.parquet` | player/GW | Leakage-gated historical training rows |
| `model/features/current_player_horizons.parquet` | player/future GW | Live preseason features for the planning horizon |
| `model/forecasts/rolling-backtest.parquet` | player/GW/fold | Strict rolling out-of-season model forecasts |
| `model/forecasts/2026-27-preseason.parquet` | player/future GW | Current expected-points and participation forecast |
| `decisions/2026-27-gw1-initial-squad.json` | recommendation receipt | Legal squad, lineups, planning transfers, hashes and stability |
| `decisions/2026-27-gw1-candidates.json` | candidate/squad | Reproducible 128-squad premium, bench and forecast-perturbation field |
| `model/tournament_v1/gw1-5-candidate-metrics.parquet` | candidate | Base, premium-recovery and appearance-risk tournament metrics |
| `model/tournament_v1/gw1-5-results.json` | tournament run | Calibration, holdouts, knockout survival and transfer-aware finalist policies |
| `model/artifacts/component_v1/goal-model.joblib` | model artifact | CUDA-trained Poisson fixture-goal model and imputation contract |
| `model/artifacts/component_v1/2026-27-preseason-goal-rates.parquet` | fixture | Current home/away goal rates and clean-sheet probabilities |
| `model/features/player_components.parquet` | player/GW | Deadline-safe stable-component training targets and features |
| `model/artifacts/component_v2/models.joblib` | model artifact | CUDA goal, assist and bonus player-event models with season-forward gates |
| `model/forecasts/2026-27-preseason-components.parquet` | player/future GW | Current player event-component forecasts |
| `model/component_backtest_v1/rolling-player-components.parquet` | player/GW/fold | Season-forward reconstructed component and incumbent xP forecasts |
| `model/component_backtest_v1/metrics.json` | backtest receipt | Validation-selected raw/xP blend and untouched-season result |
| `model/normalized/historical_market_goal_rates.parquet` | fixture | De-vigged pre-closing 1X2/totals probabilities converted to home/away Poisson rates |
| `model/normalized/historical_market_goal_rates_receipt.json` | source/build | Raw season hashes, source URLs, information policy and frozen fixture-metric gate |
| `model/market_goal_policy_v1/results.json` | event/policy | Validation-selected legal squad/XI/bench/captain replay and untouched-season result |
| `model/market_transfer_policy_v1/results.json` | season path | Continuous validation/test replay with bank, purchase/selling prices, carried transfers and hits |
| `model/return_distribution_v1/rolling-return-distribution.parquet` | player/GW/fold | Season-forward probabilities for under-five, 5–9 return and 10+ haul outcomes |
| `model/return_distribution_v1/results.json` | forecast/policy receipt | Frozen blend selection, legal independent-squad tests and continuous validation/test transfer paths |
| `model/external_forecast_benchmark_v1/rolling-forecasts.parquet` | player/deadline/fold | Matched OpenFPL-method reproduction forecasts on the champion's exact outer folds |
| `model/full_distribution_calibration_v1/results.json` | prospective player/decision role | CRPS, interval, p10/p90, CVaR and haul-tail calibration gate |
| `model/price_liquidity_scenarios_v1/results.json` | price night/decision | Timestamp-safe price-direction and realized net-points timing gate |
| `decisions/2026-27-gw1-component-candidates.json` | candidate/policy | Legal component-native squads generated on the selection seed |
| `model/tournament_v2/component-gw1-5-candidate-metrics.parquet` | candidate | Raw and xP-anchored match-component tournament metrics |
| `model/tournament_v2/component-player-calibration.parquet` | player/GW | Full point-component decomposition and xP anchor audit |
| `model/tournament_v2/component-gw1-5-results.json` | tournament run | Component backtests, identities, conservation checks, gates and finalist policies |

## Live official snapshot

The current-season snapshot comes directly from FPL's public, unauthenticated application
endpoints, not from a historical GitHub mirror:

```bash
uv run fpl-data refresh-current
uv run fpl-data snapshot-status
```

The source catalog resolves these to `https://fantasy.premierleague.com/api/bootstrap-static/`
and `https://fantasy.premierleague.com/api/fixtures/`. Each collection is immutable under
`raw/fpl/2026-27/snapshots/live/<UTC snapshot ID>/`, with its own manifest, source URLs, byte counts
and SHA-256 hashes. `manifests/fpl-current-snapshot.json` advances only after structural validation;
`manifests/fpl-current-refresh.json` binds the raw snapshot to the normalized Parquet checksums and
DuckDB catalog receipt.

Freshness is recalculated whenever `snapshot-status` runs. The allowed age tightens from 72 hours
early in preseason to 24 hours inside T-72h, six hours inside T-24h, one hour inside T-6h and ten
minutes inside the final hour. Missing, malformed, referentially inconsistent, checksum-changed or
stale data is not publishable. Use `refresh-current --reuse-latest` to reproduce normalized tables
from the pointed immutable capture without making another network request.

Authenticated MCP sync follows the same rule. The application archives an allowlisted
`manager-state.json` containing the 15 picks, purchase/selling prices, bank, transfer state and chip
inventory under `raw/fpl/2026-27/manager-snapshots/<entry>/<UTC snapshot ID>/`. Credential, token,
email and cookie-like keys are rejected before writing. A schema-valid preseason response with
unavailable finance fields can still be displayed, but its manifest is explicitly incomplete and
cannot pass the decision-publication gate.

The old `raw/fpl/2026-27/snapshots/preseason/` files remain a read-compatible fallback only until a
valid live pointer exists. Preseason player totals in bootstrap may still be carry-over or reset
fields rather than observed 2026/27 outcomes, so they are never interpreted as new-season match
results.

## Pre-closing market fixture evidence

Run `uv run fplagent audit-market-goals` to rebuild the historical challenger from Football-Data's
Premier League CSV archive. The pipeline uses only the fields the provider documents as
pre-closing (`AvgH`, `AvgD`, `AvgA`, `Avg>2.5`, `Avg<2.5`); columns with the closing marker `C` are
excluded. Every raw season is retained with its URL and SHA-256 hash, prices are de-vigged and the
resulting probabilities are fitted to two independent-Poisson goal rates.

Run `uv run fplagent collect-current-market-goals` to check the provider's separate upcoming
fixture file. It returns `not_ready` unless all ten next-event Premier League fixtures have complete
1X2 and total-goals prices and the source page's upload time precedes the official FPL deadline. A
ready collection is archived immutably before normalized current rates and a receipt are published.
Partial coverage never fills missing fixtures with guessed prices and cannot change production.

The historical data is used for non-commercial research in this project. Public accessibility is
not permission to republish the provider's raw odds; retain attribution and re-check terms before
any product scope changes.

## Preseason lineup evidence

Run `uv run fpl-data collect-preseason-lineups` to capture completed, confirmed preseason lineups
from SofaScore's public web API. This is an unofficial third-party source. Responses are archived by
content hash and the current receipt is `manifests/preseason_lineups_current.json`.

Resolution is conservative and team-scoped. Academy, trial and departed players absent from the
current FPL catalog remain unmatched; ambiguous names are never forced. Missing source minutes stay
null rather than becoming zero. The derived role table records minute-data completeness separately
from lineup/start evidence and respects each FPL player's `team_join_date`.

This layer is advisory. A missing player or club feed is not evidence of injury or future DNP, and
the collector cannot mutate production forecasts. See the
[preseason role evidence audit](../reports/preseason-role-evidence-audit.md) for current coverage and
the required scenario/policy gate.

Run `uv run fplagent audit-preseason-role` after a refreshed collection to execute the read-only
conditional-DNP sensitivity audit. It verifies the evidence and official-table checksums before
simulating, assigns no probability weights to the counterfactual bounds, never penalizes an
uncovered club and cannot mutate the published forecast or decision.

Run `uv run fplagent audit-preseason-threshold` after that scenario receipt to refine the severe-to-
moderate sensitivity path. The command checksum-binds the scenario, evidence, forecasts and live
decision, selects from configurations discovered by the prior exhaustive endpoint searches, and
uses a fresh independent holdout. Its retention factors are mechanical perturbations, not player
availability estimates, and its receipt cannot mutate production.

Run `uv run fplagent availability-status` for the current operational view. It checksum-binds the
published 15, GW1 forecast, normalized official player table, preseason receipt, role evidence,
scenario audit and threshold curve. Each selected player receives official status/news, forecast
`p_play`, preseason role evidence and any supported-edge sensitivity value. The output is written
to `manifests/fpl-availability-watch.json`; it can require refresh or verification, but it always
sets `decision_change_authorized: false`. `fplagent deadline-status` includes a compact summary of
the same advisory receipt without allowing third-party preseason evidence to redefine the official
publication gate.

## Important caveats

- Public accessibility is not equivalent to permission to republish source data commercially.
- Historical FPL player `xP`/`ep_this` may contain post-deadline information. Shift or omit it.
- FPL Genius scores, expected points and baselines are third-party model outputs. Use its factual
  transfers, captaincy and chip timing separately from those judgements.
- Mike Croft's veteran workbooks change schema between seasons. `rows.parquet` preserves every
  row as canonical JSON plus common query columns rather than silently coercing old schemas.
- Manager picks and transfers from the official FPL API disappear after season rollover. The
  live collector must run after every deadline during 2026/27.
- Vaastav's 2016/17–2018/19 gameweek files are decoded as Latin-1; later files are UTF-8.
  The pipeline parses both groups strictly and removes only byte-for-byte duplicate records.
- The pandemic-interrupted 2019/20 source has 38 event labels spanning `GW=1..47`, and the
  fully postponed 2022/23 GW7 has no player-fixture rows. Never infer chronology from a naive
  assumption that every historical season has labels 1 through 38.
- Historical ownership is normalized to a within-deadline percentile because older gameweek
  files expose manager counts while deadline snapshots expose percentages. Mixing the raw scales
  is prohibited.
- Pre-2022/23 xG/xA and pre-2025/26 defensive-contribution values remain null, not synthetic zero.
  XGBoost handles the missing eras explicitly.
- Coventry City and Hull City have no Premier League team prior in the ten-season corpus, while
  Ipswich Town's prior is stale. The live point-in-time FDR remains available and the missing/stale
  form state is preserved for the model rather than silently filled.
