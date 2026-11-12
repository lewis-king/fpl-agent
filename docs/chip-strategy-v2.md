# Season-long chip strategy v2

**Status:** All four chips are now used before expiry. Bench Boost and Triple Captain timing
stays behind live uncertainty and historical gates; Wildcard timing comes from the live full-half
planner; Free Hit uses the joint calendar and uncertainty gates; an expiry rule guarantees that no
chip is lost  
**Updated:** 6 November 2026

## Use every chip before it expires — 6 November 2026

Each half's chips (GW1–19, GW20–38) expire at the half's last deadline. The blanket "no WC/FH
authority" rule meant the app could never recommend either, so both would have expired unused.

- **Expiry guarantee** (`chip_strategy.synthesize_joint_chip_strategy`): when the chips left fill
  every remaining week (`chips ≥ half_end − event + 1`), the best-valued current chip is played
  even if its uncertainty gates fail. `expiry_forced` and the reason record this.
- **Wildcard timing** (`chip_timing.py`): after each publication, if the squad has no fresh
  receipt (same event and squad fingerprint, under 12 hours old), the pipeline runs the adaptive
  planner on the published decision. Every ordinary first move and the published route get a
  Wildcard in each later week, plus a Wildcard now, with transfers replanned every week to the half's
  expiry. All branches share the same simulated outcomes, selected on 10k draws and checked on 20k
  holdout draws. A second pipeline pass on the same official snapshot then re-decides with the verdict.
  Wildcard now needs: best play-now holdout mean − best later-Wildcard mean > the waiting margin,
  and non-overlapping paired 95% intervals. The waiting margin is 2 points, or 4 points when the
  next deadline is ≥10 days away (international break). This is an explicit, **unvalidated**
  prior for the value of seeing more news, because the planner sees no news between deadlines.
- **Free Hit** needs positive joint value, positive in every model world, a paired 95% lower bound
  above zero and schedule fit; historical authority is no longer required.
- **Dated plan:** `chip_strategy.deadline_plan` gives each unused chip a planned week and a latest
  safe week. The CLI prints it under CHIP STRATEGY, and the web panel lists it.
- **Execution:** `weekly_configuration._squad_chip_execution_plan` binds a recommended WC/FH to its
  own squad, XI, bench and captaincy. The view adds squad-chip deltas to the ordinary route's
  metrics. `policy_release` still refuses WC/FH without a play-now verdict or the expiry rule.

GW10 2026/27 was the first live case: the planner preferred Wildcard now by +3.1 points over GW11
(paired interval separated). It **held** because GW11 comes after the international break, which
needs a 4-point margin. Lewis chose the same independently. Receipt:
`data/decisions/chip-timing-current.json`; research run
`data/research/wildcard-timing-20261106-gw10`.

Limits: residual simulation family only; GW15–19 use frozen-ability fixture extrapolation; the
waiting margin is a prior, not a fitted value; historical WC-now replays (0 and −34 points vs later)
remain the reason this is a margin-gated rule rather than raw argmax.

The [round-two audit](../reports/points-first-validation-round2-2026-09-09.md) adds an exact
two-deadline shared-world research frontier and tests all eight chip transitions through each of
two complete historical seasons. It verifies mechanics, including WC→BB and Free Hit restoration,
but does not validate optimal timing or grant WC/FH authority. Its precommitted exercise calendar
is a test fixture, not the app's suggested chip schedule.

## Decision objective

The chip engine maximises expected **net FPL points**, not chip points in isolation, team value,
popularity or the chance of a spectacular single Gameweek. Every deadline asks one question:

> Is using one chip now worth more than the strongest legal allocation of every remaining chip
> before this half-season's expiry?

That is materially different from a fixed rule such as “Triple Captain above 6 xP”. Four chips
share the same calendar, only one can occupy a Gameweek, and a Wildcard changes the squad on which
later Bench Boost and captain decisions depend.

## Exact 2026/27 mechanics

The manager state contains eight independent chip slots: WC, FH, BB and TC in each half. The first
set expires after GW19 and the second unlocks in GW20. The transition engine enforces one chip per
Gameweek, the GW1 WC/FH restriction, the consecutive Free Hit restriction, exact chip consumption,
Free Hit squad restoration, permanent Wildcard squads, exact bank/selling prices, transfer hits and
preserved banked transfers.

Rule sources: [Premier League 2026/27 chip changes](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627)
and the [official FPL FAQ](https://www.premierleague.com/en/news/4661030).

An unavailable, played, locked or expired chip is never offered to the policy. Missing schedule
history is represented as unknown; it is never converted into an ordinary single-fixture week.

The weekly refresh also supports planning while the preceding Gameweek is live. Only final,
data-checked event history enters rolling model features. During live play that finalized history is
validated as a prefix of FPL's provisional cumulative totals; partial current-event points are not
mistaken for missing history or admitted as finalized training targets.

The authenticated manager state has a separate deadline-boundary rule. A decision for GW *n* may
only use a manager snapshot captured at or after the GW *n-1* deadline. This prevents a squad,
free-transfer count, transfer cost or chip inventory from the preceding Gameweek being silently
relabelled as next-Gameweek state. A stale snapshot blocks publication, the evidence receipt, and
the visible web recommendation until FPL is reconnected.

## Joint retained-value calendar

The old implementation compared chips independently and demanded live forecasts all the way to
GW19/GW38. Early in a half this made authority impossible. Version 2 replaces that with a finite
horizon plus an empirical terminal value:

1. Exact shared-world simulations estimate every legal current transfer-plus-chip branch against
   the strongest no-chip transfer route. A chip is therefore allowed to change the optimal transfer
   plan; it is not merely bolted onto the ordinary recommendation.
2. Each forced branch supplies its own future squad and visible BB/TC opportunities. Wildcard
   changes persist through that calendar, while Free Hit restores the pre-chip squad before the
   following event. The no-chip branch uses the selected ordinary route.
3. A dynamic programme assigns at most one chip to each visible event and at most one use of each
   available chip.
4. For the period beyond the reliable forecast horizon, an event-distance-specific retained value
   prices the best later opportunity seen historically.
5. At expiry that retained value is exactly zero. With several unused chips late in a half, the
   one-chip-per-GW constraint forces the planner to start allocating them before the last deadline.

For each possible current chip, the engine solves the calendar twice: once while retaining every
chip, and once with that chip forced now. Their difference is `joint_net_value`.

## Historical calibration and recency

Calibration uses the three recent complete point-in-time forecast seasons: 2023/24, 2024/25 and
2025/26. The newest season shares the current two-of-each half-season inventory; that inventory is
applied counterfactually to the two older seasons. Their exponential half-life is 1.25 seasons,
producing weights of approximately 17.3%,
30.2% and 52.5%. Pandemic seasons are excluded from the timing prior because their postponement
process and rule environment are not representative. Recent data therefore drives the level while
the two preceding seasons stabilize the tails.

For every deadline, chip and half, the training target is the best **later forecast-visible**
opportunity before expiry—not the later realised points. The terminal value is learned separately
for every exact number of events remaining, with broader early/middle/late bands retained only for
reporting. This prevents the GW19/GW38 leakage where a coarse “late” bucket could incorrectly leave
positive value after expiry.

Validation is now strictly forward-only (expanding window). The 2023/24 season initializes the
policy; 2024/25 is tested using 2023/24, and 2025/26 using the two earlier seasons. Previously the
older folds incorrectly used future seasons despite rolling-origin wording elsewhere. Old receipts
without a passing forward-only contract cannot grant live authority. Promotion requires:

- all three recent seasons to be complete;
- positive realised chip points on every held-out season;
- exactly one BB and TC allocation in each counterfactual half;
- at least 85% of the offline forecast-oracle opportunity on every held-out season; and
- at least 75% of forecast-oracle realised chip points on untouched 2025/26.

The frozen 2025/26 result is 17 realised chip points versus 21 for the offline forecast-oracle
comparator (80.95%), while capturing 93.54% of its forecast opportunity. The comparator may inspect
all deadline forecasts after the season only; it cannot inspect realised points and never enters
the live policy.

The corrected 2024/25 test scores 34 actual chip points versus 17 for that forecast-based offline
comparator, capturing 91.54% of its forecast opportunity. This is a single replay path, not a
population-level treatment effect. Positive chip points alone are a weak benchmark; matched
full-season no-chip/alternative-timing policies and more prospective outcomes remain necessary.
The calibration now preserves its opportunity paths to make the fold construction inspectable.

Calibration lineage hashes the exact historical values consumed by the replay rather than the
physical bytes of the mixed historical/live feature Parquet. A normal weekly refresh can therefore
rewrite current-season rows without disabling chip advice, while any change to a historical
forecast, target point, target minute, price or player identity still invalidates the calibration.

As an external behavioural sanity check, the receipt also records all 56 chip uses by seven tracked
strong managers in 2025/26. Their timings are descriptive only: they cannot train the trigger or
open a promotion gate because manager behaviour is not a causal label for maximum points.

These tests support BB/TC timing authority under additional live gates. They do not prove that the
system is globally state of the art; that requires more prospective 2026/27 outcomes and a matched
external benchmark.

## Live promotion gates

A positive mean is insufficient. A current BB or TC recommendation must satisfy all of:

- positive joint value after the collision-aware retained calendar;
- positive uplift in every residual/component model world;
- a paired 95% lower bound above the retain-calendar value;
- confirmed, chip-appropriate current scheduling; and
- a passing recent-season historical timing gate.

Free Hit is **not** hard-excluded from normal single-fixture weeks; blank/double preference is a
strategy consideration, not an extra legality rule. WC and FH already receive exact
legal squad searches and shared simulations, but stay advisory because the old event-level
retained-value replay failed its declared downside bound. The engine reports their upside and why
they are blocked instead of silently pretending confidence.

## Product surface and receipts

Every weekly receipt now contains `chip_strategy` with:

- the operational call and exact action ID, if promoted;
- all available chips and the current half's expiry;
- current candidates, joint net value, paired downside and failed checks;
- the collision-free retained calendar;
- visible BB/TC opportunities and fixture-rearrangement watches; and
- checksum-bound calibration lineage and recency weights.

The weekly web panel shows the call, expiry countdown and next opportunities. “Save chips” is no
longer a generic hard-coded message: it is the result of the joint policy and includes its blockers.
Its expanded panel distinguishes an evaluated retain/play call, research-only WC/FH branches,
missing evidence and an unevaluated branch. A positive research-only value does not authorize play.

After an event is officially final and data-checked, prospective scoring records the realised
immediate uplift of every frozen BB/TC branch and every scorable WC/FH squad branch—even when the
decision was to hold. A Wildcard is not judged on one Gameweek: its persistent value remains open
until the later archived manager-state path can be scored. This prevents noisy one-week outcomes
from becoming false training labels.

## Reproduction

```bash
.venv/bin/fplagent calibrate-chip-strategy
```

Outputs:

- `data/model/chip_strategy_v2/retained-value.json`
- `reports/chip-strategy-v2.md`

Core implementation:

- `src/fplagent_engine/chip_strategy.py`
- `src/fplagent_engine/weekly_decision.py`
- `src/fplagent_engine/manager_state_store.py`
- `src/fplagent_engine/deadline_evidence.py`
- `src/fplagent_engine/season_state.py`
- `src/fplagent_web/workspace.py`
- `web/src/components/WeeklyDecisionPanel.tsx`
- `tests/test_engine_chip_strategy.py`

## Next evidence milestones

The first priority is prospective scoring of every 2026/27 chip opportunity, including decisions to
hold. WC/FH authority needs an event-level causal replay that compares persistent future manager
states, not merely current-horizon xP. The scheduler must then add probabilistic rearrangement trees
when enough independent announcement batches exist. These are explicit promotion requirements, not
features assumed to be solved.

## Adaptive Wildcard timing audit — 22 October 2026

`wildcard_timing.py` adds a **research comparison**, not new automatic chip authority.
The earlier five-week fixed-roster comparison and scalar retained-chip prior cannot establish
that paying a hit is better than Wildcard now. The new experiment compares fixed first actions
with a Wildcard in every remaining first-half event and ordinary transfers replanned at every
deadline. The current implementation is deliberately bounded, not globally optimal.

```bash
# A new directory is required; nothing overwrites the live workspace.
.venv/bin/python scripts/research_wildcard_timing.py \
  --output data/research/my-wildcard-audit --end-event 19 --samples 10000

# Stronger root screen: a transfer before WC9 is bought for GW8, not five weeks.
.venv/bin/python scripts/research_wildcard_timing.py \
  --snapshot data/research/my-wildcard-audit \
  --output data/research/my-wildcard-aware-roots --wc-aware-roots

# Add exact BB/TC date selection conditional on the saved transfer paths.
.venv/bin/python scripts/score_wildcard_team_chips.py data/research/my-wildcard-audit

# Same frozen inputs, but stress United's point forecasts by 20%.
.venv/bin/python scripts/research_wildcard_timing.py \
  --snapshot data/research/my-wildcard-audit \
  --output data/research/my-wildcard-united-stress --united-multiplier 0.8

# Alternatively reveal the stress only at a FUTURE deadline; earlier actions
# must not depend on it. These are sensitivity cases, not fitted probabilities.
.venv/bin/python scripts/research_wildcard_timing.py \
  --snapshot data/research/my-wildcard-audit \
  --output data/research/my-wildcard-news-stress \
  --united-multiplier 0.8 --shock-event 10

# Freeze the ORIGINAL selected root/date before evaluating later surprise news.
# Do not act on the news scenario's best-in-hindsight selected_group.
.venv/bin/python scripts/audit_wildcard_news.py \
  data/research/my-wildcard-audit data/research/my-wildcard-news-stress

# Two recent-season, chronological development comparisons.
.venv/bin/python scripts/replay_wildcard_timing.py \
  --output data/research/my-wildcard-historical
```

### What is accounted for

- Frozen published forecast, fixtures and authenticated manager contract, with content hashes.
- Exact purchase/selling prices, integer-tenths bank, hits, free-transfer carry and chip expiry.
- Root branches for rolling, free/paid moves, the exact published move, and Wildcards retaining
  both/one/neither of Bruno and Mbeumo. Player IDs are resolved from the current catalogue.
- Every future deadline replans legal transfers; it is not a frozen 15-player projection.
- A later Wildcard limits pre-Wildcard transfer planning to the intervening deadlines.
- Future information is visible only from its declared deadline; future actual points are
  forbidden in planner inputs. Plans are chosen before validation draws are opened.
- Paired residual-world evaluation, exact legal autosubs and C/VC fallback, undiscounted net
  points to the end of the half, no invented terminal FT/chip credit. Planning still uses the
  incumbent five-event/0.88 screening objective, including its 0.08 bench approximation.
- BB/TC marginal gains are measured against points already received through autosubs. Dates
  cannot collide with each other or Wildcard, and the final ledger is re-applied legally.

### What this does NOT establish

The directly generated live forecasts end at GW12 in this audit. GW13–19 are labelled fixture-
normalised extrapolations of frozen player ability using historical incumbent fixture response;
they are not fresh bookmaker forecasts, predicted recovery dates or known future lineups.
This auxiliary response uses venue and official fixture-difficulty values; it is not a rebuilt
long-horizon version of the production team-strength/market forecast.
No `ep_next` is used. Flat prices are the baseline, not a price prediction. Price shocks are
supported at the information boundary but have no fitted probability distribution here.

The simulator is one residual family, not three independently calibrated forecasting models.
Monte Carlo confidence intervals describe numerical sampling precision; actual score variance
and structural forecast error are different uncertainties. The calendar extension chooses BB/TC
dates **conditional on transfer paths**, not chip-preparation transfers jointly. Free Hit timing,
fixture-rearrangement probabilities and learned future-news transitions remain missing.

The historical script starts from one common GW1 policy, branches at GW8 and scores GW8–19
using dated forecasts/prices at each deadline. Calibration uses earlier seasons only. The
2024/25 and 2025/26 seasons have been reused during development and are not pristine holdouts;
their original scoring is retained while today's chip/FT mechanics are applied counterfactually.
Blank holdings are reconstructed only through the explicit as-of catalogue/fixture certificate.

For future-news sensitivities, individual deadline actions obey non-anticipation, but choosing
the best origin policy specifically for that one assumed news path is an oracle comparison.
Use `audit_wildcard_news.py` to carry the unchanged-origin choices into the news scenario and
verify their pre-news ledgers match. The scenario's conditional `selected_group` must not be
mistaken for a deployable choice made before the news arrived.

### Deployment decision

Retain the research evaluator and its audit trails. **Do not promote Wildcard timing yet.**
The initial live experiment favours Wildcard now, but the recent-season comparisons did not
demonstrate better realised performance. See `reports/wildcard-timing-audit-2026-10-22.md` for
the actual results and remaining promotion work. WC/FH authority remains unchanged.

The app and CLI must distinguish a positive unvalidated chip alternative from a proven decision
to retain. A positive research-only/needs-review chip route is now labelled **unresolved**; the
ordinary transfer recommendation is explicitly conditional on not using the chip. This display
correction does not rewrite the published squad or submit anything to FPL.
