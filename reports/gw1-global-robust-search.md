# GW1 global robust-search funnel

**Built:** 2026-08-15T18:33:56.141352+00:00<br>
**Status:** robust_challenger_provisional<br>
**Leader:** R-083607ec8c · 3-4-3 · Bruno Fernandes captain · £20.5m bench

## Verdict

The robust funnel recommends **R-083607ec8c**. It was selected after 552,528 legal local/global combinations were reduced to 10,000 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-92c8534bfc is -0.074 points (95% CI -0.137 to -0.012).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 141 | Prior residual and component optima |
| One-swap legal universe | 299,205 | Exhaustive same-position neighbours |
| Local two-swap universe | 532,367 | Neighbours of 128 proxy leaders |
| Distant MILP restarts | 256 | At least 3 swaps from every seed |
| Evolutionary squads | 19,905 | Legal crossover and mutation |
| Combined universe | 552,528 | Deduplicated local and global field |
| Discovery field | 10,000 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 308.73 | 0.38 | 30.0% |
| base evidence roll gw2 | 308.73 | 0.38 | 20.0% |
| base evidence fixed | 305.72 | 0.55 | 10.0% |
| base raw open | 286.89 | 1.87 | 10.0% |
| base anchored open | 311.15 | 0.60 | 15.0% |
| high goal open | 293.28 | 1.92 | 7.5% |
| high goal roll gw2 | 293.28 | 1.22 | 5.0% |
| high goal fixed | 290.60 | 3.24 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 14 | 308.74 | 2.73 | -0.02 | -0.16 to +0.12 |
| C007 | 22 | 309.06 | 3.06 | -0.33 | -0.45 to -0.22 |
| C009 | 41 | 307.38 | 1.88 | +1.34 | +1.12 to +1.56 |
| S001 | 13 | 308.67 | 2.71 | +0.06 | -0.09 to +0.20 |
| S028 | 64 | 299.39 | 17.19 | +9.34 | +9.12 to +9.55 |

## Global challenger audit

The remote search generated 256 optimizer squads and 19,905 legal evolutionary squads across 10 generations. 4,004 reached discovery, 38 reached exact component selection and 9 received the deep holdout.

Best remote finalist: **R-8fb9b3313d** · 4-4-2 · Bruno Fernandes captain · £21.0m bench · robust regret 2.137.
Leader minus remote challenger in the paired central holdout: +1.485 points (95% CI +1.293 to +1.676).


## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-083607ec8c | 3-4-3 | £20.5m | 308.73 | 0.81 | 3.24 | 1.42 |
| 2 | R-92c8534bfc | 3-4-3 | £20.5m | 308.80 | 0.78 | 3.37 | 1.43 |
| 3 | R-4e8a455b0e | 3-5-2 | £20.5m | 308.50 | 1.01 | 3.58 | 1.66 |
| 4 | R-93d7c65948 | 3-5-2 | £20.0m | 308.31 | 1.17 | 3.68 | 1.80 |
| 5 | R-5f3c2a2518 | 4-4-2 | £20.5m | 309.10 | 0.92 | 6.04 | 2.20 |
| 6 | R-4d5e05bb66 | 4-4-2 | £20.5m | 308.93 | 1.02 | 5.93 | 2.25 |
| 7 | R-2ef866d551 | 4-4-2 | £20.5m | 309.01 | 0.99 | 6.03 | 2.25 |
| 8 | R-5fe3724d1b | 4-4-2 | £20.5m | 308.93 | 1.03 | 5.91 | 2.25 |
| 9 | R-06250e96c5 | 3-5-2 | £20.5m | 308.15 | 1.52 | 4.86 | 2.36 |
| 10 | R-d3f20203f6 | 3-4-3 | £20.0m | 308.17 | 1.55 | 4.84 | 2.37 |

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
