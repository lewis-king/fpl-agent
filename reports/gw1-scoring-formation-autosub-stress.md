# GW1 scoring, formation and autosub stress

Generated: 2026-08-15T19:19:56.498883+00:00

**Verdict: PASS**

Every synthesis finalist plus squads generated at five different cheap bench-proxy weights is rescored with exact formation-valid autosubs and captain fallback. The 2026/27 bonus and defensive-contribution layers are then removed separately, removed together and doubled. These are model-misspecification stresses, not alternative FPL rules.

Published candidate: `R-92c8534bfc`; stress leader: `R-9be2581ab3`.

## Publication gate

- PASS — live rule assertions pass
- PASS — all synthesis finalists scored
- PASS — five bench proxy settings challenged
- PASS — exact formation valid autosubs used
- PASS — supported gw1 reversal reconciled with multiweek objective

## One-week versus multiweek reconciliation

Status: **gw1 edge recorded multiweek selector retains published**.

The stress leader gains +1.669 GW1 points in the independent central-rules holdout (95% CI +1.493 to +1.845). This is shown as a live alternative, not discarded.
It ranks 11 in the declared multiweek synthesis and carries +0.649 more synthesis regret than the published squad. The season-opening selector therefore retains the published squad; a challenger absent from that multiweek field would block publication instead.

## Top field

| Rank | Candidate | Robust regret | Central xP | Worst regret | Formation | Bench |
|---:|---|---:|---:|---:|---|---:|
| 1 | `R-9be2581ab3` | 0.000 | 59.55 | 0.000 | 3-5-2 | £20.5m |
| 2 | `R-1ced0705f3` | 1.786 | 57.79 | 2.530 | 4-4-2 | £20.5m |
| 3 | `R-92c8534bfc` | 2.002 | 57.58 | 2.677 | 3-4-3 | £20.5m |
| 4 | `R-083607ec8c` | 2.174 | 57.40 | 2.893 | 3-4-3 | £20.5m |
| 5 | `R-635e1f3716` | 2.199 | 57.38 | 2.856 | 4-4-2 | £20.5m |
| 6 | `R-4d5e05bb66` | 2.300 | 57.28 | 3.019 | 4-4-2 | £20.5m |
| 7 | `R-1ca68907f5` | 2.315 | 57.27 | 3.109 | 4-4-2 | £20.5m |
| 8 | `R-5fe3724d1b` | 2.320 | 57.26 | 3.051 | 4-4-2 | £20.5m |
| 9 | `R-a31418a5a2` | 2.338 | 57.24 | 3.037 | 4-4-2 | £20.5m |
| 10 | `R-5f3c2a2518` | 2.349 | 57.23 | 3.090 | 4-4-2 | £20.5m |
| 11 | `R-2ef866d551` | 2.352 | 57.23 | 3.082 | 4-4-2 | £20.5m |
| 12 | `R-a694204983` | 2.360 | 57.22 | 3.166 | 4-4-2 | £20.5m |
| 13 | `R-431c916239` | 2.363 | 57.22 | 3.073 | 4-4-2 | £20.5m |
| 14 | `R-7681b047b5` | 2.374 | 57.21 | 3.126 | 4-4-2 | £20.5m |
| 15 | `R-5384125eaf` | 2.505 | 57.08 | 3.295 | 4-4-2 | £20.5m |

The initial optimiser's 8% bench coefficient is therefore only a generator. It has no voting power in this gate: final scoring uses actual DNP patterns, legal autosub order, minimum three defenders, goalkeeper-only substitution and captain-to-vice fallback.
