# Preseason role scenario audit

**Verdict:** `material_counterfactual_reversal_requires_live_verification`  
**Production changed:** no

This checksum-bound audit applies declared conditional-DNP perturbations to the same residual and component worlds. They are sensitivity bounds, not estimated player probabilities.

## Evidence flags in the synthesis player pool

| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Watkins | Aston Villa | not_listed_three_plus | 7 | 0 | 0 | 0% | n/a |
| Adams | Bournemouth | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Enzo | Chelsea | not_listed_three_plus | 5 | 0 | 0 | 0% | n/a |
| McAteer | Ipswich Town | low_recent_start_share | 5 | 4 | 2 | 40% | no |
| Calvert-Lewin | Leeds | low_recent_start_share | 5 | 3 | 1 | 24% | no |
| Mukasa | Man City | low_recent_start_share | 3 | 3 | 0 | 0% | no |
| Haaland | Man City | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |
| Bruno Fernandes | Man Utd | low_recent_start_share | 5 | 2 | 0 | 0% | no |
| Yates | Nott'm Forest | low_recent_start_share | 6 | 4 | 3 | 34% | no |
| Senesi | Spurs | not_listed_three_plus | 5 | 0 | 0 | 0% | n/a |
| Bentancur | Spurs | not_listed_three_plus | 5 | 0 | 0 | 0% | n/a |
| Xhaka | Sunderland | not_listed_three_plus | 4 | 0 | 0 | 0% | n/a |

Uncovered clubs receive no negative factor. A player missing from a friendly lineup is not labelled injured or unavailable.

## Counterfactual results

Each leader was chosen on the selection sample. The table reports its paired holdout difference to the published configuration/squad in the independent residual and component families.

The configuration column exhaustively reoptimizes the published 15. The squad column is a screen over each synthesis finalist's frozen GW1 configuration; a screen reversal requires a deeper scenario-specific replay before it could be considered.

| Scenario | Configuration leader | Config residual | Config component | Frozen-config squad screen | Squad residual | Squad component |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| baseline | 3-4-3 · Bruno Fernandes | -0.039 [-0.048, -0.030] | +0.022 [+0.002, +0.043] | R-1ca68907f5 | +0.879 [+0.847, +0.911] | +1.169 [+1.095, +1.244] |
| moderate_role_stress | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-0aec115e14 | +0.901 [+0.865, +0.937] | +1.083 [+0.999, +1.168] |
| severe_role_stress | 4-3-3 · Bruno Fernandes | -0.003 [-0.010, +0.004] | -0.012 [-0.030, +0.007] | R-0aec115e14 | +0.945 [+0.906, +0.984] | +1.159 [+1.071, +1.247] |
| not_listed_dnp_boundary | 4-4-2 · Bruno Fernandes | -0.039 [-0.048, -0.030] | +0.022 [+0.001, +0.042] | R-0aec115e14 | +0.992 [+0.955, +1.030] | +1.199 [+1.113, +1.285] |

## Exhaustive challenger configuration replay

Every non-incumbent squad that wins the frozen-configuration screen is then given the same exhaustive 550-XI, bench-order, captain and vice search as the published 15. Its preselected configuration is compared with the incumbent's preselected configuration on the independent holdout.

| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline | R-1ca68907f5 | 5-3-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.952 [+0.919, +0.985] | +1.184 [+1.108, +1.260] | True |
| moderate_role_stress | R-0aec115e14 | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.950 [+0.914, +0.986] | +1.083 [+0.997, +1.169] | True |
| severe_role_stress | R-0aec115e14 | 4-4-2 · Bruno Fernandes | 4-3-3 · Bruno Fernandes | +0.977 [+0.938, +1.016] | +1.173 [+1.084, +1.263] | True |
| not_listed_dnp_boundary | R-0aec115e14 | 4-3-3 · Bruno Fernandes | 4-4-2 · Bruno Fernandes | +0.981 [+0.943, +1.019] | +1.179 [+1.090, +1.267] | True |

## Scenario details

### baseline

Production appearance worlds unchanged.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Hill, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-1ca68907f5`
- Squad changes: Hill, Groß, N.Williams out; Collins, McAteer, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### moderate_role_stress

Retain 75% of simulated appearances for three-plus-lineup absences and 90% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: N.Williams, Hill, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-0aec115e14`
- Squad changes: Hill, Groß, N.Williams out; Collins, Justin, E.Le Fée in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### severe_role_stress

Retain 50% of simulated appearances for three-plus-lineup absences and 75% for low-recent-start flags.

- XI: Watkins, Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, N.Williams
- Bench: Szoboszlai, Hill, Groß, Verbruggen
- Captain / vice: Bruno Fernandes / Tarkowski
- Squad leader: `R-0aec115e14`
- Squad changes: Hill, Groß, N.Williams out; Collins, Justin, E.Le Fée in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### not_listed_dnp_boundary

Force three-plus-lineup absence flags to DNP while leaving role-watch players at production appearance rates.

- XI: Truffert, Igor Thiago, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, N.Williams
- Bench: Hill, Groß, Watkins, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-0aec115e14`
- Squad changes: Hill, Groß, N.Williams out; Collins, Justin, E.Le Fée in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

## Operational rule

A supported stress reversal is a deadline verification trigger, not a promotion. Refresh official and preseason evidence, specify an attributable availability assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before changing squad, XI, bench or captaincy.

Selection used 5,000 worlds per family; holdout used 25,000.
