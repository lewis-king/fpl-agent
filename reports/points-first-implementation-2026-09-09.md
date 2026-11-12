# Points-first implementation and validation — 9 September 2026

The [ordered improvement programme](../docs/decision-improvement-roadmap-2026-09-09.md) separates
completed corrections from research that still needs to establish points lift. This iteration does
not establish SOTA performance, and does not claim to have completed all six research priorities.

## Published GW4 result

The standard API-driven refresh completed all five stages in **107.1 seconds**, publishing at
**12:11:21 BST on 9 September**. It retained the same player move and lineup as the morning run:

- Richarlison → Evanilson; one free transfer, no hit; one FT available next deadline.
- Bruno Fernandes captain; Szoboszlai vice-captain; no chip.
- GW4 projection: **53.8879** points, including captaincy.
- Weighted five-event simulated gain over roll: **+2.1872**; worst model-world mean: **+0.9703**.
- The robust preference accepts **0.2779** fewer weighted model points than the highest-mean
  admissible route. Safety-gate exclusions contribute no additional mean sacrifice on this run.

These are model estimates, not promised gains. The interval +2.164 to +2.307 is a residual-world
Monte Carlo interval around that world's mean, not an interval for the weighted estimate or the
actual football outcome. The app now makes this distinction explicit.

Persistence proof:

- Run: `refresh-v1-296e5c9644a32871`.
- Input fingerprint: `4ec1b0034aa321ab83828ca445a09d54cb9c249d1e31234970309e60cfb3eb9e`.
- Active receipt: `data/decisions/2026-27-weekly-current.json`.
- Immutable archive: `data/decisions/weekly/event-4/4ec1b0034aa321ab83828ca445a09d54cb9c249d1e31234970309e60cfb3eb9e.json`.
- Active/archive byte equality verified; decision SHA-256:
  `ce971efa008cc17a21f2f28dbe1ae375a23a3d54741da558ca9ba8bd3294c8fd`.
- Published implementation fingerprint matches the deployed engine code.

All deadline evidence gates passed. The manager state is derived from the existing authenticated
07:11 UTC snapshot; fresh public evidence was collected at 11:09 UTC. No FPL account mutation was
performed. The API and MCP remain running; browser address is `http://localhost:5173`.

## What changed operationally

1. Select the highest-ranked admissible ordinary action instead of skipping all alternatives when
   the leader fails. Every rejection is recorded, including incoming-player role checks.
2. Correct chip validation to expanding-window, forward-only folds; reject missing/duplicate seasons
   or incomplete event paths. A legacy or failed validation receipt cannot grant authority.
3. Remove the strategy-only restriction against normal-week Free Hits. Other legality/evidence
   checks remain. BB/TC retain live eligibility; WC/FH are still research-only.
4. Bind weekly cache reuse to engine implementation, so fixes are not masked by a recent run.
5. Freeze **654 current-event forecasts**, compared with the **36 players** in tested candidate
   squads. Prospective scoring now distinguishes selected/omitted/regular/top-forecast/position
   cohorts and accounts explicitly for missing outcomes.
6. Label Monte Carlo precision and mean-points sacrifice honestly. Show per-chip validation status.
   Correct fallback lineup evidence that previously hard-coded two sources; it now counts actual sources.

## New diagnostic, not new authority

The bounded next-deadline continuation planner is integrated in every weekly receipt. It carries
FTs, prices, bank and legal future actions rather than assuming the same roster throughout.
The published run completed its four-root comparison in **1.99 seconds** and also favoured the
operational action within that restricted deterministic search. Its screening-utility edge over
roll was about **0.545**, which must not be confused with the production simulated +2.187.

The model is explicitly **unvalidated**: flat-price default, no learned news probabilities,
fixed-roster approximation after the next deadline, small root set and bounded solve budgets.
It cannot change the recommendation. Matched sequential historical policy replay is the next
highest-value work, followed by joint persistent WC/FH planning.

## Tests and QA

- **143 tests passed** across weekly actions/simulation/selection, continuation, exact season state,
  chip timing, chip replays, prospective scoring, workspace, refresh and publication.
- Python lint passed for the changed implementation/test files.
- TypeScript/Vite production build and frontend lint passed. Existing bundle-size warning remains.
- Browser checks passed for the mean interval, model-error explanation, risk trade-off, four chip
  statuses and mobile overflow/reachability. Screenshots were inspected and the new detail text was
  increased in size/contrast after the first visual review.
- Existing mocked browser workflow passed: login → sync → refresh → publication, external worker
  updates, precise failure messages, timestamps and mobile layout. These tests do not use credentials
  or submit real refresh/account mutations.
- All changed implementation files pass whitespace checks. The wider dirty worktree contains
  pre-existing Markdown hard-break/trailing-space warnings in other generated reports.

The first full-sized staged test exposed a `Decimal` serialization error in the new diagnostic.
It failed before publication; the previous active recommendation was retained. Decimal/date/nested
Arrow values now have explicit canonical hashing, with a regression test. The subsequent normal
pipeline completed successfully. Six older workspace tests initially depended on changing live
timestamps/calendar flags; their presentation inputs are now isolated from that drift.

Frozen selector replay is reproducible without current forecasts or FPL requests:

```bash
.venv/bin/python scripts/replay_weekly_selection.py \
  data/decisions/weekly/event-2/5c47b2094a9482325c1634fd232a17ea05d5288da3b9f530f9ea826512de5511.json \
  data/decisions/weekly/event-3/e7f0a2a5617e0c7e96c870238f6729a57b7797d4f17ae8c17b474001bbe54889.json \
  data/decisions/2026-27-weekly-current.json
```

It reconstructs legal actions from hash-verified historical manager states and requires identical
rules. GW2 changes to the admissible rank-three Richarlison → Igor Jesus route; GW3/GW4 are unchanged.
Both GW2 routes would have scored 90: this is a correctness fix, not evidence of extra realized points.

Browser reproduction, with API/Vite running:

```bash
cd web
node tests/weekly-evidence.mjs
node tests/refresh-flow.mjs
```

## Explicitly unfinished

Adaptive policy promotion; full joint WC/FH retained-value validation; calibrated tactical-role
change detection; candidate-generating market/independent-data challengers; matched bench/premium
allocation and risk-weight replays; adequate untouched 2026/27 and matched external benchmarks.
No new LoRA/model training, git commit/push, or FPL account write was performed.
