# GW4 deeper-search audit — 9 September 2026

## Purpose and predeclared comparison

The user requested materially deeper weekly optimisation, not merely more simulation samples for
the old shortlist. This audit leaves the football forecasts, market/role authority, transfer rules,
0.88 horizon decay and 0.25 worst-world protection unchanged. It tests whether a wider legal roster
search and stronger use of each roster change the decision on the same current evidence.

The preceding ordinary run considered 16 distinct roll/transfer actions. It published Richarlison →
Evanilson, Bruno captain, Szoboszlai vice, no chip, with a 3-4-3 projected for 53.87 GW4 points.
This is the incumbent comparator, not a guarantee or a target to beat by changing the forecasts.

The implemented protocol in `weekly_deep_search.py` is fixed before viewing the validation results:

1. Reproduce legal roster shortlists at **4, 8, 16 and 32** alternatives per transfer count, including
   the existing protected routes that sell a severe retained role risk. At this deadline the manager
   has one FT; the configured two-paid-transfer limit permits up to three current moves. Every
   requested solver result must be optimal or proven infeasible; a timeout is not “nothing better”.
2. Generate **25,000 residual and 25,000 component selection paths** over GW4–8. Raw and anchored
   component scoring use the same component samples; they are not independent extra paths.
3. Enumerate **all 550 legal XIs and six bench orders** for every retained roster at every horizon
   event. Consider every ordered captain/vice pair among the XI: **363,000 possible configurations
   per roster/event** before exact mean-dominance pruning.
4. Retain each event's non-dominated three-world configuration frontier. Jointly optimise the
   Cartesian product of the five event frontiers with a MILP for the declared mean/regret criterion;
   do not greedily choose five unrelated single-event regret winners. Include weighted-mean and
   individual-world leaders as additional policies, and preserve the original proposals.
5. Improve the roll comparator on selection data too, so transfers do not win by competing with
   an unnecessarily poor unchanged-squad lineup. Freeze the comparator and proposed winner.
6. Test the frozen policies in **two additional independent samples**, each containing 25,000 paths
   per simulation family. Validation may accept or reject the frozen selection; a holdout winner
   cannot replace it retrospectively.

Selection seeds: 202609091/202609092. Validation seeds: 202609093/202609094 and
202609095/202609096. The coefficient is not retuned across those samples.

Acceptance requires both samples to pass: the selected policy clears the existing action/role
gates, is within 0.05 horizon regret points of the holdout leader, loses no more than 0.05 mean points
in any model world against the incumbent, and has positive conservative paired weighted lower
confidence bound against that incumbent (or is exactly unchanged). Raw/anchored uncertainty is not
combined as though those samples were independent. These are Monte Carlo precision checks, not
confidence intervals covering all football-model error.

## Exact scoring and practical computation

`exact_configuration.py` groups samples by their 15-player appearance bitmask. For each group it
retains the conditional **sum of player points**, preserving correlations and negative returns.
It evaluates legal autosubs for every XI/bench order. Captain and fallback bonuses can be added
exactly to that lineup score without simulating the match afresh for each captain pair.

A bench order or captain pair is pruned only when another choice is at least as good in every
model world's mean. Adding the same remaining component cannot reverse that dominance. Integer
sample totals are retained until pruning finishes: tiny floating summation differences must not
turn mathematical ties into fictitious superior configurations.

This is exact pruning for the monotone **mean/regret** objective. It does not establish exhaustive
CVaR, beat-roll probability or every safety-constrained configuration optimum: two configurations
can have similar means but different distributions. The surviving policies still receive full
per-path scoring and the existing paid-hit gates. “Every possible configuration” is a description
of the configuration space and the lossless mean-dominance treatment, not a claim that every
configuration was separately evaluated against every individual simulated path.

The CUDA implementation computes the legal autosub weights as well as point arithmetic, avoiding
the old CPU construction of huge per-sample weight tensors followed by a small GPU multiplication.
There is a CPU reference implementation. GPU work remains subject to memory and other workloads;
the audit does not terminate unrelated applications to claim full hardware utilisation.

## Validation before the real-data run

- CUDA per-path scores equal the original CPU reference on all **32,768 appearance masks**, four
  representative legal XIs and all six bench orders for each, including negative returns and
  captain/vice fallback.
- Future-event squad changes and a differently ordered global player pool match the reference.
- The three-world Pareto routine matches brute-force dominance, including duplicate vectors.
- The factorised configuration frontier matches exhaustive Cartesian scoring on smaller fixtures.
- The joint multi-event MILP matches brute-force enumeration of a small full horizon product.
- Configured actions preserve exact legal transfer cost, bank/FT state and projected-utility fields.
- Gate tests ensure a failing holdout cannot supply a replacement winner, even when its favourite
  would look attractive after observing that sample.
- An execution-order test caught a HiGHS global-thread-scheduler mismatch. The first research run
  was stopped before reaching that stage, marked interrupted, and retained. The corrected solver
  respects the already initialised scheduler; the rerun uses a new output path.

## Scope and limits

This is a deeper **current-transfer / fixed-roster-horizon** search, not a complete adaptive policy
over every future injury, price move and transfer sequence. The four-to-32 roster sweep is wider,
but remains a screening shortlist from the existing forecast objective. The joint configuration
solve is optimal for its finite frontiers and declared reference; it is not a theorem that the
entire safety-gated, season-long FPL problem has been solved globally.

Independent simulation seeds test selection noise under fixed current models. They are not new
historical seasons or prospective football outcomes, and cannot prove the forecast models correct.
No old season is scored using today's fitted model and called a clean historical validation.
Current-version adaptive planners and unvalidated WC/FH timing remain rejected for live authority.

The audit checks input and implementation hashes before and after execution and writes an explicit
failed/interrupted status on errors. Nothing is written to FPL. Current recommendation publication
must use the normal transactional deadline gates, not a direct rewrite of the active squad file.

## Run evidence

The first interrupted receipt is retained at
`data/research/weekly-deep-search/20260909-gw4-v1/results.json`.
The corrected run writes
`data/research/weekly-deep-search/20260909-gw4-v2/results.json`.
The corrected run **completed in 629.27 seconds (10 minutes 29 seconds)**. Captured input and
implementation hashes remained unchanged throughout it. The original interruption is not counted
as a completed experiment or used for policy selection.

| Shortlist depth per transfer count | Distinct legal routes | Winner before full configuration expansion |
| --- | ---: | --- |
| 4 | 16 | Richarlison → Evanilson |
| 8 | 30 | Richarlison → Evanilson |
| 16 | 51 | Richarlison → Evanilson |
| 32 | 100 | Richarlison → Evanilson |

The 100 rosters over five events cover a **181,500,000-configuration space** before lossless
mean-dominance pruning. This is not 181.5 million unrelated squads or individually sampled
football futures. Each roster/event retained between 2 and 28 non-dominated configurations.
The horizon MILPs and supplementary mean/world policies produced **540 distinct frozen policies**.
All 540 were retained for both validation batches, not just a favoured final pair.

The expanded selection chose `D-3aede4fe9c097090`: **Richarlison → Gonzalo**, retaining one transfer,
with a 3-5-2, Bruno captain and Szoboszlai vice. Gonzalo would be first substitute in GW4 while
Mbeumo starts. The unadjusted current-GW forecast for that XI was 53.62, versus the incumbent's
53.87. These display forecasts are not the simulated, discounted five-week comparison below.

### Acceptance result: reject the challenger; retain the published recommendation

| Paired GW4–8 mean change against the incumbent | Holdout 1 | Holdout 2 |
| --- | ---: | ---: |
| Residual world (50% weight) | −0.329 | −0.351 |
| Anchored component world (45% weight) | −0.343 | −0.416 |
| Raw component world (5% weight) | +1.388 | +1.209 |
| Weighted mean change | **−0.249** | **−0.302** |
| Conservative weighted Monte Carlo 95% lower bound | −0.333 | −0.385 |

Both holdouts independently selected the same Gonzalo configuration under the unchanged minimax
criterion, with zero holdout regret to their leader. It also cleared the existing transfer and role
safety gates. **It nevertheless failed both predeclared promotion checks against the incumbent:**
no material mean loss in any world, and a positive paired weighted lower bound. Therefore it is
rejected, not promoted simply because a longer run found it.

This is not evidence that the deeper configuration algorithm is broken or that more search has no
value. The minimax term can sacrifice weighted mean points to reduce the largest world-specific
regret, even when that world has only 5% weight in the mean. The broader configuration pool changes
the attainable reference points. The external acceptance criterion deliberately requires stronger
evidence before replacing the incumbent. This observed disagreement is a reason to investigate the
**decision objective**, not to quietly lower the acceptance bar or tune its coefficient on these
holdouts. No other challenger is selected retrospectively using the same holdout results.

### What is active in the application

The normal app still publishes the existing validated weekly policy. The new deep-audit command is
implemented and reusable, but **is not silently inserted as a replacement selector in every app
refresh**. No new transfer, formation, captain, bench order or chip instruction was published by
this audit. App API verification after the run returned the same successful published refresh:

- Run: `refresh-v1-f98e6b71c4212a2c`, completed 9 September at **14:52:59 BST**.
- Action: `A-5329ac8f23-1`, Richarlison → Evanilson; one FT, no hit, no chip.
- XI 3-4-3: Verbruggen; Truffert, Tarkowski, António Silva; Bruno Fernandes (C), Szoboszlai (VC),
  Semenyo, Gibbs-White; Evanilson, Igor Thiago, Calvert-Lewin.
- Bench: Mbeumo, N. Williams, Maguire; Donnarumma as reserve goalkeeper.
- Current-GW displayed projection: **53.8743** including captaincy.
- Active receipt and immutable archive SHA-256:
  `cc14d4ea02e7798e2703ad70f0d29989f5589b60dcfdff3246b3e69da069478d`.
- Archive:
  `data/decisions/weekly/event-4/8919a89d53893214a8b77c4500c7fd0bd0fa817575395cbf76361b450f79d019.json`.

No FPL account writes, LLM runs, commits or pushes were performed. The app, MCP and frontend remain
available; unrelated GPU workloads were not stopped. Nothing here converts the held-out simulated
numbers into measured season points or a claim of being the world's best model.

### Follow-through and highest-value remaining work

1. Compare **weighted-points versus minimax policy selection** on genuinely point-in-time rolling
   historical decisions, with a frozen latest-season test and prospective current-season receipts.
   Use this run to identify the hypothesis, not to select a new risk coefficient. The earlier two
   observed current-season decisions are insufficient evidence for retuning.
2. Improve **adaptive future-transfer recourse** and validate it on the same initial squads and
   legal FT/price/chip state. The present five-week fixed-roster surrogate still undervalues the
   ability to repair a future weakness; increasing its configuration count does not solve that.
   The earlier adaptive variant remains rejected because it failed its historical screen.
3. Only then enable a reviewed, transactional deep-search policy in routine refreshes, with
   per-run frozen selection/holdout receipts, explicit progress and the existing deadline gates.
   The current audit is callable now; its rejected result does not establish deployment merit.

After the measured run, the audit harness was further hardened to hash its historical calibration
inputs, rules files and active-receipt pointer as well as the previously recorded current artifacts.
An optional non-persisting goal-rate prediction path prevents future research runs from rewriting
the derived goal-rate artifact; a regression proves identical predictions to the existing default
production path. These provenance/I/O changes do not change the recorded experiment's selector or
numerical algorithm. Its original receipt remains intact with its original implementation hash.

### Final verification

- **665 non-LLM Python tests passed**, including 18 targeted exact-scoring/deep-search/path tests.
- **Six frontend tests passed** and the TypeScript/production build succeeded. The pre-existing
  bundle-size warning remains; the Python suite reports the existing Starlette/httpx deprecation.
- CPU and CUDA configuration frontiers both match exhaustive reference scores, including unequal
  sample counts between the three model worlds.
- New engine, audit-script and test files pass Ruff. Changed tracked implementation/docs files
  pass the scoped whitespace check; repository-wide checking still reports pre-existing Markdown
  hard-break whitespace in unrelated generated reports, which this task did not rewrite.
- Live API returns a ready GW4 workspace with the exact incumbent action and receipt hash; the
  immutable archive matches the active bytes. No app recommendation was replaced by research.

Reproduction (choose a fresh output path):

```bash
.venv/bin/python -u scripts/audit_weekly_deep_search.py \
  --output data/research/weekly-deep-search/new-audit/results.json

.venv/bin/pytest -q tests/test_engine_exact_configuration.py \
  tests/test_engine_weekly_deep_search.py tests/test_engine_weekly_simulation.py
```
