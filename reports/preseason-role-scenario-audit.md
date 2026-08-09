# Preseason role scenario audit

**Verdict:** `material_counterfactual_reversal_requires_live_verification`  
**Production changed:** no

This checksum-bound audit applies declared conditional-DNP perturbations to the same residual and component worlds. They are sensitivity bounds, not estimated player probabilities.

## Evidence flags in the synthesis player pool

| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Watkins | Aston Villa | not_listed_three_plus | 6 | 0 | 0 | 0% | n/a |
| Hill | Bournemouth | low_recent_start_share | 2 | 2 | 1 | 39% | no |
| Truffert | Bournemouth | low_recent_start_share | 2 | 2 | 1 | 39% | no |
| Collins | Brentford | no_confirmed_club_lineups | 0 | 0 | 0 | n/a | n/a |
| Igor Thiago | Brentford | no_confirmed_club_lineups | 0 | 0 | 0 | n/a | n/a |
| Verbruggen | Brighton | no_confirmed_club_lineups | 0 | 0 | 0 | n/a | n/a |
| Groß | Brighton | no_confirmed_club_lineups | 0 | 0 | 0 | n/a | n/a |
| Diego Gómez | Brighton | no_confirmed_club_lineups | 0 | 0 | 0 | n/a | n/a |
| Enzo | Chelsea | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Lerma | Crystal Palace | not_listed_three_plus | 6 | 0 | 0 | 0% | n/a |
| Calvert-Lewin | Leeds | low_recent_start_share | 3 | 1 | 0 | 0% | no |
| Virgil | Liverpool | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Mukasa | Man City | low_recent_start_share | 2 | 2 | 0 | 0% | no |
| Bruno Fernandes | Man Utd | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Senesi | Spurs | not_listed_three_plus | 4 | 0 | 0 | 0% | n/a |
| Richarlison | Spurs | low_recent_start_share | 4 | 4 | 1 | 27% | no |
| Xhaka | Sunderland | not_listed_three_plus | 4 | 0 | 0 | 0% | n/a |

Uncovered clubs receive no negative factor. A player missing from a friendly lineup is not labelled injured or unavailable.

## Counterfactual results

Each leader was chosen on the selection sample. The table reports its paired holdout difference to the published configuration/squad in the independent residual and component families.

The configuration column exhaustively reoptimizes the published 15. The squad column is a screen over each synthesis finalist's frozen GW1 configuration; a screen reversal requires a deeper scenario-specific replay before it could be considered.

| Scenario | Configuration leader | Config residual | Config component | Frozen-config squad screen | Squad residual | Squad component |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| baseline | 5-3-2 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-0145b125ed | +0.004 [-0.004, +0.012] | -0.016 [-0.033, +0.001] |
| moderate_role_stress | 5-3-2 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-e80223d1fc | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| severe_role_stress | 5-3-2 · Bruno Fernandes | -0.042 [-0.052, -0.032] | -0.033 [-0.057, -0.008] | R-e80223d1fc | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| not_listed_dnp_boundary | 4-3-3 · Tarkowski | +0.405 [+0.387, +0.422] | +0.410 [+0.388, +0.432] | R-0145b125ed | +0.025 [+0.003, +0.046] | -0.024 [-0.067, +0.020] |

## Exhaustive challenger configuration replay

Every non-incumbent squad that wins the frozen-configuration screen is then given the same exhaustive 550-XI, bench-order, captain and vice search as the published 15. Its preselected configuration is compared with the incumbent's preselected configuration on the independent holdout.

| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline | R-0145b125ed | 5-3-2 · Bruno Fernandes | 5-3-2 · Bruno Fernandes | +0.004 [-0.004, +0.012] | -0.016 [-0.033, +0.001] | False |
| not_listed_dnp_boundary | R-0145b125ed | 5-2-3 · Tarkowski | 4-3-3 · Tarkowski | +0.025 [+0.003, +0.046] | -0.024 [-0.068, +0.019] | False |

## Scenario details

### baseline

Production appearance worlds unchanged.

- XI: Watkins, Truffert, Collins, Igor Thiago, Tarkowski, Donnarumma, Maguire, Bruno Fernandes, Mbeumo, Gibbs-White, Mukiele
- Bench: Calvert-Lewin, Szoboszlai, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-0145b125ed`
- Squad changes: Groß out; Moisés Caicedo in
- Cross-family configuration support: False
- Frozen-config squad screen support: False
- Deep squad support: False

### moderate_role_stress

Retain 75% of simulated appearances for three-plus-lineup absences and 90% for low-recent-start flags.

- XI: Watkins, Truffert, Collins, Igor Thiago, Tarkowski, Donnarumma, Maguire, Bruno Fernandes, Mbeumo, Gibbs-White, Mukiele
- Bench: Calvert-Lewin, Szoboszlai, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-e80223d1fc`
- Squad changes: none out; none in
- Cross-family configuration support: False
- Frozen-config squad screen support: False
- Deep squad support: not required

### severe_role_stress

Retain 50% of simulated appearances for three-plus-lineup absences and 75% for low-recent-start flags.

- XI: Watkins, Truffert, Collins, Igor Thiago, Tarkowski, Donnarumma, Maguire, Bruno Fernandes, Mbeumo, Gibbs-White, Mukiele
- Bench: Szoboszlai, Calvert-Lewin, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-e80223d1fc`
- Squad changes: none out; none in
- Cross-family configuration support: False
- Frozen-config squad screen support: False
- Deep squad support: not required

### not_listed_dnp_boundary

Force three-plus-lineup absence flags to DNP while leaving role-watch players at production appearance rates.

- XI: Watkins, Truffert, Collins, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Maguire, Mbeumo, Gibbs-White
- Bench: Mukiele, Bruno Fernandes, Groß, Verbruggen
- Captain / vice: Tarkowski / Igor Thiago
- Squad leader: `R-0145b125ed`
- Squad changes: Groß out; Moisés Caicedo in
- Cross-family configuration support: True
- Frozen-config squad screen support: False
- Deep squad support: False

## Operational rule

A supported stress reversal is a deadline verification trigger, not a promotion. Refresh official and preseason evidence, specify an attributable availability assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before changing squad, XI, bench or captaincy.

Selection used 5,000 worlds per family; holdout used 25,000.
