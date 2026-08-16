# SOTA evidence framework

**Implemented:** 15 August 2026  
**Scope:** independent event data, external benchmarking, prospective outcomes, predicted
lineups, forecast distributions and price/liquidity policy.

This framework answers a stricter question than “did a model metric improve?”: did a change use
information that was genuinely available at the decision time, and did it improve a legal FPL
decision on data that did not choose the change?

No component below automatically changes the production picker. Collection, forecast evidence,
legal-policy evidence and promotion are separate states. A failed challenger remains a useful,
checksum-bound research result.

## One promotion path

Every challenger follows the same path:

1. freeze raw source bytes and a retrieval timestamp;
2. map source identities conservatively, retaining ambiguous rows as unmapped;
3. build chronological folds using only rows whose `available_after` precedes the FPL deadline;
4. select weights or hyperparameters on development folds;
5. score an untouched season or prospective Gameweeks;
6. route champion and challenger through the same legal budget, club, formation, XI, bench and
   captain constraints;
7. publish a machine-readable gate and human report; and
8. keep production weight at zero until all component-specific checks pass.

## 1. Independent player-event data

The second provider is SofaScore's public web data, alongside the existing Understat feed. The
collector discovers the EPL season identifier rather than copying an unstable URL suffix. It
archives every response by SHA-256 and writes normalized match, player-event and stable mapping
Parquet files.

The initial historical capture contains 1,140 completed EPL matches across 2023/24–2025/26. The
club-restricted, fail-closed player mapping rates are 95.2%, 96.1% and 98.8%. A player-event row is
not available to a fold until three hours after kickoff. Current 2026/27 collection correctly has
zero finished matches before GW1; future fixtures are never converted into observed player stats.

The first SofaScore signal challenger slightly improved frozen player MAE but lost 15 realized
points in the 2025/26 legal-policy replay. It therefore remains shadow-only. This is the intended
behaviour: source breadth is not evidence of decision lift.

Because it has zero decision authority, SofaScore is not an operational deadline dependency and
the project does not attempt to evade its bot controls. Its archived research artifacts remain
reproducible; normal squad refreshes use official evidence and independently captured FFScout /
RotoWire predicted lineups instead.

Commands:

```bash
uv run fpl-data collect-sofascore-player-events --season 2026-27
uv run fplagent backtest-sofascore-events
uv run fplagent audit-external-player-data
```

Key artifacts:

- `data/processed/supporting/sofascore/player-events/<season>/player_events.parquet`
- `data/processed/supporting/sofascore/player-events/<season>/player_mapping.parquet`
- `data/model/sofascore_event_policy_v1/results.json`
- `data/model/external_player_data_v1/receipt.json`

## 2. Matched OpenFPL benchmark

The benchmark reproduces the published OpenFPL modelling shape: separate position models,
Random Forest and XGBoost candidates, validation-ranked model selection and a median ensemble. It
is pinned to public repository commit `ad055ba7270145ce8ecc1f19581423493b1357e7`.

It is deliberately described as an **OpenFPL method reproduction**. Released weights and scalers
are not falsely presented as compatible with FPLAgent's feature schema. The reproduction is
retrained on the exact FPLAgent chronological outer folds, produces one prediction for every
matched player-deadline row, and shares the same legal solver with the champion. The evidence gate
requires FPLAgent to be no worse on both forecast MAE and realized legal-policy points.

```bash
uv run fplagent benchmark-openfpl --rebuild --top-models 10
```

Outputs are in `data/model/external_forecast_benchmark_v1/` and
`reports/openfpl-matched-benchmark.md`.

## 3. Untouched 2026/27 outcomes

Each weekly decision already freezes its player forecasts, actions, lineup and alternatives before
the deadline. The final-event scorer now also records official BPS and defensive-contribution
fields. The 2026/27 scoreboard has two distinct gates:

- six final events permit the first diagnostic review;
- 19 final events (half a season) are the minimum evidence sample for a SOTA claim.

Past-season rows can never be relabelled as prospective 2026/27 evidence.

```bash
uv run fplagent score-weekly-event --event 1
uv run fplagent prospective-2026-scoreboard
```

## 4. Predicted-lineup calibration

FFScout and RotoWire captures remain immutable and deadline-bound. The scoreboard now measures two
things:

- exact XI hit lift for each covered club; and
- realized points lift after a bounded consensus role adjustment passes through the same legal
  squad, XI and captain solver.

Six events, two sources on at least ten clubs per event, non-negative event floors and positive
aggregate role **and legal-policy** lift are all required. A lineup-hit win by itself no longer
opens production authority.

```bash
uv run fpl-data collect-participation-consensus --event 1
uv run fplagent participation-scoreboard
```

## 5. Full distribution calibration

Every newly frozen decision includes a discrete points probability mass function derived from
position-specific conditional score residuals on the 2023/24–2025/26 rolling backtest plus explicit
DNP mass. This avoids confusing tiny ensemble disagreement with the much larger aleatoric spread
of a player's FPL return. The scorer supports a richer component-simulation PMF through the same
contract.

After finalization it calculates:

- discrete CRPS against a declared reference distribution;
- central 50% and 80% interval coverage and sharpness;
- p10 breaches and p90 exceedances;
- lower and upper 10% CVaR;
- 10+ point haul Brier score; and
- separate position, captain, starter and bench views.

The gate requires six untouched events, at least 200 player outcomes, all positions, and explicit
captain and bench tails. Mean xP improvement cannot substitute for tail calibration.

```bash
uv run fplagent distribution-scoreboard
```

## 6. Price and liquidity scenarios

The existing 15-minute official telemetry now feeds a chronological rise/flat/fall probability
model. Each fold trains only on earlier UK-midnight boundaries. A scenario engine propagates the
probabilities through exact FPL selling-price rules, current bank and every incoming/outgoing
player to estimate forced affordability loss and a p10 future bank. The immediate scenario is
enumerated exactly; seeded three-night paths expose p10/p50/p90 affordability under an explicitly
labelled stationary-transition assumption.

Price accuracy is necessary but insufficient. Promotion also requires six prospectively frozen
move-now/wait decisions whose realized **net FPL points** are positive with a non-negative event
floor. Team value is recorded only as a diagnostic.

```bash
uv run fpl-data build-price-change-outcomes
uv run fplagent calibrate-price-liquidity
```

Before the first sufficiently tight UK-midnight pair, the correct state is `HOLD_SHADOW`; the
system does not manufacture historical timestamps from weekly snapshots.

## Readiness audit

Run all current evidence states through one fail-closed claim boundary:

```bash
uv run fplagent audit-sota-readiness
```

Production readiness and a SOTA claim remain separate. The app can be deadline-grade while these
six research-frontier checks honestly remain incomplete.
