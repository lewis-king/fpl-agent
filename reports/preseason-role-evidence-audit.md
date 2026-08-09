# 2026/27 preseason role evidence audit

**Collected:** 7 August 2026, 15:08 BST  
**Decision impact:** advisory only; production forecasts and the published GW1 squad are unchanged

## Outcome

A provenance-bound preseason lineup layer is now operational. It captures confirmed friendly
lineups, matches source players conservatively to the current FPL catalog, preserves incomplete
minute data as null and derives player-level listing, start, appearance and recency evidence.

This is useful as a live verification and scenario source, but it is not ready to adjust central
appearance forecasts. The source is an unofficial third-party web API, two clubs have no confirmed
lineups in the feed, and minute coverage is too sparse. Absence from a friendly squad is not proof
of injury or of a Gameweek 1 non-appearance.

## Coverage and provenance

| Measure | Result |
| --- | ---: |
| Current FPL clubs queried | 20 |
| Completed friendlies discovered before the GW1 deadline | 57 |
| Unique events with confirmed lineups | 52 |
| Premier League club/event lineup sides | 56 |
| Current FPL players observed in at least one lineup | 352 |
| Source lineup rows | 1,319 |
| Rows mapped conservatively to a current FPL player | 875 (66.3%) |
| Rows with source minute statistics | 442 (33.5%) |
| Observed FPL players with complete minute evidence | 85 |
| Clubs without confirmed lineup evidence | Brentford, Brighton |

The lower raw mapping percentage is expected because friendly squads include academy, trial and
departed players who are not in the current FPL catalog. Matching is team-scoped and uses exact
aliases, unique multi-token containment, one explicitly verified season alias and a high-threshold
fuzzy fallback. Ambiguous names remain unmatched.

Every HTTP response is content-addressed under
`data/raw/supporting/sofascore/2026-27/preseason/archive/`. The current request list, checksums,
coverage and output hashes live in `data/manifests/preseason_lineups_current.json`.

## Evidence for the published 15

| Role | Player | Team | Eligible lineups | Listed | Starts | Apps | Minutes | Recency start | Latest start | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| XI | Donnarumma | Man City | 2 | 2 | 2 | 2 | unknown | 100% | yes | observed |
| XI | Collins | Brentford | 0 | 0 | 0 | 0 | n/a | n/a | n/a | no club feed |
| XI | Maguire | Man Utd | 3 | 3 | 3 | 3 | 163 | 100% | yes | observed |
| XI | Mukiele | Sunderland | 4 | 4 | 4 | 4 | unknown | 100% | yes | observed |
| XI | Tarkowski | Everton | 4 | 4 | 3 | 3 | unknown | 87% | yes | observed |
| XI | Truffert | Bournemouth | 2 | 2 | 1 | 1 | unknown | 39% | no | observed |
| XI | Bruno Fernandes | Man Utd | 3 | 0 | 0 | 0 | 0 | 0% | n/a | not listed |
| XI | Gibbs-White | Nott'm Forest | 3 | 3 | 3 | 3 | unknown | 100% | yes | observed |
| XI | Mbeumo | Man Utd | 3 | 3 | 3 | 3 | 188 | 100% | yes | observed |
| XI | Igor Thiago | Brentford | 0 | 0 | 0 | 0 | n/a | n/a | n/a | no club feed |
| XI | Watkins | Aston Villa | 6 | 0 | 0 | 0 | 0 | 0% | n/a | not listed |
| Bench | Verbruggen | Brighton | 0 | 0 | 0 | 0 | n/a | n/a | n/a | no club feed |
| Bench | McAteer | Ipswich | 4 | 3 | 2 | 2 | unknown | 56% | yes | observed |
| Bench | Szoboszlai | Liverpool | 3 | 3 | 2 | 3 | 189 | 76% | yes | observed |
| Bench | Calvert-Lewin | Leeds | 3 | 1 | 0 | 1 | 45 | 0% | no | observed |

The official FPL snapshot currently marks every one of these players available and carries no
player news. That does not resolve the two strongest verification flags: Watkins has not appeared
in six captured Villa lineups and captain Bruno Fernandes has not appeared in three captured United
lineups. Both need current club/news evidence and remaining-friendly observations before the
deadline. Collins, Igor Thiago and Verbruggen are unknown rather than negative because their clubs
have no confirmed source lineups.

### Attributable context check

The pattern is consistent with delayed post-World-Cup returns rather than established injuries.
Aston Villa's official site confirms Watkins was selected for England at the 2026 World Cup, and
its schedule leaves a final Borussia Mönchengladbach friendly on 15 August. A contemporaneous
preseason tracker reports that Watkins missed the early trip after a deep World Cup run and was not
expected back until August. Manchester United's official preseason coverage shows returning World
Cup groups arriving in stages, while contemporaneous reporting says Bruno Fernandes returned to
Carrington on 3 August for individual testing. These sources explain the missing friendly rows but
do not prove GW1 readiness or expected minutes.

- [Villa: World Cup squad numbers](https://www.avfc.co.uk/news/2026/june/02/news-world-cup-squad-numbers-announced/)
- [Villa: 2026 preseason schedule](https://www.avfc.co.uk/news/2026/june/22/news-villa-announce-asia-pre-season-fixtures/)
- [Manchester United: preparing for 2026/27](https://www.manutd.com/en/mutv/playlists/preparing-for-the-new-season-2026-27)
- [Fantasy Football Scout preseason return context](https://www.fantasyfootballscout.co.uk/2026/07/22/fpl-pre-season-rogers-exit-onana-injury-gomes-debut)

Accordingly, neither the late-return pattern nor the extreme DNP boundary is promoted into the
central forecast. Remaining-friendly appearances and attributable press-conference news are the
evidence that should collapse this uncertainty.

## Promotion policy

This evidence cannot directly overwrite player probabilities or minutes. The safe next use is a
separate scenario audit. The first one is now complete:

1. refresh the collector as remaining friendlies finish and bind the receipt to the official FPL
   generation used by the decision;
2. combine lineup flags with timestamped official availability and attributable club evidence;
3. create explicit late-return and uncertain-role scenarios for flagged players while retaining
   the production central forecast;
4. replay the published squad, strongest alternatives, XI, bench and captaincy on identical worlds;
5. change production only if a predeclared statistical and paired-policy gate passes.

The published 15 and configuration remain exact leaders under baseline and moderate role stress.
Under severe conditional-DNP stress, the frozen-configuration screen nominates `R-5043bb75d6`.
Giving that squad the same exhaustive 550-XI, bench, captain and vice search confirms an advantage
over the reoptimized incumbent: +0.079 residual points (95% CI +0.042 to +0.116) and +0.162
component points (+0.079 to +0.245). At the deliberately extreme DNP boundary, the deep squad
comparison and within-15 configuration both reverse. These remain verification triggers rather
than promotions because the stress factors are counterfactual bounds, not inferred availability
probabilities.

The subsequent fresh-seed threshold audit refines the severe-to-moderate path. The challenger is
supported through 51.0% conditional retention for three-plus-lineup absences and 75.6% for
role-watch players, but not at the next 51.5%/75.9% point. Its supported-edge paired gain is +0.066
residual points (95% CI +0.028 to +0.103) and +0.086 component points (+0.002 to +0.169). Because
these factors jointly thin appearances already generated by the production forecast, they remain
counterfactual stress controls rather than real availability probabilities.

The historical role-feature challenger reinforces this caution. Only its goalkeeper slice passed
the statistical screen, then it lost 0.013 points per Gameweek in the exact 76-Gameweek policy
replay, with a 95% interval of -0.426 to +0.400 and a season floor of -0.184. It was rejected and no
production artifact changed.

## Commands and artifacts

```bash
uv run fpl-data collect-preseason-lineups
uv run fplagent audit-role-appearance
uv run fplagent replay-role-appearance
uv run fplagent audit-preseason-role
uv run fplagent audit-preseason-threshold
```

- `data/processed/supporting/sofascore/2026-27/preseason_events.parquet`
- `data/processed/supporting/sofascore/2026-27/preseason_lineups.parquet`
- `data/processed/supporting/sofascore/2026-27/preseason_role_evidence.parquet`
- `data/model/appearance_role_v1/metrics.json`
- `data/model/appearance_role_v1/policy-replay.json`
- `reports/appearance-role-challenger.md`
- `reports/appearance-role-policy-replay.md`
- `data/model/preseason_role_scenario_v1/results.json`
- `reports/preseason-role-scenario-audit.md`
- `data/model/preseason_role_threshold_v1/results.json`
- `reports/preseason-role-threshold-audit.md`
