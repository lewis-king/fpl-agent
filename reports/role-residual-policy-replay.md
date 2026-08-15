# Competitive-role residual challenger

Generated: 2026-08-10T17:13:27.453813+00:00

## Verdict

**RETAIN_INCUMBENT** — statistically eligible positions: GK, FWD. The exact legal-squad replay changed 2024/25 by -23 points and the untouched 2025/26 season by -8 points.

This residual model starts from the production play probability. It may only correct systematic errors associated with competitive role persistence, and it is assessed on the union of high-points and high-value candidates most likely to affect a decision.

| Position | Weight | 2024/25 Brier Δ | 2025/26 Brier Δ | Statistical gate |
|---|---:|---:|---:|---|
| GK | 0.50 | -0.00045 | -0.00041 | PASS |
| DEF | 1.00 | -0.00445 | +0.00078 | FAIL |
| MID | 1.00 | -0.00230 | +0.00047 | FAIL |
| FWD | 1.00 | -0.00614 | -0.00337 | PASS |

## Authority boundary

A probability improvement is only permission to run the legal policy replay. Production changes only if every policy gate passes; otherwise the current minutes and appearance model remains authoritative.
