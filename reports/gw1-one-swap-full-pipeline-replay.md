# GW1 one-swap full-pipeline replay

**Verdict:** `challenger_rejected_by_combined_synthesis`  
**Production changed:** no  
**Published squad retained:** `R-ee60e45c6d`

## Bottom line

The exhaustive one-swap membership audit found a real candidate-coverage gap: replacing Mukiele
with Senesi was the strongest fixed-squad neighbour over GW1–8, but the original robust funnel
dropped it before simulation. A forced replay has now given that squad the same fixed,
open-transfer and forced-GW2-roll treatment as the original deep fields.

The challenger is genuinely strong over the longer horizon, ranking **2nd of 49** and beating the
published squad by **+0.316 decayed points** in the central open-transfer view (95% CI +0.181 to
+0.452). It does not survive the complete decision policy. In the five-week robustness field it
ranks **27th of 65**, trails the published squad by **0.783 points** centrally (95% CI -0.928 to
-0.637), and carries large raw/high-goal regret. Its combined synthesis regret is **1.498**, versus
**0.906** for the published squad.

This is the correct outcome of an adversarial audit: the search gap was real, the candidate was
tested fairly, and the stronger combined policy rejected it. Mukiele stays; no hand edit is made.

## Why the candidate was missed

- The challenger was legal and present in the 299,192-squad first neighbourhood.
- It ranked 930th in that broad first-neighbourhood proxy view.
- After the global/local field was reduced to 30,000, its recalibrated proxy rank was 14,193.
- The robust discovery limit was 10,000, so it was removed before any residual, component or
  holdout simulation.
- The incumbent ranked even lower at 23,617 but survived because it was a protected component seed.

The protection explains the asymmetric coverage. It does not invalidate the final squad because
the forced candidate has now received the omitted deep tests and failed synthesis.

## Evidence by stage

| Stage | Senesi challenger result | Interpretation |
|---|---:|---|
| Fixed-squad GW1–8 residual | +2.396 [2.347, 2.446] | Strong membership-audit signal |
| Fixed-squad GW1–8 component | +2.283 [2.156, 2.410] | Cross-family confirmation |
| Full-field horizon | rank 2/49 | Credible long-horizon candidate |
| Open-transfer GW1–8 | +0.316 [0.181, 0.452] | Edge shrinks when future transfers are available |
| Open-transfer GW1–3 | -0.009 [-0.116, 0.098] | No clear early edge |
| Forced GW2 roll | -0.306 [-0.402, -0.211] | Loses valuable opening optionality |
| Five-week robust field | rank 27/65 | Fails the short/medium robustness family |
| Five-week central vs published | -0.783 [-0.928, -0.637] | Materially behind the current squad |
| Combined synthesis | 1.498 vs 0.906 | Challenger rejected |

## Decision and engineering consequence

The production candidate remains `R-ee60e45c6d`. The audit does identify a useful search-design
lesson: horizon membership checks must include strong legal neighbours that may be mediocre in a
five-week discovery proxy. The horizon audit now retains a separately protected 32-squad neighbour
portfolio across the top eight robust seeds. A live generation check includes this exact Senesi
candidate at portfolio position 26. This closes the measured gap for the next full run without
enlarging the whole production field or promoting a candidate from a fixed-squad headline.

The machine receipt is
`data/model/one_swap_full_pipeline_replay_v1/results.json`. It is checksum-bound to the published
decision, direct/component forecasts, robust results, horizon results and source one-swap audit.
