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
| 50.0% | 75.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 4-3-3 / Bruno Fernandes | +0.970 [+0.931, +1.010] | +1.187 [+1.097, +1.277] | True |
| 50.5% | 75.3% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.966 [+0.927, +1.005] | +1.154 [+1.063, +1.245] | True |
| 51.0% | 75.6% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.966 [+0.927, +1.006] | +1.148 [+1.057, +1.239] | True |
| 51.5% | 75.9% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.965 [+0.926, +1.004] | +1.150 [+1.059, +1.241] | True |
| 52.0% | 76.2% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.965 [+0.926, +1.004] | +1.147 [+1.057, +1.238] | True |
| 52.5% | 76.5% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.963 [+0.924, +1.003] | +1.145 [+1.054, +1.236] | True |
| 55.0% | 78.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.962 [+0.923, +1.000] | +1.134 [+1.043, +1.224] | True |
| 57.5% | 79.5% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.962 [+0.923, +1.000] | +1.123 [+1.032, +1.213] | True |
| 60.0% | 81.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.959 [+0.921, +0.997] | +1.117 [+1.027, +1.207] | True |
| 62.5% | 82.5% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.960 [+0.922, +0.998] | +1.110 [+1.020, +1.200] | True |
| 65.0% | 84.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.956 [+0.919, +0.994] | +1.099 [+1.009, +1.189] | True |
| 67.5% | 85.5% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.959 [+0.922, +0.997] | +1.083 [+0.993, +1.172] | True |
| 70.0% | 87.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.955 [+0.918, +0.993] | +1.068 [+0.979, +1.157] | True |
| 72.5% | 88.5% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.940 [+0.903, +0.977] | +1.060 [+0.973, +1.147] | True |
| 75.0% | 90.0% | `R-0aec115e14` | Hill, Groß, N.Williams → Collins, Justin, E.Le Fée | 4-4-2 / Bruno Fernandes | 3-4-3 / Bruno Fernandes | +0.937 [+0.900, +0.973] | +1.053 [+0.966, +1.139] | True |

## Players affected by the sensitivity path

| Player | Team | Evidence flag | Production p(play) |
| --- | --- | --- | ---: |
| Watkins | Aston Villa | not_listed_three_plus | 88.9% |
| McAteer | Ipswich Town | low_recent_start_share | 86.4% |
| Calvert-Lewin | Leeds | low_recent_start_share | 90.1% |
| Bruno Fernandes | Man Utd | low_recent_start_share | 93.9% |
| Senesi | Spurs | not_listed_three_plus | 92.9% |

## Operational rule

Do not change the published squad from this curve. Treat its supported bracket as a verification trigger: translate attributable deadline evidence into the forecast appearance model, rebuild forecasts, and rerun the complete GW1 decision pipeline before promotion.

Selection used 5,000 worlds per family; independent holdout used 25,000.
