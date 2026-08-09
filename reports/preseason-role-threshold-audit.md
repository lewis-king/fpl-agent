# Preseason availability-retention threshold audit

**Verdict:** `no_supported_challenger_on_tested_path`  
**Production changed:** no

Fresh selection simulations choose the best configuration within each squad's preselected endpoint portfolio. Independent holdout simulations then compare the best challenger with the incumbent at each threshold.

This is a coupled sensitivity path over configurations discovered by prior exhaustive endpoint searches, not a new exhaustive squad search at every grid point and not an availability probability model.

## Decision boundary

No challenger has cross-family support on the tested path.

These factors thin appearances already present in the production simulation. They are not direct estimates of real availability.

## Threshold curve

| Not-listed retention | Role-watch retention | Challenger | Changes | Challenger shape / captain | Incumbent shape / captain | Residual delta | Component delta | Supported |
| ---: | ---: | --- | --- | --- | --- | ---: | ---: | --- |
| 50.0% | 75.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.034 [+0.015, +0.052] | +0.005 [-0.032, +0.043] | False |
| 50.5% | 75.3% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.034 [+0.016, +0.052] | +0.003 [-0.034, +0.041] | False |
| 51.0% | 75.6% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.034 [+0.015, +0.052] | +0.004 [-0.033, +0.042] | False |
| 51.5% | 75.9% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.033 [+0.015, +0.051] | +0.005 [-0.032, +0.042] | False |
| 52.0% | 76.2% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.032 [+0.014, +0.050] | +0.003 [-0.034, +0.040] | False |
| 52.5% | 76.5% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.033 [+0.015, +0.051] | +0.004 [-0.033, +0.040] | False |
| 55.0% | 78.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.032 [+0.014, +0.049] | +0.001 [-0.035, +0.037] | False |
| 57.5% | 79.5% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.025 [+0.009, +0.042] | +0.008 [-0.027, +0.043] | False |
| 60.0% | 81.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.023 [+0.007, +0.040] | +0.005 [-0.029, +0.039] | False |
| 62.5% | 82.5% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.021 [+0.005, +0.037] | +0.004 [-0.029, +0.037] | False |
| 65.0% | 84.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.019 [+0.004, +0.034] | +0.001 [-0.031, +0.032] | False |
| 67.5% | 85.5% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.018 [+0.003, +0.032] | -0.001 [-0.032, +0.029] | False |
| 70.0% | 87.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.016 [+0.002, +0.031] | -0.003 [-0.033, +0.027] | False |
| 72.5% | 88.5% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.018 [+0.005, +0.032] | +0.002 [-0.027, +0.030] | False |
| 75.0% | 90.0% | `R-0145b125ed` | Groß → Moisés Caicedo | 5-3-2 / Bruno Fernandes | 5-3-2 / Bruno Fernandes | +0.016 [+0.003, +0.029] | +0.000 [-0.027, +0.028] | False |

## Players affected by the sensitivity path

| Player | Team | Evidence flag | Production p(play) |
| --- | --- | --- | ---: |
| Watkins | Aston Villa | not_listed_three_plus | 88.9% |
| Truffert | Bournemouth | low_recent_start_share | 92.3% |
| Calvert-Lewin | Leeds | low_recent_start_share | 90.1% |
| Bruno Fernandes | Man Utd | not_listed_three_plus | 93.9% |

## Operational rule

Do not change the published squad from this curve. Treat its supported bracket as a verification trigger: translate attributable deadline evidence into the forecast appearance model, rebuild forecasts, and rerun the complete GW1 decision pipeline before promotion.

Selection used 5,000 worlds per family; independent holdout used 25,000.
