# Preseason role scenario audit

**Verdict:** `material_counterfactual_reversal_requires_live_verification`  
**Production changed:** no

This checksum-bound audit applies declared conditional-DNP perturbations to the same residual and component worlds. They are sensitivity bounds, not estimated player probabilities.

## Evidence flags in the synthesis player pool

| Player | Team | Flag | Eligible | Listed | Starts | Recent start share | Latest start |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Saka | Arsenal | low_recent_start_share | 5 | 1 | 0 | 0% | no |
| Rice | Arsenal | low_recent_start_share | 5 | 1 | 0 | 0% | no |
| Zubimendi | Arsenal | low_recent_start_share | 5 | 1 | 0 | 0% | no |
| Gyökeres | Arsenal | low_recent_start_share | 5 | 5 | 3 | 45% | no |
| Watkins | Aston Villa | not_listed_three_plus | 8 | 0 | 0 | 0% | n/a |
| Adams | Bournemouth | not_listed_three_plus | 4 | 0 | 0 | 0% | n/a |
| Enzo | Chelsea | low_recent_start_share | 6 | 1 | 0 | 0% | no |
| Hughes | Crystal Palace | low_recent_start_share | 7 | 6 | 4 | 35% | no |
| Dowell | Hull City | low_recent_start_share | 5 | 5 | 1 | 11% | no |
| McAteer | Ipswich Town | low_recent_start_share | 6 | 5 | 2 | 27% | no |
| Cherki | Man City | low_recent_start_share | 4 | 1 | 0 | 0% | no |
| Neave | Newcastle | low_recent_start_share | 6 | 6 | 2 | 13% | no |
| Pedro Porro | Spurs | not_listed_three_plus | 7 | 0 | 0 | 0% | n/a |
| Florentino | Ipswich Town | not_listed_three_plus | 3 | 0 | 0 | 0% | n/a |

Uncovered clubs receive no negative factor. A player missing from a friendly lineup is not labelled injured or unavailable.

## Counterfactual results

Each leader was chosen on the selection sample. The table reports its paired holdout difference to the published configuration/squad in the independent residual and component families.

The configuration column exhaustively reoptimizes the published 15. The squad column is a screen over each synthesis finalist's frozen GW1 configuration; a screen reversal requires a deeper scenario-specific replay before it could be considered.

| Scenario | Configuration leader | Config residual | Config component | Frozen-config squad screen | Squad residual | Squad component |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| baseline | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-6958482d6f | +0.790 [+0.757, +0.823] | -0.301 [-0.392, -0.210] |
| moderate_role_stress | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-6958482d6f | +0.944 [+0.911, +0.977] | -0.059 [-0.149, +0.030] |
| severe_role_stress | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-6958482d6f | +1.104 [+1.072, +1.137] | +0.175 [+0.086, +0.263] |
| not_listed_dnp_boundary | 3-4-3 · Bruno Fernandes | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | R-6958482d6f | +1.395 [+1.363, +1.426] | +0.668 [+0.583, +0.752] |

## Exhaustive challenger configuration replay

Every non-incumbent squad that wins the frozen-configuration screen is then given the same exhaustive 550-XI, bench-order, captain and vice search as the published 15. Its preselected configuration is compared with the incumbent's preselected configuration on the independent holdout.

| Scenario | Challenger | Challenger shape/captain | Incumbent shape/captain | Residual delta | Component delta | Supported |
| --- | --- | --- | --- | ---: | ---: | --- |
| baseline | R-6958482d6f | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.512 [+0.486, +0.539] | +0.113 [+0.037, +0.190] | True |
| moderate_role_stress | R-6958482d6f | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.666 [+0.640, +0.693] | +0.355 [+0.280, +0.430] | True |
| severe_role_stress | R-6958482d6f | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +0.826 [+0.800, +0.852] | +0.589 [+0.516, +0.662] | True |
| not_listed_dnp_boundary | R-6958482d6f | 4-4-2 · Bruno Fernandes | 3-4-3 · Bruno Fernandes | +1.117 [+1.092, +1.141] | +1.082 [+1.014, +1.151] | True |

## Scenario details

### baseline

Production appearance worlds unchanged.

- XI: Watkins, Igor Thiago, Lacroix, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: Milenković, Truffert, McAteer, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-6958482d6f`
- Squad changes: Watkins, Truffert, Milenković out; Gabriel Magalhães, Hirst, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: False
- Deep squad support: True

### moderate_role_stress

Retain 75% of simulated appearances for three-plus-lineup absences and 90% for low-recent-start flags.

- XI: Watkins, Igor Thiago, Lacroix, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: Milenković, Truffert, McAteer, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-6958482d6f`
- Squad changes: Watkins, Truffert, Milenković out; Gabriel Magalhães, Hirst, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: False
- Deep squad support: True

### severe_role_stress

Retain 50% of simulated appearances for three-plus-lineup absences and 75% for low-recent-start flags.

- XI: Watkins, Igor Thiago, Lacroix, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo
- Bench: Milenković, Truffert, McAteer, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-6958482d6f`
- Squad changes: Watkins, Truffert, Milenković out; Gabriel Magalhães, Hirst, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

### not_listed_dnp_boundary

Force three-plus-lineup absence flags to DNP while leaving role-watch players at production appearance rates.

- XI: Watkins, Igor Thiago, Lacroix, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Bruno Fernandes, Mbeumo, Milenković
- Bench: Maguire, Truffert, McAteer, Verbruggen
- Captain / vice: Bruno Fernandes / Mbeumo
- Squad leader: `R-6958482d6f`
- Squad changes: Watkins, Truffert, Milenković out; Gabriel Magalhães, Hirst, Senesi in
- Cross-family configuration support: False
- Frozen-config squad screen support: True
- Deep squad support: True

## Operational rule

A supported stress reversal is a deadline verification trigger, not a promotion. Refresh official and preseason evidence, specify an attributable availability assumption, rebuild forecasts and rerun the complete GW1 decision pipeline before changing squad, XI, bench or captaincy.

Selection used 5,000 worlds per family; holdout used 25,000.
