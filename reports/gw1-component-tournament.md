# GW1–5 match-component tournament

Generated: 2026-08-09T07:26:02.869724+00:00

## Verdict

**SHADOW** — one or more adversarial gates failed, so this challenger is not allowed to replace the incumbent. The production recommendation is **S001**; the residual-engine incumbent entering this test was **S001**.

The xP-anchored component policy leader is **S001** (310.70 mean points); the raw-component leader is **S119**.
Including independently discovered component-native squads, the evidence-weighted leader is **C008**. The anchored leader is **S001** and the raw leader is **C021**.

## What is now simulated

- GPU Poisson home/away goal rates trained from leakage-safe opponent-adjusted attack/defence ratings, venue splits and promoted-team priors.
- Separately gated GPU player-event models for scorer, assister and bonus allocation.
- Correlated match scores, goal times and player on-pitch intervals.
- Every team goal is allocated to an eligible scorer; no more than one eligible teammate receives an assist.
- Clean sheets and goals conceded are derived from goals while each player is on the pitch.
- Appearance points, saves, cards, own goals, missed/saved penalties, defensive contribution and match-level 3/2/1 bonus.
- Exact FPL autosubs, legal formations, captain fallback and the previously generated transfer-aware finalist policies.

## Adversarial gates

| Gate | Result | Evidence |
|---|---:|---|
| season-forward player-component blend | PASS | 2024/25 selected raw weight=0.10; frozen 2025/26 top-k=4.131 vs xP=4.126 |
| season-forward goal model | PASS | Poisson deviance beats the home/away baseline in 2024/25 and 2025/26 |
| season-forward scorer/assister allocation | PASS | player propensities beat position-and-minutes allocation in both holdouts |
| historical scoring reconstruction | PASS | exactly reconstructed 99.9931% of 2023/24–2025/26 player-fixtures |
| optimizer-tail xP calibration | PASS | maximum pooled top-k position bias=0.390 points |
| league point conservation | PASS | raw=90.29; xP=94.32; 2025/26 actual=90.48 |
| football identities | PASS | goal reconciliation=1.000000; assist violations=0 |
| marginal xP anchoring | PASS | anchored MAE=0.0013 points |
| anchor is not doing excessive work | PASS | mean |adjustment|=0.43; P95=1.27; evidence-weighted S001 component shift=0.54/GW |
| component-native selection holdout | PASS | candidates=22; selection_seed=20260802; holdout_seed=20260803 |
| decision stability or independent challenger dominance | FAIL | incumbent=S001; anchored=S001; evidence-weighted=C008; raw stress=C021; paired evidence delta=+0.032 [-0.037, +0.101] |
| full-field rank stability | PASS | residual/component rank correlation=1.000 |

## Transfer-aware finalists

| Rank | ID | Archetype | Raw mean | Anchored mean | Decision mean | Decision P10–P90 | Decision Δ |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | S001 | current-transfer-aware | 283.46 | 310.70 | 307.98 | 266–351 | +0.00 |
| 2 | S084 | deep-bench:perturbed:0.12:d0.88 | 283.21 | 310.18 | 307.48 | 265–351 | -0.50 |
| 3 | S029 | deep-bench | 283.13 | 310.09 | 307.39 | 265–351 | -0.58 |
| 4 | S099 | perturbed:0.12:d0.88 | 283.08 | 309.90 | 307.22 | 265–350 | -0.75 |
| 5 | S079 | deep-bench:perturbed:0.12:d0.80 | 283.05 | 309.88 | 307.19 | 265–350 | -0.78 |
| 6 | S030 | deep-bench:Bruno Fernandes | 283.03 | 309.86 | 307.18 | 265–350 | -0.80 |
| 7 | S024 | medium-bench | 284.00 | 309.53 | 306.98 | 265–350 | -1.00 |
| 8 | S002 | static-xp | 283.66 | 309.40 | 306.83 | 265–350 | -1.15 |
| 9 | S009 | premium:Saka+Bruno Fernandes | 283.66 | 309.40 | 306.82 | 264–350 | -1.15 |
| 10 | S049 | historical-bench-band:perturbed:0.12:d0.80 | 283.84 | 309.34 | 306.79 | 265–350 | -1.19 |
| 11 | S019 | historical-bench-band | 283.53 | 309.18 | 306.62 | 265–350 | -1.36 |
| 12 | S119 | perturbed:0.12:d0.95 | 285.03 | 308.13 | 305.82 | 264–349 | -2.15 |
| 13 | S008 | premium:Palmer+Bruno Fernandes | 280.24 | 308.66 | 305.81 | 264–349 | -2.16 |
| 14 | S007 | premium:Isak | 277.82 | 307.67 | 304.68 | 263–347 | -3.29 |
| 15 | S033 | deep-bench:Haaland | 270.38 | 300.77 | 297.73 | 256–340 | -10.24 |

## Independently selected component-native challengers

| Rank | ID | Archetype | Raw mean | Anchored mean | Decision mean | Decision 95% CI Δ | Decision Δ |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | C008 | component-policy:w0.05:d0.95 | 285.18 | 310.54 | 308.01 | -0.04 to +0.10 | +0.03 |
| 2 | C010 | component-policy:w0.15:d0.95 | 289.43 | 310.00 | 307.94 | -0.24 to +0.17 | -0.03 |
| 3 | C006 | component-policy:w0.05:d0.88 | 286.68 | 310.18 | 307.83 | -0.32 to +0.04 | -0.14 |
| 4 | C005 | component-policy:w0.05:d0.80 | 287.25 | 310.06 | 307.78 | -0.37 to -0.02 | -0.20 |
| 5 | C012 | component-policy:w0.25:d0.80 | 289.63 | 309.70 | 307.69 | -0.48 to -0.08 | -0.28 |
| 6 | C003 | component-policy:w0.00:d0.88 | 279.81 | 310.37 | 307.32 | -0.82 to -0.50 | -0.66 |
| 7 | C002 | component-policy:w0.00:d0.80 | 280.58 | 310.23 | 307.27 | -0.90 to -0.52 | -0.71 |
| 8 | C013 | component-policy:w0.25:d0.88 | 290.95 | 308.60 | 306.83 | -1.38 to -0.90 | -1.14 |
| 9 | C001 | component-static:w0.00:d0.80 | 282.00 | 307.31 | 304.78 | -3.34 to -3.06 | -3.20 |
| 10 | C009 | component-static:w0.15:d0.88 | 286.36 | 306.74 | 304.70 | -3.43 to -3.12 | -3.28 |
| 11 | C014 | component-policy:w0.50:d0.80 | 298.54 | 304.96 | 304.32 | -3.92 to -3.39 | -3.66 |
| 12 | C007 | component-static:w0.05:d0.95 | 284.00 | 306.28 | 304.05 | -4.09 to -3.76 | -3.93 |
| 13 | C016 | component-policy:w0.50:d0.95 | 298.29 | 304.67 | 304.03 | -4.20 to -3.68 | -3.94 |
| 14 | C011 | component-static:w0.25:d0.80 | 289.02 | 305.69 | 304.02 | -4.15 to -3.76 | -3.96 |
| 15 | C004 | component-static:w0.00:d0.95 | 277.17 | 306.20 | 303.30 | -4.88 to -4.47 | -4.68 |
| 16 | C015 | component-static:w0.50:d0.95 | 296.16 | 301.63 | 301.08 | -7.13 to -6.66 | -6.89 |
| 17 | C018 | component-policy:w0.75:d0.80 | 299.49 | 300.14 | 300.07 | -8.20 to -7.61 | -7.90 |
| 18 | C020 | component-policy:w0.75:d0.95 | 301.17 | 297.19 | 297.59 | -10.70 to -10.08 | -10.39 |
| 19 | C019 | component-static:w0.75:d0.95 | 298.16 | 295.12 | 295.42 | -12.84 to -12.27 | -12.56 |
| 20 | C017 | component-static:w0.75:d0.80 | 298.25 | 294.14 | 294.55 | -13.72 to -13.13 | -13.42 |
| 21 | C021 | component-policy:w1.00:d0.80 | 302.06 | 293.62 | 294.47 | -13.84 to -13.18 | -13.51 |
| 22 | C022 | component-static:w1.00:d0.95 | 299.73 | 292.19 | 292.95 | -15.34 to -14.72 | -15.03 |

## Top 20 fixed squads

| Rank | ID | Archetype | Bench | Raw mean | Anchored mean | Decision mean | Decision top-three |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | S001 | current-transfer-aware | £22.5m | 282.00 | 307.31 | 304.78 | 3.1% |
| 2 | S084 | deep-bench:perturbed:0.12:d0.88 | £22.5m | 281.75 | 306.78 | 304.28 | 1.6% |
| 3 | S029 | deep-bench | £22.5m | 281.66 | 306.69 | 304.19 | 2.2% |
| 4 | S024 | medium-bench | £21.5m | 282.28 | 306.43 | 304.02 | 1.2% |
| 5 | S099 | perturbed:0.12:d0.88 | £22.5m | 281.37 | 306.47 | 303.96 | 1.0% |
| 6 | S002 | static-xp | £21.5m | 281.92 | 306.29 | 303.86 | 1.4% |
| 7 | S079 | deep-bench:perturbed:0.12:d0.80 | £22.5m | 281.25 | 306.32 | 303.81 | 1.2% |
| 8 | S049 | historical-bench-band:perturbed:0.12:d0.80 | £20.0m | 282.67 | 306.09 | 303.74 | 1.3% |
| 9 | S030 | deep-bench:Bruno Fernandes | £22.5m | 281.14 | 306.20 | 303.69 | 1.4% |
| 10 | S019 | historical-bench-band | £20.0m | 282.36 | 305.93 | 303.57 | 1.4% |
| 11 | S025 | medium-bench:Bruno Fernandes | £21.5m | 281.57 | 305.90 | 303.47 | 0.7% |
| 12 | S003 | premium:Bruno Fernandes | £21.5m | 281.43 | 305.77 | 303.34 | 0.9% |
| 13 | S020 | historical-bench-band:Bruno Fernandes | £20.0m | 282.02 | 305.66 | 303.29 | 1.0% |
| 14 | S059 | historical-bench-band:perturbed:0.12:d0.95 | £19.5m | 281.40 | 305.34 | 302.94 | 2.4% |
| 15 | S080 | deep-bench:perturbed:0.20:d0.80 | £23.0m | 276.25 | 305.73 | 302.78 | 3.7% |
| 16 | S119 | perturbed:0.12:d0.95 | £18.5m | 281.84 | 305.10 | 302.78 | 3.8% |
| 17 | S090 | deep-bench:perturbed:0.20:d0.95 | £23.0m | 277.68 | 305.33 | 302.57 | 3.1% |
| 18 | S095 | perturbed:0.20:d0.80 | £22.5m | 276.77 | 305.42 | 302.55 | 2.4% |
| 19 | S008 | premium:Palmer+Bruno Fernandes | £20.5m | 276.95 | 305.28 | 302.45 | 2.1% |
| 20 | S060 | historical-bench-band:perturbed:0.20:d0.95 | £19.5m | 281.91 | 304.68 | 302.40 | 3.1% |

## Premium and bench interrogation

S001 spends £22.5m on its GW1 bench. The 2019/20 eventual top ten averaged £18.45m (range £16.5m–£24.0m). Those ten managers are survivorship-selected and played under older prices/rules, so this is an audit signal rather than an optimisation target.

| GW1 bench band | Fixed squads | Best fixed decision | Best transfer-aware finalist |
|---|---:|---:|---:|
| ≤£18.5m | 39 | S119 302.78 | S119 305.82 |
| £18.6–20.0m | 26 | S049 303.74 | S049 306.79 |
| £20.1–22.0m | 35 | S024 304.02 | S024 306.98 |
| >£22.0m | 28 | S001 304.78 | S001 307.98 |

Relative to S001, the strongest named-premium policies score: Haaland -10.24, Saka -1.15, Palmer -2.16, Isak -3.29 points over five weeks. Saka therefore wins the residual-policy field, but the independently selected overall recommendation is S001. Bruno Fernandes remains the premium and captain in the promoted squad.

The conclusion is not that an expensive bench is universally desirable. Fixed and transfer-aware winners occupy different bench bands, while the final promoted candidate S001 spends £22.5m on its GW1 bench. Bench spend remains a diagnostic, never a rewarded feature.

## Calibration and identities

All 3,485,805 team goals are reconciled: 3,485,739 player goals and 66 own/unattributed goals (100.000%). The simulated assist/goal ratio is 0.911; bonus averages 6.00 points per match scenario.

Across the 196 players used by the 128 candidate squads, pre-anchor player-event mean absolute error is 0.253 points; after anchoring it is 0.001. The conditional adjustment has mean absolute size 0.434 and P95 1.272.

Literal full anchoring adds 27.24 points to S001 over five weeks (5.45/GW). The season-forward backtest selected only 10% raw component signal, so the evidence-weighted component shift is 0.54/GW. That historically frozen lineup-weighted figure controls the excessive-anchor gate.

This is a selection-tail disagreement, not league-wide point inflation. The raw component model generates 90.29 points per match and xP 94.32, versus 90.48 actually scored in 2025/26. Rolling top-k xP is also historically calibrated within the gate. The raw layer is therefore useful for covariance and sensitivity, but not yet proven superior for identifying the best individual players.

The raw result is the literal component model. The anchored result preserves those match-driven covariance shocks but adjusts marginal means to the promoted xP forecast. The decision column uses the 10% raw weight selected on 2024/25 and then tested unchanged on 2025/26.

## Squad detail for the anchored policy leader

- GK: Donnarumma (MCI, £5.5m)
- GK: Verbruggen (BHA, £4.5m)
- DEF: Tarkowski (EVE, £6.0m)
- DEF: Senesi (TOT, £6.0m)
- DEF: Truffert (BOU, £5.5m)
- DEF: Collins (BRE, £5.5m)
- DEF: Maguire (MUN, £5.0m)
- MID: Bruno Fernandes (MUN, £12.0m)
- MID: Mbeumo (MUN, £8.0m)
- MID: Gibbs-White (NFO, £8.0m)
- MID: Szoboszlai (LIV, £7.0m)
- MID: Tanaka (LEE, £5.0m)
- FWD: Watkins (AVL, £8.0m)
- FWD: Igor Thiago (BRE, £8.0m)
- FWD: Calvert-Lewin (LEE, £6.0m)

## Remaining limitations

The goal model has only a modest out-of-season edge over a home/away baseline. Goal timing is uniform, whether a goal receives an assist still uses a league-level probability, and bonus uses a promoted player-event prior inside a BPS-inspired 3/2/1 approximation rather than a full event-by-event BPS engine. Defensive-contribution probabilities have one season of evidence. The xP anchor is deliberately reported, never disguised as an observed component.
