# GW1 scoring, formation and autosub stress

Generated: 2026-08-15T16:16:04.855594+00:00

**Verdict: PASS**

Every synthesis finalist plus squads generated at five different cheap bench-proxy weights is rescored with exact formation-valid autosubs and captain fallback. The 2026/27 bonus and defensive-contribution layers are then removed separately, removed together and doubled. These are model-misspecification stresses, not alternative FPL rules.

Published candidate: `R-083607ec8c`; stress leader: `R-0aec115e14`.

## Publication gate

- PASS — live rule assertions pass
- PASS — all synthesis finalists scored
- PASS — five bench proxy settings challenged
- PASS — exact formation valid autosubs used
- PASS — supported gw1 reversal reconciled with multiweek objective

## One-week versus multiweek reconciliation

Status: **gw1 edge recorded multiweek selector retains published**.

The stress leader gains +1.386 GW1 points in the independent central-rules holdout (95% CI +1.254 to +1.518). This is shown as a live alternative, not discarded.
It ranks 5 in the declared multiweek synthesis and carries +0.258 more synthesis regret than the published squad. The season-opening selector therefore retains the published squad; a challenger absent from that multiweek field would block publication instead.

## Top field

| Rank | Candidate | Robust regret | Central xP | Worst regret | Formation | Bench |
|---:|---|---:|---:|---:|---|---:|
| 1 | `R-0aec115e14` | 0.017 | 59.16 | 0.048 | 3-5-2 | £20.5m |
| 2 | `R-98a4dba004` | 0.149 | 59.03 | 0.239 | 4-4-2 | £20.5m |
| 3 | `R-5aac936d2a` | 0.984 | 58.19 | 1.273 | 4-4-2 | £21.0m |
| 4 | `R-083607ec8c` | 1.436 | 57.74 | 1.727 | 3-4-3 | £20.5m |
| 5 | `R-1ca68907f5` | 1.467 | 57.71 | 1.864 | 4-4-2 | £20.5m |
| 6 | `R-a694204983` | 1.532 | 57.65 | 1.934 | 4-4-2 | £20.5m |
| 7 | `R-cb99f9156a` | 1.583 | 57.60 | 1.993 | 4-4-2 | £20.5m |
| 8 | `R-3ca1967bb8` | 1.692 | 57.49 | 2.114 | 4-4-2 | £20.5m |
| 9 | `R-a31418a5a2` | 1.789 | 57.39 | 2.079 | 4-4-2 | £20.5m |
| 10 | `R-4d5e05bb66` | 1.858 | 57.32 | 2.227 | 4-4-2 | £20.5m |
| 11 | `R-5fe3724d1b` | 1.897 | 57.28 | 2.273 | 4-4-2 | £20.5m |
| 12 | `R-7681b047b5` | 1.906 | 57.27 | 2.286 | 4-4-2 | £20.5m |
| 13 | `R-2ef866d551` | 1.913 | 57.27 | 2.293 | 4-4-2 | £20.5m |
| 14 | `R-5f3c2a2518` | 1.923 | 57.26 | 2.307 | 4-4-2 | £20.5m |
| 15 | `R-f0ed742b54` | 1.963 | 57.22 | 2.355 | 4-4-2 | £20.5m |

The initial optimiser's 8% bench coefficient is therefore only a generator. It has no voting power in this gate: final scoring uses actual DNP patterns, legal autosub order, minimum three defenders, goalkeeper-only substitution and captain-to-vice fallback.
