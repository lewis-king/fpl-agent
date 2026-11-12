# GW1 global robust-search funnel

**Built:** 2026-08-19T15:47:09.514899+00:00<br>
**Status:** robust_challenger_provisional<br>
**Leader:** R-b954c5c198 · 3-4-3 · Bruno Fernandes captain · £19.5m bench

## Verdict

The robust funnel recommends **R-b954c5c198**. It was selected after 537,804 legal local/global combinations were reduced to 10,011 discovery candidates, 512 component-selection candidates and 64 deep-holdout finalists.

Its central paired edge over R-01afc86b1b is -0.380 points (95% CI -0.526 to -0.234).
The regret optimizer is constrained to candidates within 1.0 point of the best central forecast, preventing an extreme stress winner from displacing a materially stronger base squad.

## Funnel

| Stage | Candidates/worlds | Purpose |
|---|---:|---|
| Seed squads | 144 | Prior residual and component optima |
| One-swap legal universe | 281,267 | Exhaustive same-position neighbours |
| Local two-swap universe | 518,272 | Neighbours of 128 proxy leaders |
| Distant MILP restarts | 256 | At least 3 swaps from every seed |
| Evolutionary squads | 19,249 | Legal crossover and mutation |
| Combined universe | 537,804 | Deduplicated local and global field |
| Discovery field | 10,011 | 40 deterministic assumption views |
| Fast screen | 2,000 worlds | Approximate nominal-XI residual screen |
| Component selection | 512 × 5,000 | Exact autosubs and football identities |
| Deep holdout | 64 × 25,000 | Untouched base evaluation |
| High-goal stress | 64 × 25,000 | Goal rates ×1.15 |

## Robust scenarios

| Scenario | Leader points | Leader regret | Weight |
|---|---:|---:|---:|
| base evidence open | 325.84 | 0.53 | 30.0% |
| base evidence roll gw2 | 325.84 | 0.53 | 20.0% |
| base evidence fixed | 321.86 | 0.60 | 10.0% |
| base raw open | 296.92 | 0.00 | 10.0% |
| base anchored open | 329.05 | 0.96 | 15.0% |
| high goal open | 304.41 | 0.00 | 7.5% |
| high goal roll gw2 | 304.41 | 0.00 | 5.0% |
| high goal fixed | 300.47 | 1.24 | 2.5% |

## Protected benchmark audit

These named incumbents were protected from both elimination cuts and received the same policy solves and untouched holdout worlds as the challenger. A negative central delta means the robust leader deliberately surrendered a small amount of central mean to reduce cross-scenario regret.

| Benchmark | Robust rank | Central | Robust regret | Leader central delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| C005 | 2 | 326.22 | 1.14 | -0.38 | -0.53 to -0.23 |
| C007 | 1 | 325.84 | 0.69 | +0.00 | +0.00 to +0.00 |
| C009 | 26 | 325.25 | 1.34 | +0.59 | +0.43 to +0.75 |
| S001 | 11 | 326.17 | 4.80 | -0.33 | -0.58 to -0.09 |
| S028 | 60 | 321.94 | 9.41 | +3.90 | +3.57 to +4.23 |

## Global challenger audit

The remote search generated 256 optimizer squads and 19,249 legal evolutionary squads across 10 generations. 7,254 reached discovery, 207 reached exact component selection and 8 received the deep holdout.

Best remote finalist: **R-b5f6d6af2f** · 3-4-3 · Bruno Fernandes captain · £21.5m bench · robust regret 1.355.
Leader minus remote challenger in the paired central holdout: +0.162 points (95% CI -0.057 to +0.381).


## Top ten

| Rank | ID | Formation | Bench | Central | Mean regret | Worst regret | Robust regret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | R-b954c5c198 | 3-4-3 | £19.5m | 325.84 | 0.50 | 1.24 | 0.69 |
| 2 | R-01afc86b1b | 3-4-3 | £20.0m | 326.22 | 0.68 | 2.50 | 1.14 |
| 3 | R-b5f6d6af2f | 3-4-3 | £21.5m | 325.68 | 1.06 | 2.25 | 1.35 |
| 4 | R-a277a3f382 | 4-3-3 | £22.0m | 326.37 | 1.03 | 4.93 | 2.01 |
| 5 | R-a277a3f382:captain-55 | 4-3-3 | £22.0m | 326.37 | 1.23 | 7.49 | 2.80 |
| 6 | R-81916752d1 | 4-3-3 | £21.5m | 326.27 | 1.39 | 10.91 | 3.77 |
| 7 | R-9f2439ebd5 | 3-4-3 | £20.0m | 325.88 | 2.02 | 9.92 | 3.99 |
| 8 | R-c30d5ae43d | 3-4-3 | £20.0m | 325.75 | 2.19 | 10.22 | 4.20 |
| 9 | R-9f2439ebd5:captain-427 | 3-4-3 | £20.0m | 325.88 | 2.17 | 11.81 | 4.58 |
| 10 | R-d491f3a7fb | 4-3-3 | £22.0m | 325.86 | 2.27 | 12.33 | 4.79 |

## GW1 starting XI

- **GK:** Donnarumma
- **DEF:** Lacroix (V), Tarkowski, Truffert
- **MID:** Bruno Fernandes (C), Mbeumo, Semenyo, Szoboszlai
- **FWD:** Igor Thiago, Calvert-Lewin, Watkins

## Bench

1. Milenković (NFO, £5.5m)
2. N.Williams (NFO, £5.0m)
3. McAteer (IPS, £4.5m)
4. Verbruggen (BHA, £4.5m)

## Interpretation

The robust rank is not simply the highest central mean. It minimizes a declared regret function across open-transfer, rolled-GW2, fixed-squad, raw-component, anchored and high-scoring environments. The weights are explicit in the receipt and should be sensitivity-tested rather than treated as natural constants.

The discovery screen deliberately uses a cheap nominal-XI approximation. No candidate is promoted from that approximation: the shortlist is re-evaluated with exact autosubs and component simulation, followed by an independent deep holdout.

**Deadline rule:** Refresh live forecasts and rerun the complete funnel. Promote only if the robust leader remains near-optimal across central, no-GW2-transfer and scoring-environment scenarios.
