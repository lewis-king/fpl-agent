# Market goal signal: sequential transfer-policy replay

Generated: 2026-08-07T17:12:15.858196+00:00

## Verdict

**REJECT** — the validation path changed by +145 net points (+3.816/GW). On the untouched 2025/26 path, the market challenger changed achievable ordinary-transfer points by -2 (-0.053/GW), with a four-GW moving-block 95% interval of -3.184 to +2.868/GW.

Each policy starts from its own legal GW1 squad, then carries one continuous squad, bank, purchase prices, selling values and free-transfer balance. Every deadline compares roll, free-transfer and up-to-two-hit routes after cost, while reoptimising XI, bench, captain and vice from all 15 players.

## Validation weight selection

| Market weight | Gross | Hits cost | Net | Transfers | Rolls |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 2246 | 24 | 2222 | 44 | 6 |
| 0.25 | 2383 | 16 | 2367 | 42 | 5 |
| 0.50 | 2340 | 16 | 2324 | 42 | 5 |
| 0.75 | 2316 | 4 | 2312 | 39 | 4 |
| 1.00 | 2232 | 24 | 2208 | 44 | 3 |

## Season paths

| Season | Policy | Gross | Hits cost | Net | Transfers | Rolls |
|---|---|---:|---:|---:|---:|---:|
| 2024-25 | incumbent_xp | 2246 | 24 | 2222 | 44 | 6 |
| 2024-25 | internal_component_control | 2276 | 28 | 2248 | 45 | 5 |
| 2024-25 | market_challenger | 2383 | 16 | 2367 | 42 | 5 |
| 2025-26 | incumbent_xp | 2031 | 24 | 2007 | 44 | 4 |
| 2025-26 | internal_component_control | 1974 | 24 | 1950 | 44 | 6 |
| 2025-26 | market_challenger | 2025 | 20 | 2005 | 43 | 5 |

## Scope

- The blend weight is selected only on continuous 2024/25 net points from the declared coarse grid, with zero included as the incumbent; 2025/26 remains untouched for this test.
- Blank/double or otherwise component-missing player rows remain in the candidate pool with direct xP, rather than being excluded.
- If a held player changes Premier League clubs, the historical state keeps its acquisition-club identity for strict legacy-state validation; every deadline optimiser still uses the current club and enforces the current three-player limit.
- This tests ordinary roll/free/hit decisions. Wildcard, Free Hit, Bench Boost and Triple Captain are deliberately excluded and need their own historical policies.
- The four-GW moving-block interval acknowledges serial dependence, but only one path per season exists. Prospective 2026/27 receipts remain the decisive evidence.
