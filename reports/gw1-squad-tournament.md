# GW1–5 squad survival tournament

**Run:** 2026-08-09T07:51:02.263233+00:00  
**Engine:** `correlated_residual_v1` · **Candidates:** 128 · **Selection simulations:** 5,000 · **Holdout simulations:** 25,000 per scenario

## Verdict

The current squad ranks **1/128** by base-scenario mean points. The holdout leader is **S001** (current-transfer-aware) at 307.24 points versus 307.24 for the current squad—a paired +0.00-point difference over five gameweeks.

The recommendation is **S001 (the current squad)**: with equal free-transfer access it leads the finalist holdout at 310.52 points, 0.47 ahead of the next route.

The knockout is a diagnostic view: after each gameweek it removes the bottom half by cumulative score (128→64→32→16→8→4), then crowns the highest-scoring finalist. The recommendation is not selected from one bracket; it uses repeated holdout distributions.

## Holdout top ten — base forecast

| Rank | ID | Archetype | Premiums | Bench | Mean | P10 | P90 | Top 10 | Champion | Δ current |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | S001 | current-transfer-aware | Bruno Fernandes | £22.5m | 307.24 | 292 | 323 | 27.0% | 3.1% | +0.00 |
| 2 | S084 | deep-bench:perturbed:0.12:d0.88 | Bruno Fernandes | £22.5m | 306.75 | 291 | 323 | 23.0% | 1.4% | -0.50 |
| 3 | S029 | deep-bench | Bruno Fernandes | £22.5m | 306.65 | 291 | 323 | 22.2% | 1.2% | -0.60 |
| 4 | S099 | perturbed:0.12:d0.88 | Bruno Fernandes | £22.5m | 306.43 | 290 | 323 | 20.5% | 1.2% | -0.81 |
| 5 | S024 | medium-bench | Bruno Fernandes | £21.5m | 306.34 | 290 | 322 | 17.3% | 0.9% | -0.90 |
| 6 | S079 | deep-bench:perturbed:0.12:d0.80 | Bruno Fernandes | £22.5m | 306.27 | 290 | 323 | 19.6% | 1.1% | -0.97 |
| 7 | S002 | static-xp | Bruno Fernandes | £21.5m | 306.19 | 290 | 322 | 16.2% | 0.9% | -1.05 |
| 8 | S030 | deep-bench:Bruno Fernandes | Bruno Fernandes | £22.5m | 306.16 | 290 | 323 | 18.9% | 1.0% | -1.08 |
| 9 | S049 | historical-bench-band:perturbed:0.12:d0.80 | Bruno Fernandes | £20.0m | 305.99 | 290 | 322 | 14.7% | 0.9% | -1.26 |
| 10 | S019 | historical-bench-band | Bruno Fernandes | £20.0m | 305.84 | 290 | 322 | 14.0% | 0.7% | -1.40 |

## Premium recovery stress

This second holdout raises play probability to at least 86% for available, highly owned £9.0m+ midfielders/forwards returning from a 60+ day break. It is a generic counterfactual, not a name-based boost.

| Rank | ID | Premiums | Base mean | Recovery mean | Recovery Δ current |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | S001 | Bruno Fernandes | 307.24 | 307.24 | +0.00 |
| 2 | S084 | Bruno Fernandes | 306.75 | 306.75 | -0.50 |
| 3 | S029 | Bruno Fernandes | 306.65 | 306.65 | -0.60 |
| 4 | S099 | Bruno Fernandes | 306.43 | 306.43 | -0.81 |
| 5 | S024 | Bruno Fernandes | 306.34 | 306.34 | -0.90 |
| 6 | S009 | Bruno Fernandes, Saka | 304.91 | 306.29 | -0.96 |
| 7 | S079 | Bruno Fernandes | 306.27 | 306.27 | -0.97 |
| 8 | S002 | Bruno Fernandes | 306.19 | 306.19 | -1.05 |
| 9 | S030 | Bruno Fernandes | 306.16 | 306.16 | -1.08 |
| 10 | S049 | Bruno Fernandes | 305.99 | 306.16 | -1.08 |

### Best named premium challengers

| Premium | ID | Bench | Base rank | Base Δ | Recovery rank | Recovery Δ | Policy recovery Δ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Haaland | S033 | £22.5m | 108 | -14.28 | 99 | -10.84 | -9.13 |
| Saka | S009 | £20.5m | 20 | -2.33 | 6 | -0.96 | -0.71 |
| Palmer | S008 | £20.5m | 18 | -1.99 | 19 | -1.90 | -2.06 |
| Isak | S007 | £21.5m | 69 | -7.41 | 65 | -6.12 | -2.89 |

## Appearance-risk stress

The raw model is well calibrated overall, but its 80%+ play probabilities are conservative in the rolling out-of-fold sample. This scenario applies a position-specific isotonic reliability map while preserving every player's xP; it changes only DNP/autosub risk.

| Rank | ID | Bench | Base mean | Calibrated mean | Calibrated Δ current |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | S001 | £22.5m | 307.24 | 301.01 | +0.00 |
| 2 | S084 | £22.5m | 306.75 | 300.84 | -0.17 |
| 3 | S029 | £22.5m | 306.65 | 300.81 | -0.21 |
| 4 | S099 | £22.5m | 306.43 | 300.74 | -0.28 |
| 5 | S079 | £22.5m | 306.27 | 300.68 | -0.33 |
| 6 | S030 | £22.5m | 306.16 | 300.65 | -0.37 |
| 7 | S080 | £23.0m | 305.66 | 300.44 | -0.58 |
| 8 | S024 | £21.5m | 306.34 | 300.34 | -0.68 |
| 9 | S002 | £21.5m | 306.19 | 300.29 | -0.72 |
| 10 | S025 | £21.5m | 305.81 | 300.17 | -0.84 |

The reliability map changes play probability by +0.032 on average across the live forecast rows; expected points are held constant.

## Transfer-aware finalist holdout

The selection top ten plus the best premium and bench-band challengers get an equal free-transfer planning envelope. These are deterministic preseason routes, not claims that we would ignore new information at future deadlines.

| Rank | ID | Premiums | Fixed mean | Policy mean | P10 | Top 3 | Δ current policy |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | S001 | Bruno Fernandes | 307.24 | 310.52 | 295 | 29.6% | +0.00 |
| 2 | S084 | Bruno Fernandes | 306.75 | 310.05 | 294 | 23.9% | -0.47 |
| 3 | S029 | Bruno Fernandes | 306.65 | 309.95 | 294 | 22.9% | -0.57 |
| 4 | S099 | Bruno Fernandes | 306.43 | 309.76 | 294 | 17.8% | -0.77 |
| 5 | S079 | Bruno Fernandes | 306.27 | 309.72 | 294 | 17.2% | -0.80 |
| 6 | S030 | Bruno Fernandes | 306.16 | 309.70 | 294 | 17.0% | -0.82 |
| 7 | S024 | Bruno Fernandes | 306.34 | 309.42 | 294 | 20.3% | -1.10 |
| 8 | S002 | Bruno Fernandes | 306.19 | 309.29 | 293 | 18.9% | -1.24 |
| 9 | S049 | Bruno Fernandes | 305.99 | 309.25 | 293 | 18.6% | -1.27 |
| 10 | S009 | Bruno Fernandes, Saka | 304.91 | 309.20 | 293 | 29.5% | -1.32 |
| 11 | S019 | Bruno Fernandes | 305.84 | 309.10 | 293 | 17.2% | -1.42 |
| 12 | S008 | Bruno Fernandes, Palmer | 305.25 | 308.47 | 292 | 23.9% | -2.06 |
| 13 | S119 | Bruno Fernandes | 305.06 | 307.95 | 292 | 18.0% | -2.58 |
| 14 | S007 | Bruno Fernandes, Isak | 299.83 | 307.49 | 292 | 16.5% | -3.03 |
| 15 | S033 | Bruno Fernandes, Haaland | 292.96 | 300.58 | 284 | 8.7% | -9.95 |

**S001 planned route:**

- GW2: Collins → Hill (1/1 free transfers used)
- GW3: — → roll (0/1 free transfers used)
- GW4: Hill, Maguire → Van Hecke, Justin (2/2 free transfers used)
- GW5: Van Hecke → Milenković (1/1 free transfers used)

## Bench-spend interrogation

The current candidate spends **£22.5m** on its GW1 bench. The 2019/20 eventual top ten averaged **£18.45m** in GW1 (range £16.5m–£24.0m). This is only ten survivorship-selected managers under older prices/rules, so it is a warning flag, not a target.

| GW1 bench band | Candidates | Best base | Group base | Best calibrated | Best ID |
| --- | ---: | ---: | ---: | ---: | --- |
| ≤£18.5m | 39 | 305.06 | 296.15 | 299.43 | S119 |
| £18.6–20.0m | 26 | 305.99 | 299.38 | 300.11 | S049 |
| £20.1–22.0m | 35 | 306.34 | 301.54 | 300.34 | S024 |
| >£22.0m | 28 | 307.24 | 301.53 | 301.01 | S001 |

## Fixed-squad leader detail

**S001 · current-transfer-aware · £100.0m spent · £22.5m bench**

| Pos | Player | Club | Price | GW1 role |
| --- | --- | --- | ---: | --- |
| GK | Donnarumma | MCI | £5.5m | Starter |
| GK | Verbruggen | BHA | £4.5m | Bench 4 |
| DEF | Tarkowski | EVE | £6.0m | Vice-captain |
| DEF | Senesi | TOT | £6.0m | Starter |
| DEF | Truffert | BOU | £5.5m | Starter |
| DEF | Collins | BRE | £5.5m | Starter |
| DEF | Maguire | MUN | £5.0m | Starter |
| MID | Bruno Fernandes | MUN | £12.0m | Captain |
| MID | Mbeumo | MUN | £8.0m | Starter |
| MID | Gibbs-White | NFO | £8.0m | Starter |
| MID | Szoboszlai | LIV | £7.0m | Bench 2 |
| MID | Tanaka | LEE | £5.0m | Bench 3 |
| FWD | Watkins | AVL | £8.0m | Starter |
| FWD | Igor Thiago | BRE | £8.0m | Starter |
| FWD | Calvert-Lewin | LEE | £6.0m | Bench 1 |

## Tournament integrity checks

The field contains 128 unique squads and 196 different players. Pairwise squads overlap by 9.3/15 players on average (range 4–14). Selection-versus-holdout rank correlation is 1.000.

Across the 196 players used by the field, holdout simulated means differ from forecast xP by -0.001 points on average (absolute calibration error 0.007). Appearance-rate bias is -0.0001. GW1 point correlation averages 0.013 for same-team pairs versus 0.000 for different teams.

The season-forward marginal distribution replay covers 36,368 player/gameweeks in 2024/25 and 2025/26. Its nominal 10th–90th interval contains 79.9% of realised scores, with -0.040 mean-point bias.

## What the simulation models

- 32,677 historical played player/gameweeks calibrate conditional score residuals, split by position and forecast-strength quintile.
- 1,140 historical fixtures supply paired home/away, position-specific shocks; gameweek shocks correlate the whole slate.
- Residual dispersion scales by position (GK 0.65, DEF 0.40, MID 0.40, FWD 0.45), selected on 2024/25 interval coverage and checked forward on 2025/26.
- A calibrated Gaussian copula carries player appearance risk across adjacent weeks; a separate persistent residual carries part of player-level forecast error.
- Every squad uses its forecast-best legal XI, captain and vice each week. Realised DNPs invoke formation-valid autosubs and captain-to-vice fallback.
- Player prices and the initial 15 are fixed for this five-week contest. That isolates the initial squad decision; transfers and price moves require a separate policy tournament.

## Limits that still matter

This is a correlated residual simulator, not yet a goal/assist/clean-sheet component model. It preserves historical match-level covariance in aggregate but cannot enforce every football identity (for example, a conceded goal simultaneously erasing every defender's clean sheet). The premium-recovery stress is intentionally separate from the base forecast. Candidate discovery and holdout use independent random seeds, but both ultimately depend on the same forecast and residual assumptions.
