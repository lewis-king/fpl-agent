# Market features inside the player decision model

Generated: 2026-08-10T11:11:08.547890+00:00

## Verdict

**PROMOTE_PRESEASON_ONLY** — defender market features were the only component to improve top-k realised points and MAE in all three forward seasons. The multi-season stability rule selected the bounded 20% defender-only blend.

## Defender forecast evidence

| Season | Incumbent top-k | Market-feature top-k | Lift | MAE lift |
|---|---:|---:|---:|---:|
| 2023-24 | 3.621 | 3.705 | +0.084 | +0.0082 |
| 2024-25 | 3.649 | 3.777 | +0.128 | +0.0098 |
| 2025-26 | 4.154 | 4.314 | +0.160 | +0.0048 |

## Legal decision replay

- Unbounded single-season weight search selected 70%, then lost **-16 points** on independent test-season squads; it was rejected.
- Independent frozen squads at the bounded deployment weight: **+27 points**.
- Sequential stability blend selected on 2023/24 + 2024/25: **20%**.
- Continuous 2023/24 development path: **+64 points**.
- Continuous 2024/25 development path: **+76 points**.
- Continuous frozen follow-up path (2025/26): **+90 points (+2.368/GW)**.
- Four-GW moving-block interval: **+0.816 to +4.132/GW**.
- Pooled 2023/24 + 2025/26 out-of-selection interval: **-0.158 to +3.934/GW**.

### Sequential stability selection

| Defender market weight | 2023/24 delta | 2024/25 delta | Worst season | Total |
|---:|---:|---:|---:|---:|
| 0% | +0 | +0 | +0 | +0 |
| 10% | +64 | +1 | +1 | +65 |
| 20% | +64 | +76 | +64 | +140 |

## Interpretation

The market is not used as a substitute player forecast. Its team scoring rate, opponent scoring rate and clean-sheet expectation are deadline features alongside player xG/xA, role, price and minutes. Missing or incomplete market fixtures resolve to the internal team features with zero coverage, so availability never creates fabricated values.

A bounded Betfair defender blend may enter preseason squad and XI decisions. It improved defender forecast and legal-decision totals across every tested season, but weekly transfer authority remains disabled until the continuous-path downside interval passes or prospective evidence resolves it.
