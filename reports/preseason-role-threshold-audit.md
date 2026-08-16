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
| 50.0% | 75.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.541 [+0.505, +0.577] | +0.881 [+0.801, +0.961] | True |
| 50.5% | 75.3% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.544 [+0.508, +0.580] | +0.883 [+0.803, +0.963] | True |
| 51.0% | 75.6% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.547 [+0.510, +0.583] | +0.888 [+0.808, +0.968] | True |
| 51.5% | 75.9% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.547 [+0.511, +0.583] | +0.894 [+0.813, +0.974] | True |
| 52.0% | 76.2% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.551 [+0.515, +0.587] | +0.898 [+0.818, +0.978] | True |
| 52.5% | 76.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.555 [+0.518, +0.591] | +0.898 [+0.818, +0.978] | True |
| 55.0% | 78.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.566 [+0.530, +0.603] | +0.913 [+0.833, +0.993] | True |
| 57.5% | 79.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 4-4-2 / Bruno Fernandes | +0.581 [+0.545, +0.617] | +0.928 [+0.848, +1.008] | True |
| 60.0% | 81.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.609 [+0.571, +0.647] | +0.882 [+0.800, +0.964] | True |
| 62.5% | 82.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.619 [+0.582, +0.656] | +0.894 [+0.812, +0.976] | True |
| 65.0% | 84.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.631 [+0.594, +0.668] | +0.908 [+0.826, +0.990] | True |
| 67.5% | 85.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.604 [+0.567, +0.640] | +0.944 [+0.862, +1.026] | True |
| 70.0% | 87.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.614 [+0.578, +0.651] | +0.951 [+0.869, +1.033] | True |
| 72.5% | 88.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.626 [+0.590, +0.662] | +0.966 [+0.884, +1.048] | True |
| 75.0% | 90.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.677 [+0.640, +0.713] | +0.960 [+0.878, +1.041] | True |

## Players affected by the sensitivity path

| Player | Team | Evidence flag | Production p(play) |
| --- | --- | --- | ---: |
| Watkins | Aston Villa | not_listed_three_plus | 88.9% |
| McAteer | Ipswich Town | low_recent_start_share | 86.4% |
| Tanaka | Leeds | low_recent_start_share | 87.7% |

## Operational rule

Do not change the published squad from this curve. Treat its supported bracket as a verification trigger: translate attributable deadline evidence into the forecast appearance model, rebuild forecasts, and rerun the complete GW1 decision pipeline before promotion.

Selection used 5,000 worlds per family; independent holdout used 25,000.
