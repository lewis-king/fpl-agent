# GW1 global robust-search funnel

**Built:** 2026-08-09T07:32:19.648899+00:00  
**Status:** robust_challenger_provisional  
**Leader:** R-54af886244 · 5-3-2 · Bruno Fernandes captain · £23.0m bench

## Verdict

The robust funnel recommends **R-54af886244**. It was selected after 558,300 legal local/global combinations were reduced to 10,000 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-f3fe0f4df3 is +0.727 points (95% CI +0.546 to +0.909).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 143 | Prior residual and component optima |
| One-swap legal universe | 310,541 | Exhaustive same-position neighbours |
| Local two-swap universe | 538,172 | Neighbours of 128 proxy leaders |
| Distant MILP restarts | 256 | At least 3 swaps from every seed |
| Evolutionary squads | 19,872 | Legal crossover and mutation |
| Combined universe | 558,300 | Deduplicated local and global field |
| Discovery field | 10,000 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 308.18 | 0.00 | 30.0% |
| base evidence roll gw2 | 308.30 | 0.00 | 20.0% |
| base evidence fixed | 303.41 | 1.48 | 10.0% |
| base raw open | 285.06 | 2.09 | 10.0% |
| base anchored open | 310.75 | 0.06 | 15.0% |
| high goal open | 291.01 | 2.54 | 7.5% |
| high goal roll gw2 | 291.55 | 2.07 | 5.0% |
| high goal fixed | 290.05 | 2.63 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 1 | 308.18 | 1.20 | +0.00 | +0.00 to +0.00 |
| C007 | 37 | 307.10 | 2.42 | +1.08 | +0.90 to +1.25 |
| C009 | 3 | 307.62 | 1.61 | +0.55 | +0.37 to +0.74 |
| S001 | 16 | 308.07 | 2.05 | +0.10 | -0.01 to +0.22 |
| S028 | 64 | 298.31 | 16.87 | +9.87 | +9.61 to +10.13 |

## Global challenger audit

The remote search generated 256 optimizer squads and 19,872 legal evolutionary squads across 10 generations. 4,196 reached discovery, 32 reached exact component selection and 9 received the deep holdout.

Best remote finalist: **R-a03af10cce** · 4-3-3 · Bruno Fernandes captain · £22.5m bench · robust regret 1.163.
Leader minus remote challenger in the paired central holdout: +1.209 points (95% CI +1.044 to +1.373).


## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-54af886244 | 5-3-2 | £23.0m | 308.18 | 0.73 | 2.63 | 1.20 |
| 2 | R-f3fe0f4df3 | 4-3-3 | £22.5m | 307.45 | 1.11 | 2.50 | 1.46 |
| 3 | R-dc7de17def | 4-3-3 | £22.0m | 307.62 | 0.96 | 3.58 | 1.61 |
| 4 | R-6dcff8b173 | 4-3-3 | £22.0m | 307.48 | 1.04 | 3.43 | 1.64 |
| 5 | R-ad155aeb95 | 4-3-3 | £22.0m | 307.54 | 1.02 | 3.52 | 1.64 |
| 6 | R-144a048c90 | 4-3-3 | £22.5m | 307.90 | 1.02 | 3.55 | 1.65 |
| 7 | R-db5cc8d741 | 4-3-3 | £21.5m | 307.71 | 0.80 | 4.30 | 1.68 |
| 8 | R-55b796c314 | 4-3-3 | £22.5m | 307.49 | 1.21 | 3.09 | 1.68 |
| 9 | R-82f2d8901a | 4-3-3 | £22.0m | 307.44 | 1.08 | 3.49 | 1.69 |
| 10 | R-c78e39e675 | 4-3-3 | £22.0m | 307.45 | 1.08 | 3.55 | 1.70 |

## GW1 starting XI

- **GK:** Donnarumma
- **DEF:** Tarkowski (V), Collins, Maguire, Mukiele, Truffert
- **MID:** Bruno Fernandes (C), Mbeumo, Gibbs-White
- **FWD:** Igor Thiago, Watkins

## Bench

1. Calvert-Lewin (LEE, £6.0m)
2. Szoboszlai (LIV, £7.0m)
3. Xhaka (SUN, £5.5m)
4. Verbruggen (BHA, £4.5m)

## Interpretation

The robust rank is not simply the highest central mean. It minimizes a declared regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, anchored and high-scoring environments. The weights are explicit in the receipt and should be sensitivity-tested rather than treated as natural constants.

The discovery screen deliberately uses a cheap nominal-XI approximation. No candidate is promoted from that approximation: the shortlist is re-evaluated with exact autosubs and component simulation, followed by an independent deep holdout.

**Deadline rule:** Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios.
