# Historical bench-depth audit

Generated: 2026-08-09T09:27:57.338551+00:00

## Verdict

**DO NOT ASSUME A DEEP BENCH**

The existing £18.45m benchmark is exact but narrow: it is the GW1 mean for ten eventual 2019/20 top-ten managers. It is not a multi-season target. The broader test below asks a different and more actionable question: when the same season-forward forecast and legal optimiser are forced into each bench-spend band, which policy subsequently scores most actual points?

## Opening five-Gameweek replay

Each squad is selected at that season's GW1 deadline using only the GW1 forecast. It is held for five events; at each later deadline the XI, bench order, captain and vice are reset using only the forecast available for that event. Actual points, minutes, formation-valid autosubs and captain fallback determine the score. A season is omitted here unless GW1–5 are five ordinary single-fixture rounds with all 20 clubs playing exactly once in each round.

| Season | Lean ≤£18.5m | £18.6–20m | £20.1–22m | Deep >£22m | Deep − lean | Best band |
|---|---:|---:|---:|---:|---:|---|
| 2019-20 | 251 | 254 | 238 | 220 | -31 | lower_middle |
| 2021-22 | 269 | 267 | 267 | 283 | +14 | deep |
| 2022-23 | 206 | 196 | 170 | 222 | +16 | deep |
| 2024-25 | 297 | 291 | 294 | 294 | -3 | lean |
| 2025-26 | 201 | 243 | 233 | 271 | +70 | deep |

## Rolling five-event fixed-squad windows

Across 15 non-overlapping five-event windows in 6 seasons, deep benches changed realised points by **+10.67 per window versus lean** (season-clustered 95% interval -2.78 to +24.11; win rate 66.7%).

| Band | Mean actual points | Mean bench spend | Mean autosub points | Mean rotation slots | Mean stranded bench points |
|---|---:|---:|---:|---:|---:|
| lean | 240.13 | £16.30m | 1.47 | 1.07 | 1.40 |
| lower_middle | 245.20 | £18.73m | 4.27 | 3.47 | 9.93 |
| upper_middle | 236.27 | £20.25m | 6.80 | 4.20 | 10.13 |
| deep | 250.80 | £22.19m | 6.87 | 6.20 | 20.73 |

## Exact manager evidence

The exact 2019/20 eventual top-ten cohort averaged £18.45m on its GW1 bench (range £16.5m–£24.0m). Exact manager-level bench positions and purchase prices are not present for every season in the archive, so aggregate veteran ownership tables are not mislabelled as bench-spend observations.

## Decision consequence

A £22m+ bench has not cleared the multi-season generalisation gate. The current £23.0m proposal may still win under 2026/27-specific forecasts, but it must be treated as a close, season-specific challenger. Production selection should require a positive paired holdout against the best ≤£20m alternative after the final data refresh; otherwise promote the leaner squad and move the money into the XI or bank.

## Method and limitations

- Forecast folds are strictly season-forward; the test season is never used to train its model.
- The last three folds reuse the frozen production rolling forecasts; earlier folds use the same feature and model contract.
- The primary benchmark contains only five consecutive, ordinary single-fixture rounds. Blanks, doubles and extraordinary disruption are excluded rather than treated as representative of the current horizon.
- The compressed 2020/21 pandemic season is excluded from primary windows even when a particular block happened to contain one fixture per club.
- The 15-player squad is chosen using only the start-event forecast. Later-event forecasts may reset that event's XI, bench order and armband only after their own deadline information becomes available.
- International breaks require no special fixture treatment: no Premier League round is scheduled during the break. Post-break availability uncertainty belongs in the player forecast.
- Each replay is a fixed-squad experiment. It does not claim managers knew future injuries or price changes, and it intentionally gives the initial squad no future-fixture planning advantage.
- Bench spend is constrained, never rewarded in the objective. The optimiser maximises forecast starters and captain with zero proxy credit for unused substitutes.
- The rolling windows increase sample size but remain correlated within seasons; confidence intervals are therefore clustered by season.
- This is policy evidence, not evidence that historical champions themselves used the simulated squads.
