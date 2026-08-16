# Preseason role scenario audit

**Verdict:** `material_counterfactual_reversal_requires_live_verification`  
**Production changed:** no

This checksum-bound audit applies declared conditional-DNP perturbations to the same residual and component worlds. They are sensitivity bounds, not estimated player probabilities.

## Evidence flags in the synthesis player pool

| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Watkins | Aston Villa | not_listed_three_plus | 8 | 0 | 0 | 0% | n/a |
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
| baseline | 3-4-3 · Bruno Fernandes | +0.034 [+0.023, +0.045] | -0.008 [-0.034, +0.019] | R-1ced0705f3 | +0.687 [+0.655, +0.720] | +0.922 [+0.847, +0.998] |
| moderate_role_stress | 3-4-3 · Bruno Fernandes | +0.040 [+0.028, +0.052] | -0.011 [-0.039, +0.018] | R-1ced0705f3 | +0.611 [+0.576, +0.645] | +0.871 [+0.794, +0.948] |
| severe_role_stress | 3-4-3 · Bruno Fernandes | +0.040 [+0.028, +0.052] | -0.021 [-0.051, +0.009] | R-1ca68907f5 | +0.549 [+0.512, +0.585] | +0.761 [+0.684, +0.839] |
| not_listed_dnp_boundary | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-1ced0705f3 | +0.588 [+0.551, +0.625] | +0.858 [+0.778, +0.939] |

## Exhaustive challenger configuration replay

Every non-incumbent squad that wins the frozen-configuration screen is then given the same exhaustive 550-XI, bench-order, captain and vice search as the published 15. Its preselected configuration is compared with the incumbent's preselected configuration on the independent holdout.

| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline | R-1ced0705f3 | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.653 [+0.621, +0.685] | +0.930 [+0.855, +1.005] | True |
| moderate_role_stress | R-1ced0705f3 | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.571 [+0.537, +0.605] | +0.882 [+0.805, +0.958] | True |
| severe_role_stress | R-1ca68907f5 | 5-3-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.539 [+0.502, +0.575] | +0.768 [+0.691, +0.845] | True |
| not_listed_dnp_boundary | R-1ced0705f3 | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.588 [+0.551, +0.625] | +0.858 [+0.778, +0.939] | True |

## Scenario details

### baseline

Production appearance worlds unchanged.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ced0705f3`
- Squad changes: Hill, Truffert, Xhaka out; Collins, Tanaka, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### moderate_role_stress

Retain 75% of simulated appearances for three-plus-lineup absences and 90% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ced0705f3`
- Squad changes: Hill, Truffert, Xhaka out; Collins, Tanaka, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### severe_role_stress

Retain 50% of simulated appearances for three-plus-lineup absences and 75% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Xhaka, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ca68907f5`
- Squad changes: Hill, N.Williams, Xhaka out; Collins, McAteer, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### not_listed_dnp_boundary

Force three-plus-lineup absence flags to DNP while leaving role-watch players at production appearance rates.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, Xhaka
- Bench: Szoboszlai, N.Williams, Hill, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-1ced0705f3`
- Squad changes: Hill, Truffert, Xhaka out; Collins, Tanaka, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

## Operational rule

A supported stress reversal is a deadline verification trigger, not a promotion. Refresh official and preseason evidence, specify an attributable availability assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before changing squad, XI, bench or captaincy.

Selection used 5,000 worlds per family; holdout used 25,000.
