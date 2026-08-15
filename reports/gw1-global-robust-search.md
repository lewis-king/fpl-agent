# GW1 global robust-search funnel

**Built:** 2026-08-15T16:02:39.018380+00:00<br>
**Status:** robust_challenger_provisional<br>
**Leader:** R-083607ec8c · 3-4-3 · Bruno Fernandes captain · £20.5m bench

## Verdict

The robust funnel recommends **R-083607ec8c**. It was selected after 554,062 legal local/global combinations were reduced to 10,000 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-4e8a455b0e is +0.212 points (95% CI +0.033 to +0.392).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 139 | Prior residual and component optima |
| One-swap legal universe | 297,343 | Exhaustive same-position neighbours |
| Local two-swap universe | 533,836 | Neighbours of 128 proxy leaders |
| Distant MILP restarts | 256 | At least 3 swaps from every seed |
| Evolutionary squads | 19,970 | Legal crossover and mutation |
| Combined universe | 554,062 | Deduplicated local and global field |
| Discovery field | 10,000 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 308.92 | 0.44 | 30.0% |
| base evidence roll gw2 | 308.92 | 0.44 | 20.0% |
| base evidence fixed | 305.62 | 0.59 | 10.0% |
| base raw open | 286.02 | 2.11 | 10.0% |
| base anchored open | 311.47 | 0.67 | 15.0% |
| high goal open | 292.33 | 2.06 | 7.5% |
| high goal roll gw2 | 292.33 | 0.73 | 5.0% |
| high goal fixed | 289.50 | 3.51 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 12 | 309.36 | 2.42 | -0.44 | -0.61 to -0.26 |
| C007 | 12 | 309.36 | 2.42 | -0.44 | -0.61 to -0.26 |
| C009 | 5 | 308.53 | 2.05 | +0.39 | +0.23 to +0.56 |
| S001 | 12 | 309.36 | 2.42 | -0.44 | -0.61 to -0.26 |
| S028 | 64 | 300.73 | 15.08 | +8.19 | +7.98 to +8.41 |

## Global challenger audit

The remote search generated 256 optimizer squads and 19,970 legal evolutionary squads across 10 generations. 4,587 reached discovery, 87 reached exact component selection and 11 received the deep holdout.

Best remote finalist: **R-c60fa6e43b** · 4-4-2 · Bruno Fernandes captain · £21.0m bench · robust regret 3.037.
Leader minus remote challenger in the paired central holdout: +0.052 points (95% CI -0.108 to +0.213).


## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-083607ec8c | 3-4-3 | £20.5m | 308.92 | 0.87 | 3.51 | 1.53 |
| 2 | R-4e8a455b0e | 3-5-2 | £20.5m | 308.71 | 1.05 | 3.66 | 1.70 |
| 3 | R-5aac936d2a | 4-4-2 | £21.0m | 309.12 | 0.79 | 4.60 | 1.74 |
| 4 | R-0aec115e14 | 3-5-2 | £20.5m | 308.91 | 1.10 | 4.77 | 2.02 |
| 5 | R-98a4dba004 | 4-4-2 | £20.5m | 308.53 | 1.56 | 3.52 | 2.05 |
| 6 | R-5f3c2a2518 | 4-4-2 | £20.5m | 309.35 | 0.90 | 6.10 | 2.20 |
| 7 | R-5fe3724d1b | 4-4-2 | £20.5m | 309.20 | 1.00 | 5.99 | 2.25 |
| 8 | R-4d5e05bb66 | 4-4-2 | £20.5m | 309.17 | 1.01 | 5.95 | 2.25 |
| 9 | R-2ef866d551 | 4-4-2 | £20.5m | 309.24 | 0.99 | 6.11 | 2.27 |
| 10 | R-f0ed742b54 | 4-4-2 | £20.5m | 309.16 | 1.05 | 6.10 | 2.31 |

## GW1 starting XI

- **GK:** Donnarumma
- **DEF:** Tarkowski (V), Maguire, Truffert
- **MID:** Bruno Fernandes (C), Mbeumo, Semenyo, Szoboszlai
- **FWD:** Igor Thiago, Watkins, Calvert-Lewin

## Bench

1. N.Williams (NFO, £5.0m)
2. Hill (BOU, £5.5m)
3. Groß (BHA, £5.5m)
4. Verbruggen (BHA, £4.5m)

## Interpretation

The robust rank is not simply the highest central mean. It minimizes a declared regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, anchored and high-scoring environments. The weights are explicit in the receipt and should be sensitivity-tested rather than treated as natural constants.

The discovery screen deliberately uses a cheap nominal-XI approximation. No candidate is promoted from that approximation: the shortlist is re-evaluated with exact autosubs and component simulation, followed by an independent deep holdout.

**Deadline rule:** Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios.
