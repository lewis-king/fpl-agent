# Wildcard, Free Hit and retained-chip decision shadow

**Status:** superseded retained-value design; WC/FH exact branches remain advisory
**Updated:** 30 August 2026

> Version 2 now solves the four-chip calendar jointly and has promoted BB/TC timing behind strict
> live uncertainty gates. See [Season-long chip strategy v2](chip-strategy-v2.md). The document
> below is retained as the audit trail for the original shadow implementation and its rejected
> gates.

FPLAgent can now generate and simulate legal Wildcard and Free Hit counterfactuals alongside roll,
ordinary-transfer and hit routes. This closes the squad-search gap; it does not yet mean the engine
knows when spending either chip is better than retaining it.

## Wildcard search

The Wildcard solver searches the full eligible player pool under the manager's exact bank plus the
current selling value of every holding. It enforces the 15-player positional structure, team-value
constraint, three-player club limit and a legal XI/captain for every event in the current horizon.

The chosen squad is permanent. The state transition:

- charges no transfer points;
- consumes the correct half-season Wildcard;
- preserves the free-transfer balance entering the Gameweek;
- carries the new squad and remaining bank into the next manager state; and
- reoptimises XI, bench order, captain and vice-captain in every simulated event.

## Free Hit search

The Free Hit solver separately optimises a fresh legal squad for the current event only. Its budget
is the exact bank plus current selling values, and it can replace any number of players without a
hit.

From the following event onward, every simulation explicitly switches back to the original
15-player squad. The original bank and entering free-transfer balance are restored, while the chip
is consumed. Gameweek 1 and consecutive Free Hits—including GW19 followed by GW20—are rejected.

The event-by-event squad mapping is carried into the shared residual and component simulations.
This matters in doubles and blanks: match-scoped component outcomes are aggregated into each event,
but a temporary Free Hit player cannot leak into later gameweeks.

## What the receipt reports

Each WC/FH candidate includes:

- all transfers and the exact post-chip bank;
- the selected 15, XI, bench, captain and vice-captain;
- the squad used in every event of the horizon;
- shared-world raw points delta against the strongest weighted ordinary action;
- model-world downside and a paired confidence interval; and
- schedule completeness, horizon coverage and retention-calibration checks.

The best raw candidate is useful as a structural diagnostic—for example, it can show how much a
confirmed blank/double would reward a Free Hit, or how much forecast decay exists across the current
squad. It remains `operational_recommendation: no_chip` and `decision_authority: false`.

## Why the engine still retains the chip

Raw current-horizon gain is not the opportunity cost of a chip. A correct decision also needs the
distribution of credible later uses before the chip expires. That requires point-in-time historical
and prospective schedule states, including what rearrangements were actually known before each
deadline.

Promotion therefore requires:

1. confirmed or explicitly modelled schedule coverage with no speculative double treated as fact;
2. a retained-chip value learned only from later opportunities that were knowable at the time;
3. separate policy replay for ordinary weeks, blanks and doubles;
4. stable gain across residual and match-component simulations;
5. legal continuous-season state, including later bank, transfers and the other chips; and
6. positive net FPL points with a defensible downside bound on untouched seasons and prospective
   receipts.

The first calibration now exists, and it was rejected. The subsystem can answer “what would this
chip do now?” but it still cannot authoritatively answer “is now the best time in the half-season to
spend it?”.

## Historical schedule foundation

The first retained-value input is now built from the archived Git fixture snapshot selected before
each historical deadline. It contains 1,771 decision/future-event rows across 83 snapshots:

- 37 decision snapshots in 2023/24;
- 35 in 2024/25; and
- 11 in the currently available 2025/26 archive.

Every row records the blank, double and triple-plus teams, unassigned fixtures, provisional times,
lead in gameweeks and whether the opportunity falls before the current 2026/27 half-season expiry
boundary. It never backfills a later final rearrangement into an earlier decision. This ledger is
ready evidence, not yet a retained-points model; historic seasons did not necessarily share the
current eight-chip inventory.

## Probabilistic rearrangement shadow

The engine reconstructs each historical unassigned-to-assigned fixture transition without using a
later schedule at an earlier deadline. Rearrangements announced together are treated as one
correlated batch rather than several independent observations. The empirical support over
resolution delay and assignment lead time then drives a current Monte Carlo shadow for every still
unassigned match, producing blank/single/double/triple team-event probabilities beside the official
schedule.

This model found 17 historical episodes, 16 resolved, but only nine independent resolution batches
across two seasons. Its frozen minimum is 20 batches across three seasons, so the gate correctly
fails. The probabilities are diagnostic only: the official assigned schedule remains the sole
confirmed input and unresolved scheduling still blocks chip authority.

## Continuous WC/FH replay result

The replay follows one legal manager state through all 38 deadlines: squad, bank, purchase and
selling prices, carried free transfers, hits, chip inventory and Free Hit restoration. It selects a
trigger on 2023/24 and freezes it before the untouched 2024/25 path. Forecasts and schedule state are
only those visible at each deadline.

The selected policy gained 58 net points in selection and 79 in the untouched test, but its frozen
four-Gameweek downside interval was −1.053 to +5.474 points per Gameweek. That misses the declared
−0.25 lower-bound gate, so the receipt verdict is `REJECT` and its thresholds do not enter live
decisions.

## Bench Boost and Triple Captain timing result

The same continuous ordinary-transfer path now scores exact Bench Boost and Triple Captain uplift.
Bench Boost scores all 15 plus ordinary captaincy; Triple Captain includes the third captain copy
and exact vice-captain fallback. One copy of each chip is available in each current-rule half and no
two chips can be used in the same Gameweek.

The trigger pair is selected on 2023/24 and tested untouched on 2024/25. It gained 40 and 24 points
respectively. A stronger offline comparator retains each chip for the best forecast-visible,
distinct opportunity in its half; the frozen test policy finished two points above that comparator
in total, but the four-Gameweek timing-regret interval was −0.474 to +0.711 points per Gameweek. It
misses the −0.25 safety bound and is therefore also `REJECT`, with zero authority. The oracle uses
later deadlines only as an offline upper-bound comparator and never as a live input.

Both rejected receipts are checksum-bound into weekly decision lineage. The next chip milestone is
not to weaken their gates: it is to improve the retained-timing policies, accumulate prospective
2026/27 receipts, and replay all four chip types jointly because spending one removes that
Gameweek—and possibly the best squad state—from the others.

## Reproduce the evidence

```bash
.venv/bin/fplagent build-rearrangement-model
.venv/bin/fplagent replay-squad-chips
.venv/bin/fplagent replay-team-chips
```

The frozen outputs are:

- `data/model/schedule_rearrangement_v1/model.json` and `episodes.parquet`;
- `data/model/squad_chip_replay_v1/results.json` and
  `reports/squad-chip-retention-replay.md`; and
- `data/model/team_chip_replay_v1/results.json` and
  `reports/team-chip-retention-replay.md`.

Implementation:

- `src/fplagent_engine/weekly_actions.py`
- `src/fplagent_engine/weekly_simulation.py`
- `src/fplagent_engine/weekly_decision.py`
- `src/fplagent_engine/season_state.py`
- `src/fplagent_engine/chip_schedule_history.py`
- `src/fplagent_engine/schedule_rearrangement.py`
- `src/fplagent_engine/squad_chip_replay.py`
- `src/fplagent_engine/team_chip_replay.py`
- `tests/test_engine_weekly_actions.py`
- `tests/test_engine_weekly_simulation.py`
- `tests/test_engine_weekly_decision.py`
- `tests/test_engine_season_state.py`
- `tests/test_engine_chip_schedule_history.py`
- `tests/test_engine_schedule_rearrangement.py`
- `tests/test_engine_squad_chip_replay.py`
- `tests/test_engine_team_chip_replay.py`
