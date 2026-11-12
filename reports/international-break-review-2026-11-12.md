# International break review, 12 November 2026

State after GW10: **585 points, rank 3.60M of 11.3M**. All four first-half chips unused; they expire
at the GW19 deadline (1 January). Sources: public FPL API (entry 2754976, overall league
standings), archived pre-deadline decisions in `data/decisions/weekly/`, raw snapshots in
`data/raw/fpl/2026-27/snapshots/live/`. Scripts: `scripts/season_review/` (run from a scratch
directory; `decision_audit.py` first, it builds the cache the others read).

## Where we stand

| Line | Points | Gap to us |
|---|---:|---:|
| Rank 1 | 825 | 240 |
| Top 1k | 754 | 169 |
| Top 10k | 731 | 146 |
| Top 100k | 699 | 114 |
| Top 1M | 645 | 60 |
| Us | 585 | |
| Average manager (sum of GW averages) | 563 | −22 |

Against the median of 60 sampled managers ranked about 1k and 10k:

| GW | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Elite median | 69 | 110 | 57 | 97 | 56 | 81 | 78 | 52 | 69 | 74 |
| Us | 35 | 90 | 43 | 56 | 62 | 36 | 60 | 72 | 67 | 68 |
| Diff | −34 | −20 | −14 | −41 | +6 | −45 | −18 | +20 | −2 | −6 |

GW1–7: −166. GW8–10: +12. The gap was built early; since the 16 and 21 October fixes (simulation
lineups, availability bug) we have scored at the elite weekly rate. Three weeks is a small sample.

## Findings

1. **Chips are the largest certain gap.** All 60 elite managers have played chips: Bench Boost 57
   (38 of them in GW1), Triple Captain 56 (32 in GW3, 17 in GW7), Wildcard 46 (28 in GW4), Free
   Hit 30. We have played none. They have spent theirs; ours are still in hand for GW11–19.
2. **Transfers are a strength.** Nine transfers, +140 points net while held, one 4-point hit.
3. **Forecasts are sound on average.** GW4–10, 1,671 player-weeks: MAE 2.24 vs 2.61 for FPL
   `ep_next`; rank correlation 0.32 vs 0.16; calibrated in every bucket (5–6 forecast → 5.96 actual).
4. **Forecast weak spots.**
   - Premiums over-forecast: £8.5m+ forecast 4.9, actual 4.2 (n=32). Bruno Fernandes GW4–10:
     forecast 5.0, actual 2.6. Saka 5.0 vs 3.0.
   - Cheap template defenders under-forecast: Konsa 3.2 vs 7.4, De Cuyper 3.2 vs 7.7, Vuskovic
     3.1 vs 7.4 (ranked outside our top 30 defenders). N. Jackson 3.5 vs 7.1.
   - A naive residual blend does not help (MAE worsens at every weight; error persistence between
     GW4–7 and GW8–10 is 0.10). Part of the template miss is hindsight. Needs a test on underlying
     stats and team defence strength, not points chasing.
5. **Captaincy.** Captain scored ≤3 in 6 of 10 weeks; 56 points behind best-in-XI (hindsight).
   Captaining Haaland every week would have scored 70 vs our 68, so Haaland alone is not the gap.
   Bruno was captain four times for 2, 23, 2, 1.
6. **Bench.** 139 bench points (elite median 100.5). Bench value £23.1m vs £20.8m. A strong bench
   that was never Bench Boosted.
7. **Structure.** Elite ownership: Haaland 100%; we own 2 of their top 12. Team value £100.2m vs
   £103.4m. The GW10 Wildcard candidate had no Haaland and few template players.
8. **Reliability.** 276 uncommitted files; CLI refresh watcher times out mid-run; FPL token expired
   mid-day; a blocked refresh rewrites forecast files under a published decision; five tests fail
   on season date.

## Plan for the break (GW11 deadline 21 Nov, GW12 27 Nov)

| # | Work | Why | Estimated size |
|---|---|---|---|
| 1 | Chip calendar on real numbers to GW19: extend forecasts past GW14, schedule all four chips jointly, Wildcard then Bench Boost | Four chips in nine weeks; Triple Captain and Free Hit weeks are placeholders today | 35–45 points (estimate) |
| 2 | Wildcard squad challenge: longer horizon, Haaland and template structures tested against the engine's pick in shared simulations | The Wildcard sets 15 players for up to eight weeks | Largest single decision left |
| 3 | Forecast tests: premium over-forecast, team defence strength and defensive contributions, in-season learning rate; backtest on 2024/25 and 2025/26 mid-season origins; promote on expected points | Feeds 2 and captaincy | Unknown until tested |
| 4 | Bench budget: after Bench Boost, move £2–3m from bench to XI | 39 bench points above elite | Tested 12 November: no gain, withdrawn |
| 5 | Reliability pass and unattended pre-deadline runs with a notification; commit the work | Eight deadlines between 27 Nov and 1 Jan | Protects every decision |
| 6 | Weekly elite scoreboard (this report's tables, automated) | Outcome-based measure of whether changes work | Measurement |
| 7 | Ownership-aware selection: cover heavily owned players unless the forecast says poor value; ownership breaks ties within about 0.3 pts a week; differential captain within about 0.5 pts; risk dial rises late in the season. Thresholds are starting guesses, to be backtested | The engine ignores ownership, so it takes large bets against the field without measuring them | Unknown until tested |

### How differentiated the squad already is (GW10, 60-manager elite sample)

- Two elite squads share a median of 8 of 15 players. Ours shares 3 with a typical elite squad.
- Mean elite ownership of our 15 is 24%.
- Ten players are owned by at least half the sample: Haaland 100%, Groß 93%, Rogers 92%, Konsa 83%, Calafiori 80%, De Cuyper 78%, N.Jackson 75%, Tavernier 70%, Raya 67%, Palmer 62%. We hold Groß and Rogers.
- Our chips are unplayed while theirs are spent, so chip points are gains against the whole sample.

Order: 1 and 3 first (3 feeds 2), then 2 before the GW11 run on 20 November, 5 alongside, 4 after
the Bench Boost, 6 any time.

### Correction, 12 November: festive rotation

The first draft said to keep the Bench Boost out of GW17–19 because of rotation. History does not support that. Since 2021/22, players who had played 60 minutes in each of their last three matches reached 60 minutes again in 82.5% of matches on three days' rest or less (3,139 player-matches) and 85.4% on six to nine days (11,398). Mean points were 3.22 and 3.10. The planner applies no festive discount.

### Forecast test, 12 November: the scoring-rule hypothesis

Question: does the points model under-rate defenders because only one of its ten training seasons (2025/26) has defensive-contribution points?

- Evidence for: in the season-forward backtest, 2025/26 defenders forecast at 2.5 or more scored 0.5 a match above forecast (1,571 player-matches). The two earlier seasons were within 0.13.
- Test (`scripts/research_rule_era_refit.py`): train on every season to 2024/25 plus 2025/26 GW1–19, test on 2025/26 GW20–38 (15,163 player-matches). Nine variants of the points model: recent-season weighting, a rule-era flag, season-to-date form inputs.
- Result: once the model has seen half a season of the new rule, the gap is gone. The current equal-weight model over-forecast likely-starter defenders by 0.24 and had the lowest error (MAE 0.947). Weighting the new-rule season more heavily raised error (0.973 at three times the weight) and widened the bias (0.45).
- Season-to-date inputs: MAE 0.949, top-k points 187.7 against 185.8. Inside noise for one half season.
- Decision: no forecast change. The 2026/27 misses on Konsa, De Cuyper and Vuskovic are not explained by the rule change. With the earlier form-reversion replay (9% of a short-run form gap persists) this is the third test that says chasing this season's surprises does not pay.

### Chip calendar, first live run (12 November, GW11 data)

The planner now prices every chip for every week to GW19 (`src/fplagent_engine/chip_timing.py`). Why no chip had been played: at GW10 all four showed a positive edge and all four failed one check that needed the 95% lower bound of "now against later" above zero. The calendar replaces that check.

| Chip | Week | Expected gain | Note |
|---|---|--:|---|
| Wildcard | GW11 | 2.5 over the best later week | Margin needed is 2.0, so this is close and is re-run on 20 November |
| Free Hit | GW13 | 2.4 | Low value after a Wildcard with no blank weeks; played so it is not lost |
| Bench Boost | GW17 | 14.3 | Squad built for it; GW12 scores 12.5 and GW18 13.1 |
| Triple Captain | GW19 | 6.6 | GW13 scores the same; weeks after GW15 use fixture-adjusted form |

Season paths to GW19 (20,000 draws): Wildcard now 548.2, best two-transfer route with Wildcard in GW12 545.7.

### Wildcard squad challenge (12 November, `scripts/season_review/wildcard_challenge.py`)

Each squad is a GW11 Wildcard managed by the same weekly replanning to GW19, scored on the same 20,000 draws.

| Squad | Points to GW19 | Against the app's pick | Players shared with a typical elite squad |
|---|--:|--:|--:|
| App's pick, five-week view (Bruno, Isak, no Haaland) | 548.2 | 0 | 3.5 |
| App's pick, eight-week view (same core, McGinn for Rudoni) | 550.6 | +2.4 (2.2 to 2.6) | 3.5 |
| Haaland required (no Bruno, no Isak) | 549.5 | +1.2 (1.0 to 1.5) | 4.3 |
| Elite core required (seven players owned by 75% or more) | 540.3 | −8.0 (−8.3 to −7.7) | 6.8 |

- Copying the template costs 8 points on our forecasts.
- Haaland against Bruno and Isak is a tie on forecast: 1.1 points over nine weeks.
- The five-week solver's "best" squad was beaten by two alternatives in simulation, so Wildcard squads should be chosen by simulation from several builds. Not yet wired into the published decision.
- Intervals are simulation error only. Field-gap figures in the JSON assume the field never changes and are for comparing squads, not forecasting rank.

### Cover or swing: simulated against real rival squads (12 November)

Question: on a forecast tie, should the app take the player everyone owns (Haaland) or the differentials (Bruno and Isak)? Method: 209 real squads at ranks 10k, 100k, 500k, 1M, 2M, 3M and 3.6M (`scripts/season_review/rival_sample.py`), each scored on the same 20,000 draws to GW19 as our two Wildcard squads, starting from real totals. Haaland is in 87% to 100% of squads at every rank.

| Chance of finishing GW19 above a manager now ranked | Bruno and Isak | Haaland | Difference |
|---|--:|--:|--:|
| 1M (60 ahead), rivals keep their season scoring rate | 2.8% | 2.5% | −0.4 |
| 2M (33 ahead), same assumption | 19.9% | 19.0% | −0.9 |
| 3M (12 ahead), same assumption | 51.2% | 50.1% | −1.0 |
| 1M, rivals score like us without chips | 22.8% | 21.6% | −1.1 |
| 500k, rivals score like us without chips | 11.0% | 10.2% | −0.8 |

- Owning Haaland cuts the spread of our result against a rival by about 1.5% (standard deviation 45.2 against 45.9 points). Fourteen other players still differ, so one shared player changes little.
- With the two squads' averages forced equal, covering helps by under 1 percentage point against rivals we are favoured to pass and swinging helps by a similar amount against rivals who need luck to catch.
- The 1.2-point difference in average points between the squads matters more than the ownership effect.
- Decision: no cover rule. Pick on expected points; ownership stays a measurement and a tie-break of last resort. Plan item 7 shrinks to that.
- Limits: rivals keep their GW10 XI and captain with no transfers or chips, so the levels depend on the scoring-rate assumption (two shown). The differences between our two squads are stable across assumptions. Intervals on the differences are about ±0.2 points of probability.

### Bench budget test (12 November, `scripts/season_review/bench_budget.py`)

Audit first. Of the 139 bench points in GW1–10, 56 were the benched goalkeeper (Verbruggen 40 in eight weeks, Donnarumma 16 in two) and 83 were outfield. The started keeper scored 34 in the same weeks, so the keeper pick cost 22 points. That is about 1.6 standard deviations of ordinary keeper luck over ten weeks, so it is not evidence of a forecast fault. The sampled top managers' median bench total is 100.5 including their keeper, so our outfield bench is not out of line.

Test: five Wildcard squads built and managed to GW19 with the bench counted at 0%, 4%, 8% (current), 16% and 30% of forecast points, Bench Boost and Triple Captain on the live calendar, 20,000 shared draws with automatic substitutions.

| Bench weight | Points to GW19 | Against current |
|---|--:|--:|
| 0% | 568.9 | −0.3 |
| 4% | 569.2 | 0.0 |
| 8% (current) | 569.2 | 0 |
| 16% | 569.2 | 0.0 |
| 30% | 569.3 | +0.1 (±0.2) |

- Four of the five settings pick the same 15 players. The setting does not matter, so it stays at 8%.
- Reason: the forecasts are close together (most picks sit between 4 and 5.3 points a week), so the squad is 15 playable players who rotate on fixtures. Bruno Fernandes is on the GW11 bench because of Liverpool away and starts in later weeks. Bench value by price is therefore a misleading measure for this squad.
- The earlier estimate of 1–2 points a week from moving bench money is withdrawn.

### Top-manager scoreboard (built 12 November)

In the app's season review: weekly points minus the median of 60 sampled managers ranked about 1,000 and 10,000, the last-five-weeks and season totals, the gap to the top-10k line, and the most-owned players we lack. The sample is fetched once per finished Gameweek when results are refreshed (`fplagent_data.elite_sample`).

What it is for: one rule. Trailing the median by 50 or more over five weeks (roughly one standard deviation of luck) flags a review of forecasts and decisions. It never changes a pick; the cover-or-swing test showed ownership should not drive selection. Today it reads −57 for GW6–10, almost all from GW6 (−46), and −155 for the season.

## Not verified

- Chip point values are estimates; elite chip gains were not measured.
- Elite sample is 60 managers at two rank points, one snapshot.
- Forecast scoring covers GW4–10 only (full-pool forecasts were not archived for GW1–3).
