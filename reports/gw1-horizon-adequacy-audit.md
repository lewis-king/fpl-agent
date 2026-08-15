# GW1 horizon-adequacy audit

**Built:** 2026-08-15T16:14:58.005523+00:00<br>
**Verdict:** long_horizon_challenger_promoted<br>
**Leader:** R-1ca68907f5 · 4-4-2 · Bruno Fernandes captain · £20.5m bench

**Scope note:** this is the horizon-family verdict, not the final cross-model decision. See `reports/gw1-synthesized-decision.md` for the synthesis with scoring-environment and component-model stress.

## Answer

This audit does not assume that five equal gameweeks are the correct outset. It re-simulates GW1–8 and evaluates short, medium, decayed long, late-fixture, fixed-squad and forced-GW2-bank views.

The eight-week leader is **R-1ca68907f5**. Against the five-week incumbent **R-083607ec8c**, its paired central delta is +1.027 points (95% CI +0.877 to +1.176).

## Evaluation funnel

| Stage | Count |
|---|---:|
| Five-week finalists carried forward | 64 |
| New horizon-specific squads | 128 |
| Protected legal neighbours | 32 |
| Selection worlds | 5,000 |
| Deep finalists | 48 |
| Eight-week holdout worlds | 25,000 |

## Scenario comparison

| Scenario | Leader | Incumbent | Leader regret | Weight |
|---|---:|---:|---:|---:|
| gw1 3 open d088 | 165.96 | 164.92 | 0.00 | 10% |
| gw1 5 open d088 | 243.57 | 243.06 | 0.00 | 15% |
| gw1 8 open d070 | 195.51 | 194.61 | 0.00 | 10% |
| gw1 8 open d080 | 258.81 | 257.88 | 0.00 | 10% |
| gw1 8 open d088 | 331.86 | 330.83 | 0.00 | 15% |
| gw1 8 open d094 | 404.75 | 403.56 | 0.00 | 10% |
| gw6 8 open equal | 189.17 | 187.93 | 0.00 | 10% |
| gw1 8 fixed d088 | 328.06 | 327.32 | 0.12 | 5% |
| gw1 8 roll gw2 d088 | 331.49 | 330.71 | 0.00 | 15% |

## What strong managers historically did

The public 2019/20 top-ten squads retained the following number of their original 15 players. Early wildcard use is reported separately because it explains much of the sharp drop.

| GW | Mean retained | Median | Range |
|---:|---:|---:|---:|
| 2 | 13.0 | 14.0 | 7–15 |
| 3 | 11.9 | 13.0 | 7–14 |
| 4 | 7.5 | 7.5 | 1–13 |
| 5 | 7.2 | 6.5 | 2–12 |
| 6 | 6.7 | 6.5 | 2–12 |
| 7 | 6.2 | 6.0 | 2–11 |
| 8 | 5.9 | 5.5 | 2–10 |

Early chips in that cohort: GW2 wildcard ×2, GW4 freehit ×1, GW4 wildcard ×4, GW5 3xc ×1, GW5 wildcard ×1.

The 2025/26 top-100 trail shows that 61 managers rolled in GW2, while only 22 did so in GW3 and 19 in GW4. Strong managers therefore preserved optionality initially but adapted quickly when evidence arrived.

**Evidence caveat:** The 2019/20 cohort contains only ten elite managers and unusually early wildcard use; the 2025/26 top-100 trail is richer but transfer rows include wildcard restructures. These data inform decay and adaptability, not a causal optimal horizon.

## GW1 team

- **GK:** Donnarumma
- **DEF:** Tarkowski (V), Maguire, Collins, Senesi
- **MID:** Bruno Fernandes (C), Mbeumo, Semenyo, Szoboszlai
- **FWD:** Igor Thiago, Watkins

## Interpretation

GW6–8 are included, but discounted because current information about minutes, form and injuries is materially weaker. The separate equal-weight GW6–8 scenario prevents an easy opening run from hiding a poor late fixture block. Fixed and forced-bank scenarios prevent the audit from assuming perfect transfer execution.

**Deadline rule:** Rerun after the final pre-GW1 forecast refresh. Do not promote a horizon challenger unless its paired eight-week interval excludes zero and it remains within the declared central-regret cap.
