# Preseason role scenario audit

**Verdict:** `material_counterfactual_reversal_requires_live_verification`  
**Production changed:** no

This checksum-bound audit applies declared conditional-DNP perturbations to the same residual and component worlds. They are sensitivity bounds, not estimated player probabilities.

## Evidence flags in the synthesis player pool

| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Watkins | Aston Villa | not_listed_three_plus | 8 | 0 | 0 | 0% | n/a |
| Taylor | Ipswich Town | not_listed_three_plus | 6 | 0 | 0 | 0% | n/a |
| McAteer | Ipswich Town | low_recent_start_share | 6 | 5 | 2 | 27% | no |
| Tanaka | Leeds | low_recent_start_share | 6 | 6 | 3 | 47% | no |
| Haaland | Man City | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Florentino | Ipswich Town | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |

Uncovered clubs receive no negative factor. A player missing from a friendly lineup is not labelled injured or unavailable.

## Counterfactual results

Each leader was chosen on the selection sample. The table reports its paired holdout difference to the published configuration/squad in the independent residual and component families.

The configuration column exhaustively reoptimizes the published 15. The squad column is a screen over each synthesis finalist's frozen GW1 configuration; a screen reversal requires a deeper scenario-specific replay before it could be considered.

| Scenario | Configuration leader | Config residual | Config component | Frozen-config squad screen | Squad residual | Squad component |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| baseline | 3-4-3 · Bruno Fernandes | +0.034 [+0.023, +0.045] | -0.013 [-0.040, +0.014] | R-1ca68907f5 | +0.733 [+0.700, +0.766] | +1.016 [+0.941, +1.092] |
| moderate_role_stress | 3-4-3 · Bruno Fernandes | +0.040 [+0.028, +0.052] | -0.010 [-0.039, +0.018] | R-1ca68907f5 | +0.659 [+0.624, +0.694] | +0.946 [+0.869, +1.023] |
| severe_role_stress | 4-4-2 · Bruno Fernandes | -0.004 [-0.022, +0.014] | -0.033 [-0.078, +0.013] | R-1ced0705f3 | +0.482 [+0.446, +0.519] | +0.849 [+0.771, +0.928] |
| not_listed_dnp_boundary | 4-3-3 · Bruno Fernandes | +0.042 [+0.029, +0.056] | -0.012 [-0.045, +0.021] | R-1ced0705f3 | +0.585 [+0.548, +0.622] | +0.968 [+0.887, +1.048] |

## Exhaustive challenger configuration replay

Every non-incumbent squad that wins the frozen-configuration screen is then given the same exhaustive 550-XI, bench-order, captain and vice search as the published 15. Its preselected configuration is compared with the incumbent's preselected configuration on the independent holdout.

| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline | R-1ca68907f5 | 5-3-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.721 [+0.686, +0.755] | +1.059 [+0.980, +1.137] | True |
| moderate_role_stress | R-1ca68907f5 | 5-3-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.622 [+0.586, +0.658] | +0.985 [+0.903, +1.066] | True |
| severe_role_stress | R-1ced0705f3 | 4-4-2 · Bruno Fernandes | 4-4-2 · Bruno Fernandes | +0.447 [+0.411, +0.482] | +0.922 [+0.844, +1.000] | True |
| not_listed_dnp_boundary | R-1ced0705f3 | 3-4-3 · Bruno Fernandes | 4-3-3 · Bruno Fernandes | +0.504 [+0.466, +0.541] | +1.020 [+0.938, +1.102] | True |

## Scenario details

### baseline

Production appearance worlds unchanged.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ca68907f5`
- Squad changes: Hill, N.Williams, Xhaka out; Collins, McAteer, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### moderate_role_stress

Retain 75% of simulated appearances for three-plus-lineup absences and 90% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ca68907f5`
- Squad changes: Hill, N.Williams, Xhaka out; Collins, McAteer, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### severe_role_stress

Retain 50% of simulated appearances for three-plus-lineup absences and 75% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, N.Williams
- Bench: Calvert-Lewin, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-1ced0705f3`
- Squad changes: Hill, Truffert, Xhaka out; Collins, Tanaka, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### not_listed_dnp_boundary

Force three-plus-lineup absence flags to DNP while leaving role-watch players at production appearance rates.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, N.Williams
- Bench: Szoboszlai, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ced0705f3`
- Squad changes: Hill, Truffert, Xhaka out; Collins, Tanaka, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

## Operational rule

A supported stress reversal is a deadline verification trigger, not a promotion. Refresh official and preseason evidence, specify an attributable availability assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before changing squad, XI, bench or captaincy.

Selection used 5,000 worlds per family; holdout used 25,000.
