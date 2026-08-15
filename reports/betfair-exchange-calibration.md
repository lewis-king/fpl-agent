# Betfair Exchange calibration and legal policy replay

Generated: 2026-08-10T10:14:32.032268+00:00

## Verdict

**REJECT** — validation selected a 20% exchange-component weight. The untouched 2025-26 continuous legal policy changed net points by -2 (-0.053/GW).

## Fixture calibration

| Season | Coverage | Exchange deviance | Average deviance | Internal deviance | Exchange CS Brier |
|---|---:|---:|---:|---:|---:|
| 2024-25 | 377/380 (99.2%) | 1.0631 | 1.0621 | 1.0933 | 0.1707 |
| 2025-26 | 360/380 (94.7%) | 1.0501 | 1.0472 | 1.0848 | 0.1794 |

The broad market average is a slightly stronger fixture forecaster than the single Betfair Exchange column on both seasons. Betfair still beats the internal fixture model on the untouched season, which is the relevant question when it is the only complete live market source.

## Validation-selected policy weight

| Weight | 2024/25 net points |
|---:|---:|
| 0.00 | 2222 |
| 0.10 | 2346 |
| 0.20 | 2404 |
| 0.30 | 2261 |
| 0.40 | 2295 |
| 0.50 | 2353 |
| 0.60 | 2352 |
| 0.70 | 2313 |
| 0.80 | 2130 |
| 0.90 | 2220 |
| 1.00 | 2248 |

## Untouched sequential path

- Incumbent: **2007** net points
- Betfair challenger: **2005** net points
- Broad market control at the same weight: **2005** net points
- Four-GW moving-block interval: **-3.316 to +3.026 points/GW**

## Production rule

Do not promote Betfair into decision authority: retain it as a visible shadow scenario because the held-out legal-policy gate failed.

Historical `BFE*` prices are non-closing exchange odds. The current anonymous feed uses delayed best-back/best-lay probability midpoints, so prospective receipts continue to monitor this near-but-not-identical method. Missing historical BFE fixtures use the market-average rate and are explicitly flagged; no closing columns are used.
