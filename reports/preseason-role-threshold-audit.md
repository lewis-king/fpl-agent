# Preseason availability-retention threshold audit

**Verdict:** `supported_to_top_of_tested_path`  
**Production changed:** no

Fresh selection simulations choose the best configuration within each squad's preselected endpoint portfolio. Independent holdout simulations then compare the best challenger with the incumbent at each threshold.

This is a coupled sensitivity path over configurations discovered by prior exhaustive endpoint searches, not a new exhaustive squad search at every grid point and not an availability probability model.

## Decision boundary

The mildest tested point still supporting the challenger retains 75.0% of simulated appearances for three-plus-lineup absences and 90.0% for role-watch players.

Support persists to the mildest end of the tested path.

These factors thin appearances already present in the production simulation. They are not direct estimates of real availability.

## Threshold curve

| Not-listed retention | Role-watch retention | Challenger | Changes | Challenger shape / captain | Incumbent shape / captain | Residual delta | Component delta | Supported |
| ---: | ---: | --- | --- | --- | --- | ---: | ---: | --- |
| 50.0% | 75.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.826 [+0.799, +0.852] | +0.576 [+0.504, +0.648] | True |
| 50.5% | 75.3% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.823 [+0.797, +0.850] | +0.569 [+0.497, +0.641] | True |
| 51.0% | 75.6% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.820 [+0.794, +0.847] | +0.563 [+0.491, +0.635] | True |
| 51.5% | 75.9% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.816 [+0.790, +0.843] | +0.553 [+0.481, +0.625] | True |
| 52.0% | 76.2% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.813 [+0.787, +0.840] | +0.545 [+0.472, +0.617] | True |
| 52.5% | 76.5% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.811 [+0.784, +0.837] | +0.539 [+0.466, +0.611] | True |
| 55.0% | 78.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.796 [+0.770, +0.823] | +0.505 [+0.432, +0.577] | True |
| 57.5% | 79.5% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.779 [+0.753, +0.806] | +0.483 [+0.410, +0.556] | True |
| 60.0% | 81.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.762 [+0.736, +0.789] | +0.459 [+0.386, +0.532] | True |
| 62.5% | 82.5% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.746 [+0.719, +0.772] | +0.428 [+0.355, +0.501] | True |
| 65.0% | 84.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.730 [+0.704, +0.757] | +0.398 [+0.325, +0.471] | True |
| 67.5% | 85.5% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.714 [+0.687, +0.740] | +0.382 [+0.309, +0.455] | True |
| 70.0% | 87.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.701 [+0.675, +0.728] | +0.352 [+0.279, +0.426] | True |
| 72.5% | 88.5% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.687 [+0.661, +0.714] | +0.326 [+0.252, +0.400] | True |
| 75.0% | 90.0% | `R-6958482d6f` | Watkins, Truffert, Milenković → Gabriel Magalhães, Hirst, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.673 [+0.646, +0.699] | +0.309 [+0.235, +0.383] | True |

## Players affected by the sensitivity path

| Player | Team | Evidence flag | Production p(play) |
| --- | --- | --- | ---: |
| Watkins | Aston Villa | not_listed_three_plus | 88.9% |
| McAteer | Ipswich Town | low_recent_start_share | 86.5% |

## Operational rule

Do not change the published squad from this curve. Treat its supported bracket as a verification trigger: translate attributable deadline evidence into the forecast appearance model, rebuild forecasts, and rerun the complete GW1 decision pipeline before promotion.

Selection used 5,000 worlds per family; independent holdout used 25,000.
