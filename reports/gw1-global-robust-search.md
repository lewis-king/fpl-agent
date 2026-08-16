# GW1 global robust-search funnel

**Built:** 2026-08-16T06:27:22.186349+00:00<br>
**Status:** robust_challenger_provisional<br>
**Leader:** R-92c8534bfc · 3-4-3 · Bruno Fernandes captain · £20.5m bench

## Verdict

The robust funnel recommends **R-92c8534bfc**. It was selected after 551,183 legal local/global combinations were reduced to 10,000 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-dc7de17def is +0.419 points (95% CI +0.234 to +0.604).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 141 | Prior residual and component optima |
| One-swap legal universe | 298,359 | Exhaustive same-position neighbours |
| Local two-swap universe | 530,947 | Neighbours of 128 proxy leaders |
| Distant MILP restarts | 256 | At least 3 swaps from every seed |
| Evolutionary squads | 19,980 | Legal crossover and mutation |
| Combined universe | 551,183 | Deduplicated local and global field |
| Discovery field | 10,000 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 308.82 | 0.30 | 30.0% |
| base evidence roll gw2 | 308.82 | 0.30 | 20.0% |
| base evidence fixed | 305.70 | 0.56 | 10.0% |
| base raw open | 286.89 | 2.05 | 10.0% |
| base anchored open | 311.25 | 0.49 | 15.0% |
| high goal open | 292.93 | 1.87 | 7.5% |
| high goal roll gw2 | 292.93 | 1.36 | 5.0% |
| high goal fixed | 290.28 | 3.25 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 12 | 308.82 | 2.62 | -0.00 | -0.13 to +0.13 |
| C007 | 21 | 309.12 | 2.97 | -0.30 | -0.42 to -0.19 |
| C009 | 2 | 308.40 | 1.53 | +0.42 | +0.23 to +0.60 |
| S001 | 14 | 308.64 | 2.68 | +0.18 | +0.03 to +0.32 |
| S028 | 64 | 299.78 | 16.38 | +9.04 | +8.83 to +9.24 |

## Global challenger audit

The remote search generated 256 optimizer squads and 19,980 legal evolutionary squads across 10 generations. 3,991 reached discovery, 45 reached exact component selection and 8 received the deep holdout.

Best remote finalist: **R-8447ae7ba5** · 3-4-3 · Bruno Fernandes captain · £19.5m bench · robust regret 3.648.
Leader minus remote challenger in the paired central holdout: +2.594 points (95% CI +2.389 to +2.798).


## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-92c8534bfc | 3-4-3 | £20.5m | 308.82 | 0.77 | 3.25 | 1.39 |
| 2 | R-dc7de17def | 4-4-2 | £21.0m | 308.40 | 1.19 | 2.57 | 1.53 |
| 3 | R-4e92594171 | 3-4-3 | £20.5m | 308.75 | 0.93 | 3.60 | 1.60 |
| 4 | R-4e8a455b0e | 3-5-2 | £20.5m | 308.44 | 1.07 | 3.34 | 1.64 |
| 5 | R-93d7c65948 | 3-5-2 | £20.0m | 308.27 | 1.20 | 3.47 | 1.76 |
| 6 | R-c0a059b3be | 3-4-3 | £20.5m | 308.74 | 1.04 | 4.56 | 1.92 |
| 7 | R-5f3c2a2518 | 4-4-2 | £20.5m | 309.12 | 0.90 | 5.73 | 2.10 |
| 8 | R-4d5e05bb66 | 4-4-2 | £20.5m | 308.94 | 1.01 | 5.60 | 2.16 |
| 9 | R-2ef866d551 | 4-4-2 | £20.5m | 309.02 | 0.97 | 5.72 | 2.16 |
| 10 | R-5fe3724d1b | 4-4-2 | £20.5m | 308.93 | 1.02 | 5.62 | 2.17 |

## GW1 starting XI

- **GK:** Donnarumma
- **DEF:** Tarkowski (V), Maguire, Truffert
- **MID:** Bruno Fernandes (C), Mbeumo, Semenyo, Szoboszlai
- **FWD:** Igor Thiago, Watkins, Calvert-Lewin

## Bench

1. Xhaka (SUN, £5.5m)
2. N.Williams (NFO, £5.0m)
3. Hill (BOU, £5.5m)
4. Verbruggen (BHA, £4.5m)

## Interpretation

The robust rank is not simply the highest central mean. It minimizes a declared regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, anchored and high-scoring environments. The weights are explicit in the receipt and should be sensitivity-tested rather than treated as natural constants.

The discovery screen deliberately uses a cheap nominal-XI approximation. No candidate is promoted from that approximation: the shortlist is re-evaluated with exact autosubs and component simulation, followed by an independent deep holdout.

**Deadline rule:** Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios.
