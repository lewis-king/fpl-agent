# GW1 robust-search funnel

**Built:** 2026-08-03T18:57:26.557740+00:00  
**Status:** robust_challenger_provisional  
**Leader:** R-dc7de17def · 4-3-3 · Bruno Fernandes captain · £22.0m bench

## Verdict

The robust funnel recommends **R-dc7de17def**. It was selected after 542,246 legal seed/neighbourhood combinations were reduced to 10,000 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-82f2d8901a is +0.101 points (95% CI +0.078 to +0.124).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 149 | Prior residual and component optima |
| One-swap legal universe | 321,629 | Exhaustive same-position neighbours |
| Two-swap expanded universe | 542,246 | Neighbours of 128 proxy leaders |
| Discovery field | 10,000 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 307.57 | 0.22 | 30.0% |
| base evidence roll gw2 | 307.57 | 0.35 | 20.0% |
| base evidence fixed | 304.82 | 0.04 | 10.0% |
| base raw open | 289.25 | 0.67 | 10.0% |
| base anchored open | 309.61 | 0.60 | 15.0% |
| high goal open | 295.76 | 0.75 | 7.5% |
| high goal roll gw2 | 295.76 | 0.75 | 5.0% |
| high goal fixed | 290.94 | 0.76 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 16 | 307.69 | 1.07 | -0.12 | -0.30 to +0.06 |
| C007 | 18 | 307.79 | 1.70 | -0.22 | -0.39 to -0.05 |
| S001 | 55 | 306.70 | 4.73 | +0.88 | +0.67 to +1.09 |
| S028 | 39 | 307.33 | 3.39 | +0.25 | +0.09 to +0.41 |

## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-dc7de17def | 4-3-3 | £22.0m | 307.57 | 0.41 | 0.76 | 0.50 |
| 2 | R-82f2d8901a | 4-3-3 | £22.0m | 307.47 | 0.47 | 0.71 | 0.53 |
| 3 | R-6dcff8b173 | 4-3-3 | £22.0m | 307.47 | 0.47 | 0.72 | 0.54 |
| 4 | R-c78e39e675 | 4-3-3 | £22.0m | 307.44 | 0.51 | 0.74 | 0.57 |
| 5 | R-060855a345 | 4-3-3 | £22.0m | 307.42 | 0.54 | 0.80 | 0.61 |
| 6 | R-a4a9463256 | 4-3-3 | £22.0m | 307.36 | 0.56 | 0.83 | 0.63 |
| 7 | R-dcfdefb356 | 4-3-3 | £22.0m | 307.36 | 0.58 | 0.82 | 0.64 |
| 8 | R-1cd7a99f1d | 4-3-3 | £22.0m | 307.34 | 0.57 | 0.86 | 0.64 |
| 9 | R-a61d88b4b8 | 4-3-3 | £22.0m | 307.38 | 0.58 | 0.85 | 0.65 |
| 10 | R-5606b39d3c | 4-3-3 | £22.0m | 307.38 | 0.58 | 0.85 | 0.65 |

## GW1 starting XI

- **GK:** Donnarumma
- **DEF:** Tarkowski (V), Maguire, Senesi, Truffert
- **MID:** Bruno Fernandes (C), Mbeumo, Gibbs-White
- **FWD:** Igor Thiago, Watkins, Calvert-Lewin

## Bench

1. Szoboszlai (LIV, £7.0m)
2. Hill (BOU, £5.5m)
3. Tanaka (LEE, £5.0m)
4. Verbruggen (BHA, £4.5m)

## Interpretation

The robust rank is not simply the highest central mean. It minimizes a declared regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, anchored and high-scoring environments. The weights are explicit in the receipt and should be sensitivity-tested rather than treated as natural constants.

The discovery screen deliberately uses a cheap nominal-XI approximation. No candidate is promoted from that approximation: the shortlist is re-evaluated with exact autosubs and component simulation, followed by an independent deep holdout.

**Deadline rule:** Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios.
