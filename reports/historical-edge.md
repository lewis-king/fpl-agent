# FPLAgent historical edge study

Generated 2026-08-02T09:05:56.901528+00:00. This is an evidence audit, not a claim that historical
correlations guarantee a future finish. All figures are reproducible with `uv run fpl-data analyse`.

## Executive answer

The data rejects both comforting extremes. Winning is neither pure luck nor a collection of
clever differentials. The repeatable foundation is consistently selecting high expected-point
routes, preserving optionality, and evaluating transfers over multiple gameweeks. Extreme final
ranks additionally require favourable realised variance.

The exact 2025/26 top 100 averaged **2,504.1 points**, against
**2,090.9** for the 3.53m active-manager population. Of that
413.2-point gap, 234.6
points (57%) came from Solio's projected quality of the weekly
picks and 178.7 from finishing above projection. Only
2 of the actual top 100 were themselves projected top-100 managers;
their median projected rank was 73,694.

The reverse view is healthier for product design: the 100 best projected managers had a median
actual rank of **7,448**; 55%
finished inside the top 10k and 16% inside the top 1k. A process can
produce a formidable finish distribution without being able to promise the single realised winner.

## What strong managers actually did

### Captaincy: deviation was selective, not the objective

Across 3,800 top-100 captain decisions, the model comparator and manager agreed
2,235 times (58.8%). Managers deviated
1,565 times. Those deviations won 961 and lost
482, with a realised mean edge of
5.2 points.

That is descriptive survivorship evidence: this cohort was selected because it finished top 100,
so its successful captain deviations cannot be treated as a prospective causal return. The usable
lesson is narrower: do not reward rarity. Recommend a non-template captain only when the forecast
distribution independently gives that player the better risk-adjusted score.

The independent 2019/20 top-ten picks reinforce how noisy hindsight is. Their captain happened to
be the highest-scoring player in their own 15 only
22.4% of 380 manager-weeks; the mean hindsight gap was
6.6 points. Excluding Bench Boost weeks, they fielded
the hindsight-best legal XI only 28.6% of the time, with
3.4 points of mean lineup regret. That oracle was not
available at the deadline. We should judge captain and bench calls against the **pre-deadline
forecast distribution**, never whether the benched player later hauled.

### Transfers: horizon and restraint both matter

The cohort rolled a transfer a mean **11.1 weeks** each
(range 4–19).
Their recorded moves produced mean player-in minus player-out returns of
2.1, 3.0, and
4.5 points over one, three, and five gameweeks. The widening edge
supports planning transfers across horizons rather than chasing only the next fixture.

There were only 92 paid-hit events (392 points of
cost) among 100 managers. Paid moves show 9.4 mean three-GW
gross alpha versus 2.9 for free moves, but this is again
selected-on-success evidence and the gross comparison does not license indiscriminate hits. A hit
must clear its cost under uncertainty and improve the multi-week squad state.

### Counts are not a strategy

The independent 2019/20 top-50 archive averaged 50.5 transfers and
19.4 hit points. Within that already elite sample, transfer count had
almost no relationship with rank (r=-0.009); captain points were more
favourable but still weak (rank r=-0.145). The top ten actually
took more hits on average than ranks 41–50 (17.2 vs
11.6). This does **not** mean hits help—it means decision quality
dominates a blanket rule about activity.

The 27-manager Titan cohort tells a similar cautionary story. Final rank correlated
-0.470 with average squad value and
0.299 with transfer cost (lower rank is better), while experience
was essentially unrelated (-0.038). These are small observational
samples; squad value and bench points also proxy a generally successful squad and are not causal
targets by themselves.

### Budget: cash is a constraint, not a score

The 2019/20 top ten averaged a weekly team value of £104.6m,
and higher average squad value was associated with better rank in the small Titan cohort. That
supports auditing the old app's habit of leaving money unused, but it does not justify a blanket
“spend everything” rule. Bank is valuable when it unlocks a later transfer or avoids a hit. The
engine must calculate **unused-budget opportunity cost**: the expected multi-horizon gain of the
best legal upgrade currently declined. Cash is suspicious only when that gain exceeds the option
value of keeping it.

## Leakage-safe player forecast baseline

Each historical player-fixture record was first aggregated to player/gameweek so double-gameweek
returns remain one decision target. Every predictor is lagged: prior points, minutes, appearance
rate, price, ownership, ICT/BPS and expected-stat form. The model never sees same-gameweek goals,
minutes, transfers, ownership or results. Players needed at least three prior observations and a
30-minute recent average. Separate ridge models were fitted by position using only seasons before
the test season.

| Season | Signal/model | MAE | GW rank corr. | Top-15 pts/player | Captain pts |
| --- | --- | ---: | ---: | ---: | ---: |
| 2023-24 | Five-GW points average | 2.335 | 0.278 | 4.46 | 5.11 |
| 2023-24 | Season-to-date points average | 2.179 | 0.286 | 4.63 | 5.69 |
| 2023-24 | Lagged ownership (ranking only) | n/a | 0.182 | 4.58 | 6.40 |
| 2023-24 | Current-row FPL xP (unsafe diagnostic) | 1.714 | 0.648 | 7.99 | 10.06 |
| 2023-24 | Ridge: lagged form + availability | 2.093 | 0.396 | 5.07 | 6.57 |
| 2023-24 | Ridge: + lagged underlying stats | 2.099 | 0.408 | 5.09 | 6.00 |
| 2024-25 | Five-GW points average | 2.243 | 0.287 | 4.34 | 6.57 |
| 2024-25 | Season-to-date points average | 2.098 | 0.316 | 4.68 | 8.71 |
| 2024-25 | Lagged ownership (ranking only) | n/a | 0.202 | 4.38 | 7.94 |
| 2024-25 | Current-row FPL xP (unsafe diagnostic) | 1.759 | 0.628 | 6.95 | 11.03 |
| 2024-25 | Ridge: lagged form + availability | 2.031 | 0.378 | 5.22 | 9.20 |
| 2024-25 | Ridge: + lagged underlying stats | 2.009 | 0.385 | 5.23 | 8.89 |
| 2025-26 | Five-GW points average | 2.440 | 0.207 | 3.91 | 4.14 |
| 2025-26 | Season-to-date points average | 2.282 | 0.235 | 4.29 | 6.43 |
| 2025-26 | Lagged ownership (ranking only) | n/a | 0.171 | 4.08 | 5.09 |
| 2025-26 | Current-row FPL xP (unsafe diagnostic) | 2.619 | 0.643 | 3.66 | 5.71 |
| 2025-26 | Ridge: lagged form + availability | 2.148 | 0.338 | 4.67 | 6.20 |
| 2025-26 | Ridge: + lagged underlying stats | 2.143 | 0.334 | 4.65 | 6.63 |

This is a **benchmark**, not the production model. Its purpose is to make future XGBoost/RF/ensemble
work beat a fixed, time-ordered baseline. `current_xp_unsafe` is deliberately included only as a
leakage diagnostic because Vaastav documents that the field may have been captured after matches.
It is forbidden as a production feature. The ridge model improves gameweek ranking materially over
raw five-GW form in every test season. Adding rolling expected/ICT statistics does **not** improve
the ranking consistently, so a naive “more stats” model has failed its first audition. The next
candidate needs nonlinear interactions, explicit opponent strength and a proper minutes/appearance
model—not cosmetic feature accumulation. OpenFPL independently supports position-specific public
data ensembles and prospective season isolation, but our implementation must beat these local
baselines on untouched future gameweeks.

Top-15 and captain columns are ranking diagnostics over eligible players, not scores from a legal,
budget-constrained squad. They intentionally separate forecast quality from the optimizer that we
will test next. Eligibility removes the opening three observations, so each season reports up to
35 evaluated gameweeks.

### Which individual signals survived?

| Lagged signal | Mean GW rank correlation | Top-15 pts/player |
| --- | ---: | ---: |
| Season-to-date points | 0.279 | 4.54 |
| Five-GW points | 0.257 | 4.24 |
| Three-GW minutes | 0.254 | 3.18 |
| Five-GW BPS | 0.241 | 4.11 |
| Lagged price | 0.212 | 4.50 |
| Five-GW appearance rate | 0.210 | 2.96 |
| Five-GW xGI | 0.197 | 4.36 |
| Lagged ownership | 0.185 | 4.35 |
| Five-GW threat | 0.177 | 4.22 |

Minutes and appearance history are essential for estimating whether points are available at all,
but do not rank upside alone. Price and ownership are useful market priors, not objectives. Recent
points/BPS/threat carry signal, while the raw xGI aggregate has too little stable incremental value
in this linear setup to justify calling it an edge. These variables remain candidates for a
nonlinear, position-specific model with opponent and minutes interactions.

## Evidence classification

| Finding | Status | Product consequence |
| --- | --- | --- |
| Better projected weekly picks strongly improve finish distribution | Strong, population-scale but one season/model | Expected points remains the default objective |
| Extreme top-100 outcomes contain substantial positive variance | Strong descriptive evidence | Communicate ranges; do not overfit winner quirks |
| Transfer edge is larger over 3–5 GWs than one GW | Useful selected-cohort evidence | Optimize several horizons and replan each deadline |
| Strong managers frequently roll | Descriptive but consistent with option value | “No move” must be a first-class action |
| Differential captains worked in the realised top 100 | Hindsight-selected, non-causal | Never add a differential bonus by default |
| More transfers or hits cause better ranks | Unsupported | Score the move, not activity |
| Current-row historical xP is safe | Rejected by source timing | Ban it; allow only timestamped pre-deadline forecasts |
| Bench points should simply be minimized | Unsupported/confounded | Value squad resilience, then optimize lineup separately |

## What the historical corpus cannot solve by itself

This baseline deliberately starts after three player observations, so it is not a GW1 model.
Preseason needs a separate cold-start layer joining players across seasons by stable player code,
carrying prior-league performance, promoted-team strength, expected minutes, injuries/suspensions
and likely roles. New signings without Premier League history need league-strength translation and
wider uncertainty. Deadline news and predicted lineups must be timestamped independently; an LLM
may summarize attributable reports, but it must never invent or numerically override the structured
availability model.

Rule eras also need explicit treatment. The 2025/26 outcomes include defensive contributions and
two copies of several chips, while older seasons do not. Raw historical points remain useful labels
for the rules actually played, but a 2026/27 optimizer must use the normalized current scoring and
chip tables rather than blindly extrapolating old positional value.

## Backtestable policy v0

For every deadline, the engine should generate legal action bundles—roll; free transfers; paid
transfers; captain/vice; bench and formation; chip variants—and simulate them over 1, 3, 5 and 8
gameweeks. The primary score is expected total FPL points, including captain multiplier, autosub
probability, hit cost, banked-transfer option value and chip opportunity cost.

Uncertainty is represented with outcome distributions, not a fixed “differential” bonus. Default
risk targets maximum expected points with a downside constraint. Mini-league context may alter the
utility curve late in the season: leaders reduce avoidable covariance and tail risk; materially
trailing managers can accept higher variance when the expected-point sacrifice is bounded. Overall
points strength remains the prior, as requested—the mini-league opponent is context, not the main
game.

A recommendation is allowed only if it records a pre-deadline receipt containing the data snapshot,
model version, predicted distribution, chosen action, best rejected alternative and why. Those
receipts become the prospective dataset that the public historical record cannot provide.

## Non-negotiable evaluation gates

1. Season-forward splits only; no random train/test rows.
2. Features must have an `available_at` timestamp earlier than the FPL deadline.
3. Compare against roll, five-GW form, ownership, official safe forecast when available, and the
   prior production model.
4. Report MAE/RMSE **and** decision metrics: captain regret, transfer net gain, top-k high-return
   recall, squad points, chip value and rank-distribution simulation.
5. Lock an untouched 2026/27 prospective holdout. Do not tune on Lewis's realised results.
6. Promote only on repeated improvement across seasons/positions and no material downside-tail
   regression.

## Sources and limitations

- [Solio EOS](https://eos.solioanalytics.com/) defines projected points as its model expectation
  from each manager's weekly picks. It is a third-party retrospective evidence layer, not truth.
- [Vaastav's data dictionary](https://github.com/vaastav/Fantasy-Premier-League/blob/master/DATA_DICTIONARY.md)
  explicitly warns that historical `xP` timing may be post-match.
- [OpenFPL](https://arxiv.org/abs/2508.09992) reports prospective 2024/25 performance from
  position-specific public-data ensembles, supporting it as a benchmark direction—not as proof
  that our implementation will inherit its results.
- Top-manager action datasets are selected on final performance. They reveal behaviours worth
  testing, but cannot estimate an unbiased causal advantage without a contemporaneous control
  cohort.
- Complete all-manager decision histories do not exist publicly across old seasons. The mandatory
  2026/27 collector must therefore preserve our own and opt-in users' public pre-deadline states.
