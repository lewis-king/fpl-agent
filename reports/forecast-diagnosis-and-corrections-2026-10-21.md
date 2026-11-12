# Fresh forecast comparison, error diagnosis and availability corrections

21 October 2026 · GW8 research · no FPL account writes or new published recommendation

## What changed

This pass found and fixed live forecast defects, rather than concluding that the incumbent
could not be improved. A fresh, authorized Scout comparison exposed a player our model still
treated as likely to appear despite the official **next-round** availability being zero.
The defect affected other players and also suppressed some returning players.

The live input/forecast corrections are production code. Historical experiments below are
separate evidence, not a promised season-points uplift. No Scout projections are used to train
our models or copied into a production prediction feed. No LLM work was performed.

## 1. A real contemporaneous comparison

Official snapshot: `20261021T212002161760Z`. Refreshed official results, fixtures, market
evidence, live features and participation inputs; regenerated direct and component forecasts.
Market collection reported `ready`; lineup evidence was partial, not a fabricated two-source
consensus. Scout's stale team-news material was not made current by fetching the page again.

Private authorized projected-points capture compared 25 players across GW8–12, using the
fixed supplied 15 plus each source's leading two players per position over that horizon.
Identity, season, club, position, price and freshness checks passed with no issues.
Capture time is known; Scout's underlying model-build/publication time remains unknown.

- Before correction: `.local/scout-benchmarks/gw08-5acf8df90ca2b7e65e0d.json`.
- After correction: `.local/scout-benchmarks/gw08-fe173abc6e67b14713cf.json`.
- These files remain private/ignored. Neither receipt is a training set.
- The supplied manager contract is from 17 October/GW7. It defines a fixed roster for
  comparing forecasts, **not** proof of today's authenticated account state.

Both sources' transparent scalar-xP controls selected the **same starting XI and Bruno
Fernandes captain** for that fixed roster. They differed on vice-captain and bench order.
These are our identical legal comparison controls, not Scout's actual optimizer or editorial
recommendation. Their projected totals are not directly comparable measures of realized skill.
Scout's GW8 outcomes do not exist yet; the frozen capture will be scored when finalized.

The useful disagreements included greater Scout confidence in Mbeumo and Saka, and less in
Calvert-Lewin and Groß. Disagreement alone does not identify which model is correct.

### Concrete defect uncovered

Semenyo's snapshot had **100% this round, 0% next round**. The original regenerated forecast
still assigned approximately **75.5% appearance probability and 2.70 points** for GW8.
After correction both are **zero** for the officially flagged event.

Independent checks against the raw official snapshot found **18 unavailable players with
nonzero direct forecasts** before correction; none after. All component checks also pass.
Examples affected include Szoboszlai, Mainoo and Saliba. Conversely, players such as Mateta
and Gravenberch are no longer excluded solely by the previous round's zero flag.
Across the current GW8 pool, 38 player xP values changed by more than 0.01.

## 2. Where the season's prediction errors actually came from

The audit verifies immutable decision/outcome hashes and refuses post-deadline forecasts.
It analyzes **2,768 frozen player-events**, including 105 chosen-squad observations and seven
captains. GW1–3 saved only candidate subsets; GW4–7 saved the full pool. These samples are
not interchangeable or independent. Missing historical minutes estimates stay missing.

For the 105 chosen-squad player-events, mean xP was **4.281**, versus **4.086** realized points.
An exact algebraic decomposition attributes **+9.33** points to appearance-versus-DNP outcomes
and **−29.85** to returns conditional on appearing (including cameo duration).
This is about all 15 players, without captain multipliers; it is **not** a league-score deficit
or a number of points that could necessarily have been recovered.

The seven captains averaged **5.97** forecast points and **4.86** actual points before doubling.
That is a warning, not enough data to infer a stable captain-bias correction.

Among frozen players forecast at least three points:

| Position | Player-events | Mean xP | Mean actual |
| --- | ---: | ---: | ---: |
| GK | 72 | 3.52 | 3.67 |
| DEF | 176 | 3.82 | 3.84 |
| MID | 222 | 3.84 | 4.14 |
| FWD | 85 | 4.12 | 3.78 |

The selected squad's weaker outcomes cannot honestly be blamed entirely on nonappearance.
Igor Thiago, Truffert and Maguire were substantial negative return differences despite regularly
playing. Positive differences included De Cuyper, Groß and Haaland. These are retrospective
diagnostic rankings, **not** a recipe to chase last week's scorers or nerf named players.

The existing receipts did not consistently freeze separate attacking, clean-sheet and
defensive-contribution predictions. We therefore cannot credibly assign each old xP miss
to those exact components. New receipts preserve round-specific availability, raw/conditional
xP, role adjustment, team goal/clean-sheet environment and attacking-history inputs so that
future discrepancies can be traced more precisely. The diagnostic now refreshes automatically
with normal finalized-outcome scoring; no extra weekly manager task is required.

## 3. Implemented corrections and safeguards

1. **Relative horizons:** current availability is anchored to the actual next decision event,
   not hardcoded GW1/GW2/GW3 conditions. Longer-range recovery assumptions are explicitly labeled
   `unvalidated_recovery_prior`; a zero next-round flag is not proof of a season-long absence.
2. **Correct official round:** participation consensus uses next-round probability for an
   upcoming deadline and does not fall back to a contradictory previous-round value.
   A still-running current GW no longer wins over `is_next` when selecting the next decision.
3. **Source-independent official gate:** the direct forecast enforces current official
   unavailability even when predicted-lineup feeds are absent, stale or incompletely authorized.
4. **Zero is not missing:** a zero role ratio no longer becomes `1.0` in component inference.
   Nonplaying players cannot retain manufactured goal, assist, bonus or save expectations.
5. **Independent publication check:** raw official availability is checked against direct and
   component outputs. A future recurrence blocks publication even if forecast flags claim success.
6. **Cache and provenance:** direct/component implementation hashes participate in cache identity;
   forecast receipts freeze the additional diagnostic evidence.

These are general corrections, not name-based overrides. Existing risk/search parameters,
chip policies and learned model weights remain unchanged unless a separate validated release
explicitly replaces them.

## Historical checks and their limits

An isolated dated **explicit next-round-zero** ablation and a lagged-form baseline were run
through all 38 events of 2023/24, 2024/25 and 2025/26. Each arm carries its own roster, cash,
purchase/selling values, free transfers and hit costs. Outcomes are not provided to the
selection objective. Identical current transfer constraints apply to all arms; no chips.

| Full-season legal replay, after hits | 2023/24 | 2024/25 | 2025/26 |
| --- | ---: | ---: | ---: |
| Frozen own-model control | 2,176 | 2,228 | 2,070 |
| Explicit next-round-zero correction | 2,205 | 2,189 | 2,070 |
| Lagged form-five control | 2,051 | 1,880 | 1,774 |
| Zero-correction difference | **+29** | **−39** | **0** |

The hard-zero ablation improved all-player MAE/RMSE in all three seasons, but did **not**
establish a season-points advantage. The four-event-block delta intervals include zero.
This distinguishes enforcing the intended live availability contract from claiming guaranteed
points gains. About 1% of historical explicit-zero observations still appeared, illustrating
that stale/inexact archive flags are not physical certainty.

Receipt: `data/research/forecast-diagnosis-20261021/historical-zero-policy-v3.json`, completed
76.19 seconds, stable code/data hashes. Independent accounting and exhaustive legal-substitution
checks passed **342 arm-events**. There were 136 held-player/event missing-row fallbacks, declared
as zero outcomes with carried prices, not silently presented as complete archived coverage.
Failed setup runs v1/v2 are preserved and not counted as completed evidence.

Important limits: historical snapshots use Git timestamps and fixture-minus-90-minute deadline
proxies; availability coverage is incomplete (especially 2025/26); prices can be lagged; the
replay uses a one-event scalar optimizer, not the production five-event multi-world search.
It is a useful controlled diagnostic, **not** a production-matched historical league result.

A paired chronological refit also tested whether correcting the availability input during
training helps, using identical XGBoost parameters, seeds and time-forward validation folds.
**2,801 historical feature rows changed.** Both arms were refitted on the RTX5090; validation
uses the season preceding each test season, and fitting uses earlier seasons only.

| Paired refit, full-season legal replay after hits | 2023/24 | 2024/25 | 2025/26 |
| --- | ---: | ---: | ---: |
| Recreated incumbent | 2,102 | 2,249 | 1,968 |
| Next-round input refit | 2,102 | 2,249 | 1,998 |
| Difference | 0 | 0 | **+30** |

The first two folds are numerically identical: their training histories precede meaningful
dated availability coverage, so they do not independently validate this feature change.
Only the latest fold materially tests it. Its paired block interval is **−3.05 to +4.53
points/event**; small Brier/RMSE gains coexist with slightly worse MAE. This is encouraging
policy evidence, not sufficient justification to replace the learned weights. The recreated
baseline also differs from the older archived OOF control: compare **within** each paired
experiment, never subtract absolute totals across those tables or against the live season.

Receipt `data/research/forecast-diagnosis-20261021/paired-refit-v2.json` completed in **95.54s**
with stable input/code hashes. Independent ledger/scoring checks passed **228 arm-events**,
with 90 declared missing-held-player/event fallbacks. V1 failed before fitting due to a JSON
serialization setup issue; it is preserved and not counted as evidence. There are no live
weight changes, no after-the-fact parameter search, and no historical Scout backfill.

### Release decision

`points_first_release_20261021_v5` promotes the live round/zero-handling corrections and retains
the current learned weights. **This is not another “nothing improved” release:** fresh GW8
forecasts now correctly exclude officially unavailable players and restore relevant returnees.
It is also not a claim that these repairs establish a winning model or guaranteed points uplift.

The corrected forecasting code runs on the next ordinary decision refresh. The fresh forecast
artifacts have already been rebuilt, but the published recommendation remains the saved GW7
receipt; no stale manager contract was relabeled as a fresh actionable GW8 decision.

## Reproduction

```bash
.venv/bin/python scripts/research_round_availability.py --output data/research/NEW-availability-audit.json
.venv/bin/python scripts/research_availability_refit.py --output data/research/NEW-paired-refit.json
.venv/bin/python scripts/verify_forecast_replay.py data/research/forecast-diagnosis-20261021/historical-zero-policy-v3.json
.venv/bin/pytest -q tests/test_engine_round_availability.py
```

Do not edit engine code, refresh shared feature artifacts, or launch competing GPU-heavy work
during the hash-frozen experiments. Use a new output name; old receipts are preserved.

## Final verification

- **905 non-LLM tests passed** in 34.48s, one existing Starlette deprecation warning.
- Targeted Ruff and edited-code/documentation whitespace checks passed. Generated scoreboards
  retain their existing Markdown hard-line-break whitespace convention.
- Independent historical accounting/substitution validation: **570 arm-events** across the
  two completed experiments. This proves accounting under the stated archive assumptions,
  not forecast superiority.
- Corrected direct/component forecasts checked against the raw official next-round data;
  no unavailability contradictions remain. Scouting evidence is rebuilt from corrected forecasts.
- Published GW7 decision SHA256 retained:
  `a5beb7ca1db85ecba54a21787b9e9a7d42ecc247205b3e27ce86555c0e2f4899`.
- No authenticated account writes, model-weight promotion, LLM inference/training, services,
  commit or push. All completed experiment artifacts remain on disk for reproduction.
