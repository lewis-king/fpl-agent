# Adaptive transfers: implementation, historical test and activation decision

**9 September 2026. Priority 2 of the points-first programme.**

## Decision

Do **not** activate the next-deadline planner as the production selector yet. The opening-ten-event
historical experiment improved net points in 2024/25 but not in 2025/26. It therefore failed its
predeclared two-season screen. This is evidence for further testing, not a reason to tune settings
until both already-inspected seasons turn positive.

The validated weekly selector remains responsible for the app's recommendation. The new planner
remains a bounded diagnostic with `decision_authority: false`. Its frozen first-action preference
will now be scored after each future event, allowing genuinely new evidence to accumulate.

## What was built

- A paired sequential replay: identical GW1 squad and lineup, then independently carried rosters,
  purchase prices, sale proceeds, bank and free transfers for the two policies.
- At each deadline, the fixed-roster policy chooses its best screening action. The adaptive policy
  fixes a current action and compares the best legal next-deadline transfer continuation for every
  root in the same bounded first-action set. Only the current action is executed; next week the
  policy re-plans with that week's information.
- Exact incremental hit costs, captain fallback and legal autosubs in realized scoring. An initial
  squad has zero bankable GW1 transfers and receives one FT for GW2.
- Club changes observed at a later deadline update a holding's club without charging a fantasy
  transfer or resetting its purchase price. Unsupported position changes or over-club-limit states
  block the experiment rather than being silently repaired.
- Solver diagnostics distinguish optimal solutions, proven infeasibility and unresolved searches.
  A timed-out child route cannot now masquerade as an impossible route and produce a supposedly
  complete continuation winner. Ordinary production candidate attempts are recorded too.
- Each new continuation receipt preserves the future roster and proposed event lineups as well as
  transfers, hit costs and FT/cash state. These are plans under stated assumptions, not future facts.
- Prospective scoring recognizes the diagnostic's frozen current-action choice, compares its actual
  net points with the production action, and labels this **first-action-only**. It does not pretend
  that this proves a multiweek adaptive policy worked.

## Experiment design, frozen before scoring

| Setting | Choice and limitation |
| --- | --- |
| Evaluation | GW1–10 of 2024/25 and 2025/26; no chips |
| Lookahead | Five events, decay 0.88, bench screening proxy 0.08 |
| Ordinary actions | Roll and one optimal squad per exact transfer count; maximum two transfers and one paid transfer |
| Future action | Same transfer bounds at the next deadline; fixed roster thereafter |
| Prices/news | Frozen within a projection; actual deadline prices and forecasts are ingested only when that deadline arrives |
| FT terminal value | Zero in both arms, avoiding a present-day calibration trained on the test seasons |
| Search budget | Two seconds per exact solve; 24-second continuation budget; unresolved solves invalidate the comparison |
| Search equality | Identical first-action bounds; identical states share the same solved roots. The adaptive arm uses additional continuation compute |
| Screen | Positive net-point delta in both full ten-event folds; insufficient for production authority even if passed |

The scoring window is **not** treated as the end of the season. GW10 still plans through GW14.
This avoids an artificial last-week liquidation effect. The early window deliberately excludes
historical midseason transfer grants and joint chip-rule changes, which still need separate tests.

Current-event predictions come from stored rolling out-of-fold forecasts. Historical forward xP
is reconstructed from the origin forecast and the latest fixture snapshot available by that
deadline. Position-specific fixture-response coefficients train on 2023/24 for the 2024/25 fold,
and 2023/24–2024/25 for 2025/26. Later forecasts, later prices, later fixture snapshots and realized
labels are not passed into the earlier decision optimizer. The tests explicitly mutate future
data and actual outcomes and verify that the earlier decision rows do not change.

This is **not** a reproduction of the complete current three-world simulation selector. It uses
the deterministic screening objective and a zero-terminal-FT ablation; it does not use the live
paid-hit promotion gates. The relatively high hit counts below make that distinction important.
Nor are these globally untouched seasons: the project has inspected them in earlier research.

## Results

| Season | Fixed net points | Adaptive net points | Difference | Fixed / adaptive transfers | Fixed / adaptive hit points |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024/25 | 582 | 640 | **+58** | 15 / 11 | 24 / 8 |
| 2025/26 | 494 | 492 | **−2** | 17 / 15 | 32 / 24 |

In 2024/25, adaptive planning rolled twice while the comparator made transfers every deadline.
It saved 16 hit points and scored 42 more gross points. In 2025/26 it saved eight hit points but
scored ten fewer gross points. Reducing churn is useful only when the retained players and future
routes justify it; this experiment does not show a consistently superior policy.

Descriptive four-event moving-block intervals for the mean weekly difference, excluding the shared
GW1, are +3.33 to +9.67 and −3.23 to +2.78. These use only nine paired differences per fold. They
are not reliable season-wide confidence guarantees, do not remove model misspecification, and
must not be pooled into a claimed universal lift. The predeclared screen **failed**.

The final frozen-code run took **43.7 seconds** and reproduced both paths' previous completed
results exactly. No horizon, weight or player preference was retuned after seeing the results.

## Reproducibility and safety

Source: `src/fplagent_engine/weekly_continuation_replay.py`.

Canonical research receipt:
`data/research/weekly-continuation/20260909-opening10-final.json`.

Configuration SHA-256:
`d157447de99cf40a7ff5d34afbf2a43d176cb20adb665606c859df54b91d9a83`.

The receipt freezes input and implementation hashes, configurations, per-event actions, lineups,
hits, cash and FT state. Completion checks that code and historical inputs did not change during
the experiment. Existing result paths cannot be overwritten. Research runs never write the live
decision or the user's FPL account.

```bash
.venv/bin/python scripts/replay_weekly_continuation.py \
  --output data/research/weekly-continuation/new-experiment.json
```

The first development run stopped on Eze's historical club change; the receipt is retained as
blocked, not counted as a completed fold pair. A subsequent development run was superseded by
the canonical frozen-code confirmation above. All are preserved for audit.

## What should happen next, by impact

1. Continue recording current-deadline challenger choices and score them only after official
   finalization. Match the planner against the **actual production selector**, with common
   simulation worlds, its paid-hit gates and candidate access, before granting authority.
2. Extend the state planner to permanent Wildcard and restored Free Hit rosters, and WC→BB
   interactions. Validate complete chip halves jointly with transfers; isolated attractive chip
   uplift is not enough. Do not wait for another sequence of narrow historical tuning attempts.
3. Test genuine tactical/selection changes and fresh independent lineup evidence. Forecast errors
   about whether or how a player plays can outweigh a more sophisticated optimizer.
4. Revisit allocation/risk weights only through the same net-points comparisons, not to force a
   favoured player, an expensive bench, or a recent high scorer into the team.

The full programme is in [the ordered roadmap](../docs/decision-improvement-roadmap-2026-09-09.md).
This report makes no SOTA or guaranteed-league-winning claim.

## Fresh GW4 publication and checks

The normal app-triggered refresh ran from **12:44:29 to 12:46:19 BST**, taking **109.8 seconds**.
All five stages passed; the browser read model and immutable archive agree with the active bytes.
The live engine implementation hash also matches the published input identity.

- **Richarlison → Evanilson**; one FT, no hit, one FT available next deadline.
- **Bruno Fernandes captain; Szoboszlai vice-captain; no chip.**
- **53.8879 projected GW4 points**, including captaincy; +2.1871 weighted GW4–8 model gain versus
  the optimized roll comparator; +0.9704 in the worst model world.
- The player move and lineup are unchanged from the previous validated run. Tiny numerical
  simulation differences are not a changed recommendation.
- The current limited continuation diagnostic also chooses that route, finishes in **2.04 seconds**,
  and reports a complete four-root comparison. Twelve ordinary roots were outside its diagnostic
  budget. It still has no authority; agreement here does not repair the failed historical screen.
- All **26 ordinary candidate search attempts** ended optimally or with proven infeasibility.
  The receipt freezes all **654** current-event player forecasts for subsequent scoring.
- BB/TC have live eligibility; WC/FH remain research-only. Thus “no chip” must not be interpreted as
  proof that the still-unvalidated joint Wildcard/Free Hit policy is complete.

Recommended 3-4-3:

- GK: Verbruggen.
- DEF: Truffert, Tarkowski, António Silva.
- MID: Bruno Fernandes (C), Szoboszlai (VC), Semenyo, Gibbs-White.
- FWD: Evanilson, Igor Thiago, Calvert-Lewin.
- Bench: Mbeumo, N. Williams, Maguire; Donnarumma as reserve goalkeeper.

The app's saved current XI differs from this optimized XI. The displayed **+2.64 GW4 points**
compares the recommendation with the user's saved lineup; it is not the same comparator or horizon
as the **+2.1871** simulated five-week gain versus optimized rolling.

Persistence identifiers:

- Refresh: `refresh-v1-c56ea88bb6c65934`.
- Active: `data/decisions/2026-27-weekly-current.json`.
- Archive: `data/decisions/weekly/event-4/abfac5f7b4ceb4b6ac92c2b82ba49aaf52d2e19c892c6fad760fad8e4b20a267.json`.
- Decision SHA-256: `4a5af1633f3f2ed9e112b47e17baf5452b81bdc140d0889b328c8b87480a8032`.
- Engine SHA-256: `ec4ec65e3d1748f8521ae221a24ec916d607c752100858c14ecd35fb8ebcdc80`.

Public evidence was refreshed during this run; manager state was rebuilt against it using the
existing authenticated **08:11 BST** snapshot, not a newly submitted login or account mutation.
The next regular evidence check is **18:46 BST**, subject to material changes and the service remaining
running. The official GW4 deadline is **12 September, 13:30 BST**; this is not a deadline-day lock.

**162 targeted tests passed**, covering actions, simulation, continuation, season state, chips,
prospective scoring, horizon replay, workspace, refresh, publication and rehearsal. Python lint
and changed-file whitespace checks passed. A pre-existing Starlette/httpx deprecation warning
remains. The API at port 8000, frontend at 5173 and authenticated MCP at 8021 remain running.
Both existing browser regression scripts passed against the fresh read model with API mutations
mocked: evidence/uncertainty and chip-status presentation, plus login→sync→refresh→publication,
external-worker updates, precise blockers, timestamps and mobile layout.
No LLM run, git commit/push or FPL-account write was performed.
