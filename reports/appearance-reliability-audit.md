# Appearance reliability audit

**Built:** 2026-08-03T17:11:25.235522+00:00  
**Candidate rows:** 6,872  
**Promoted positions:** FWD

This audit is deliberately restricted to the union of leading raw-points and value candidates the optimiser could realistically select. That captures both premium starters and cheap bench routes without allowing hundreds of irrelevant players to dominate the score.

## Strict forward results

| Season | Pos | Raw Brier | Cal Brier | Raw log loss | Cal log loss | Raw/actual DNP |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2024-25 | GK | 0.0451 | 0.0458 | 0.1834 | 0.1846 | 16.2/13 |
| 2024-25 | DEF | 0.0631 | 0.0605 | 0.2467 | 0.2341 | 83.6/49 |
| 2024-25 | MID | 0.0460 | 0.0454 | 0.1922 | 0.1878 | 61.9/41 |
| 2024-25 | FWD | 0.0576 | 0.0566 | 0.2324 | 0.2278 | 36.0/26 |
| 2025-26 | GK | 0.0376 | 0.0374 | 0.1659 | 0.1602 | 19.3/10 |
| 2025-26 | DEF | 0.0672 | 0.0679 | 0.2572 | 0.2626 | 64.6/58 |
| 2025-26 | MID | 0.0554 | 0.0556 | 0.2197 | 0.2237 | 50.8/50 |
| 2025-26 | FWD | 0.0428 | 0.0413 | 0.1831 | 0.1766 | 35.1/19 |

## Decision

Only positions improving both Brier score and log loss in both strict season-forward tests are applied. All rejected positions remain unmodified.

A global correction was rejected during exploration because it improved 2024/25 but worsened the latest season. This artifact cannot silently alter a failed position.
