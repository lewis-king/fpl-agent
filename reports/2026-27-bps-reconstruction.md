# 2026/27 Bonus Points System reconstruction

**Built:** 2026-08-03T16:53:06.314692+00:00  
**Monte Carlo worlds:** 400  
**Promotion gate:** PASS

## What is proven

The tie-aware control reproduces 380 of 380 2025/26 match allocations exactly and all 2,415 awarded bonus points.

The CBI change is exact at player-match level: `floor(CBI / 3) - floor(CBI / 2)`.

## The missing tackled event

The public 2025/26 archive does not contain the tackled event. A GPU Poisson model was trained on 2016/17 and 2017/18 and tested strictly forward on 2018/19.

- Row MAE: 0.440 vs 0.472 baseline.
- Active-player season MAE: 11.36 vs 15.20 baseline.
- Active-player season rank correlation: 0.892.

The official 2025/26 top-ten and defender tables anchor the modern scale. Their published season totals are exact; match placement remains simulated from the model.

## Counterfactual effect

| Position | Appearances | Mean bonus delta/appearance | Rows with >5% change chance |
| --- | ---: | ---: | ---: |
| GK | 767 | -0.046 | 10.2% |
| DEF | 3,950 | -0.011 | 11.5% |
| MID | 5,347 | +0.011 | 10.3% |
| FWD | 1,428 | +0.007 | 9.3% |

## Boundary of confidence

This is a promoted correction prior, not a claim that the complete Opta BPS feed has been recreated. Unknown goalkeeper save locations and unpublished big-chance saves make the displayed GK counterfactual a lower bound, so goalkeeper deltas are not promoted into live forecasts. The live simulator keeps match-level bonus conservation and applies the promoted outfield deltas only to bonus propensity.

Official source: https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system
