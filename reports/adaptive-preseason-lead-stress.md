# Adaptive preseason lead-time stress

Generated: 2026-08-10T17:38:13.889323+00:00

## Verdict

**FULL_PIPELINE_RETAIN_INCUMBENT** — `AP-009-cb99f9156a` leads the bounded adaptive tournament with robust regret 0.116; production `R-dc7de17def` has 1.603.

Every initial squad receives a separately solved legal GW1–8 transfer policy under the base and lead-specific forecast families. Both policies are then scored in 10,000 paired correlated worlds, with fixed-squad and moderate GW1 role-downside families preventing a single optimistic future model from owning the answer.

| Rank | Candidate | Robust regret | Base open | Lead open | Role downside |
|---:|---|---:|---:|---:|---:|
| 1 | `AP-009-cb99f9156a` | 0.116 | 334.73 | 314.90 | 333.53 |
| 2 | `AP-007-92c8534bfc` | 0.652 | 333.76 | 314.74 | 332.93 |
| 3 | `AP-008-4e92594171` | 0.706 | 333.70 | 314.65 | 332.99 |
| 4 | `AP-006-083607ec8c` | 0.738 | 333.66 | 314.60 | 332.97 |
| 5 | `AP-010-80ac405ebe` | 0.781 | 333.65 | 314.53 | 332.45 |
| 6 | `AP-012-8cdf4d1b52` | 0.876 | 333.55 | 314.43 | 332.40 |
| 7 | `AP-014-da30feb9f1` | 0.977 | 333.45 | 314.36 | 332.25 |
| 8 | `R-dc7de17def` | 1.603 | 333.37 | 313.39 | 332.32 |
| 9 | `AP-004-ad155aeb95` | 1.678 | 333.32 | 313.28 | 332.32 |
| 10 | `AP-003-6dcff8b173` | 1.709 | 333.33 | 313.23 | 332.33 |
| 11 | `AP-005-bf70ca3297` | 2.019 | 333.16 | 313.34 | 332.36 |
| 12 | `AP-002-596f267ab1` | 2.447 | 332.81 | 313.76 | 332.05 |

## Full-pipeline request gate

- PASS — base open non regression
- PASS — lead open improves
- PASS — leader differs from incumbent
- PASS — robust regret improves by point two five
- PASS — role downside non regression

Passing this gate only requests equal treatment in the complete robust-search, horizon and synthesis funnel. It cannot directly replace the published squad.

## Full-pipeline resolution

**RETAIN_INCUMBENT** — the requested challenger reached the full robust and horizon holdouts. Robust regret was 3.617, horizon regret was 0.488, and synthesis selected `R-dc7de17def`.
