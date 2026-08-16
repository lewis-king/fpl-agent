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
| 50.0% | 75.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.530 [+0.493, +0.567] | +0.771 [+0.694, +0.847] | True |
| 50.5% | 75.3% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.533 [+0.497, +0.570] | +0.773 [+0.696, +0.850] | True |
| 51.0% | 75.6% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.537 [+0.500, +0.573] | +0.774 [+0.697, +0.850] | True |
| 51.5% | 75.9% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.538 [+0.502, +0.575] | +0.778 [+0.701, +0.854] | True |
| 52.0% | 76.2% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.542 [+0.506, +0.578] | +0.785 [+0.708, +0.861] | True |
| 52.5% | 76.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.546 [+0.509, +0.582] | +0.784 [+0.707, +0.860] | True |
| 55.0% | 78.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.556 [+0.520, +0.592] | +0.796 [+0.720, +0.873] | True |
| 57.5% | 79.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.572 [+0.536, +0.608] | +0.810 [+0.734, +0.886] | True |
| 60.0% | 81.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.627 [+0.591, +0.663] | +0.818 [+0.740, +0.895] | True |
| 62.5% | 82.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 5-3-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.597 [+0.561, +0.633] | +0.824 [+0.747, +0.900] | True |
| 65.0% | 84.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.567 [+0.532, +0.602] | +0.837 [+0.762, +0.913] | True |
| 67.5% | 85.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.574 [+0.539, +0.609] | +0.854 [+0.779, +0.929] | True |
| 70.0% | 87.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.585 [+0.550, +0.620] | +0.874 [+0.799, +0.949] | True |
| 72.5% | 88.5% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.595 [+0.560, +0.629] | +0.886 [+0.811, +0.961] | True |
| 75.0% | 90.0% | `R-1ca68907f5` | Hill, N.Williams, Xhaka → Collins, McAteer, Senesi | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.604 [+0.570, +0.639] | +0.892 [+0.817, +0.967] | True |

## Players affected by the sensitivity path

| Player | Team | Evidence flag | Production p(play) |
| --- | --- | --- | ---: |
| Watkins | Aston Villa | not_listed_three_plus | 88.9% |
| McAteer | Ipswich Town | low_recent_start_share | 86.4% |
| Tanaka | Leeds | low_recent_start_share | 87.7% |

## Operational rule

Do not change the published squad from this curve. Treat its supported bracket as a verification trigger: translate attributable deadline evidence into the forecast appearance model, rebuild forecasts, and rerun the complete GW1 decision pipeline before promotion.

Selection used 5,000 worlds per family; independent holdout used 25,000.
