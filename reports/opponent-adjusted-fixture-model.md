# Opponent-adjusted fixture model — technical decision record

Generated 3 August 2026. This report records the design, leakage controls,
frozen tests and production decision for the new fixture-strength foundation.

## Decision

**Promote `forecast_v3_opponent_adjusted`.** The production model no longer uses
FPL's official fixture difficulty or official attack/defence strengths. It also
removes the old unadjusted five/ten-match team goal averages. A 47-feature
challenger built around dynamic opponent-adjusted ratings passed the
pre-registered champion/challenger gate, the independent model-versus-form gate,
the goal-model gate and the component-simulation gates.

This is an evidence-backed improvement, not a performance guarantee. The model
still has meaningful uncertainty and must be refreshed as real 2026/27 evidence
arrives.

## The problem being solved

“Conceded ten in five” is not a team-strength measurement. It mixes the defence's
ability with the quality of five opposing attacks, venue, scoring environment and
random match outcomes. Two clubs can concede the same number while providing
very different evidence about their future clean-sheet probability.

For each fixture the new online Poisson layer estimates:

```text
home goals λ = exp(league home rate
                   + home attack + home-attack residual
                   - away defence - away-defence residual)

away goals λ = exp(league away rate
                   + away attack + away-attack residual
                   - home defence - home-defence residual)
```

Positive attack is stronger; positive defence is better. After a result, the
Poisson surprise `actual goals − expected goals` updates both the scoring team's
attack and the opponent's defence. Conceding two when the model expected two is
approximately neutral. Conceding two when it expected 0.8 is negative evidence.
This opponent feedback is the schedule adjustment.

### A real example from the data

Before 2025/26 GW9, Manchester United had conceded eight in five:

| Opponent | Venue | Conceded | Pre-match expected against |
|---|:---:|---:|---:|
| Manchester City | A | 3 | 1.76 |
| Chelsea | H | 1 | 1.47 |
| Brentford | A | 3 | 1.71 |
| Sunderland | H | 0 | 1.09 |
| Liverpool | A | 1 | 2.15 |
| **Total** |  | **8** | **8.18** |

A raw model sees 1.6 conceded per match. The adjusted model sees a difficult run
that was fractionally better than its 8.18-goal expectation, so United entered
GW9 with a near-league-average positive defensive rating (`+0.003`) rather than
receiving an automatic “bad defence” label. That is the requested sophistication
in concrete form.

## Point-in-time construction

- 2,660 completed Premier League fixtures from 2019/20–2025/26 produce 5,320
  pre-decision fixture-side snapshots.
- Initial league scoring rates are estimated only from the prior 2018/19 season:
  1.568 home and 1.253 away goals.
- Every player in an FPL event receives one shared rating snapshot before that
  event's first kickoff. Results from the first match of a double gameweek can
  never leak into features for its second match.
- Historical seasons without archived exact deadlines use one second before the
  event's earliest kickoff. This is conservative and preserves the essential
  property that no target-event result is available.
- Matches sharing a kickoff are predicted as a batch, then updated as a batch.
  Their results cannot leak sideways into one another.
- Ratings decay continuously toward the league prior. The selected base half-life
  is 540 days; venue residuals decay faster at 240 days.
- Surprise updates are clipped at 2.5 goals so one freak score cannot rewrite a
  club's identity.

The data-quality suite explicitly verifies unique fixture-side keys, pre-kickoff
timestamps, one information set per event, complete current-player coverage,
valid goal/clean-sheet probabilities and entrant-prior coverage.

## Home and away are hierarchical, not separate small samples

Each club has a shared attack and defence plus smaller home and away residuals.
This lets 266 matches of Arsenal history inform both venues while still learning
that a club may press, create or defend differently at home. The selected learning
rates are `0.030` for shared strength and `0.010` for venue residuals, preventing
the noisier venue split from overwhelming the larger sample.

The model exposes both base and at-venue attack/defence, opponent equivalents,
expected goals, expected goals against and clean-sheet probability. Tree models
can use the direct expectation or learn position-specific interactions—for
example, clean-sheet probability is especially important to goalkeepers and
defenders.

## Promoted and returning clubs

The system identifies entrants by stable team code relative to the previous
Premier League season. It does not leave them null and does not pretend they are
league average.

- Earlier entrant cohorts supply empirical end-of-first-season attack/defence
  evidence using only seasons completed at the prediction date.
- Cohorts are recency weighted and shrunk toward a conservative fallback with six
  prior-equivalent clubs, limiting the effect of one exceptional promoted class.
- A returning club blends 20% of its decayed old Premier League identity with 80%
  of the promoted prior.
- For 2026/27 the learned entrant prior is attack `−0.208`, defence `−0.172`.
  Coventry and Hull receive the entrant prior. Returning Ipswich blends it with
  its decayed 2024/25 state and starts at attack `−0.192`, defence `−0.180`.

This uses no future data and no FPL official strength rating. A future improvement
would incorporate point-in-time Championship xG and squad continuity when a
reliable open historical source is available.

## Parameter selection and frozen score test

Twenty-seven configurations crossed three shared learning rates, three venue
learning rates and three decay half-lives. Only 2021/22 and 2022/23 selected the
configuration. The following three seasons stayed frozen:

| Season | Fixtures | Goal MAE | Poisson deviance | Clean-sheet Brier |
|---|---:|---:|---:|---:|
| 2023/24 | 380 | 0.975 | 1.089 | 0.156 |
| 2024/25 | 380 | 0.927 | 1.091 | 0.172 |
| 2025/26 | 380 | 0.898 | 1.088 | 0.182 |
| **Frozen aggregate** | **1,140** | **0.933** | **1.089** | **0.170** |

The downstream GPU goal model also replaces all official/raw fixture features
with the adjusted layer. Against a simple expanding home/away rate it improves
Poisson deviance from 1.188 to 1.109 in 2024/25 and from 1.126 to 1.084 in
2025/26. Clean-sheet Brier improves in both seasons.

## Player-model fixture ablation

All variants below used the same 244,425 player-event rows, rolling train/test
seasons, position-specific hurdle models, targets and RTX 5090 CUDA path. Only
the feature contract changed.

| Variant | Features | MAE | Mean GW rank | Top-k actual pts | GW1 top-k | Legal GW1 total |
|---|---:|---:|---:|---:|---:|---:|
| Player only | 28 | 0.9780 | 0.6964 | 3.984 | 3.955 | 111 |
| Old official/raw fixture model | 41 | 0.9452 | 0.6968 | 4.098 | 3.748 | 138 |
| Opponent-adjusted, base ratings | 40 | 0.9457 | 0.6974 | 4.158 | 3.891 | 121 |
| **Opponent-adjusted + home/away** | **47** | **0.9467** | **0.6974** | **4.200** | **3.816** | **137** |

The full challenger adds `+0.102` realised top-group points per selected player per
gameweek over the old model and wins/ties that metric in nine of twelve
season-position slices. Rank improves by `+0.00062`; MAE is `0.00150` worse, well
inside the pre-registered 0.01 non-inferiority margin. The three-season legal GW1
replay is one point worse (137 versus 138), so it remains a disclosed high-variance
diagnostic rather than being hidden or used to tune the gate.

Removing fixtures entirely is materially worse. Adding home/away context on top
of base opponent adjustment raises top-group points from 4.158 to 4.200. Those
results support both the general fixture layer and the venue-specific extension.

In the final fitted point models, adjusted fixture features account for 44.7% of
total split gain for goalkeepers, 49.6% for defenders, 18.3% for midfielders and
26.1% for forwards. Split gain is descriptive, not causal, but confirms the model
is actively using the new signal.

## Current GW1 team expectations

| Fixture side | Opponent | Venue | Expected goals | Expected against | Clean sheet |
|---|---|:---:|---:|---:|---:|
| Arsenal | Coventry | H | 2.15 | 0.70 | 49.8% |
| Manchester United | Hull | A | 1.89 | 1.10 | 33.3% |
| Manchester City | Bournemouth | H | 1.77 | 1.05 | 34.8% |
| Newcastle | Liverpool | H | 1.80 | 1.56 | 21.0% |
| Liverpool | Newcastle | A | 1.56 | 1.80 | 16.6% |
| Nottingham Forest | Leeds | H | 1.49 | 1.06 | 34.8% |
| Coventry | Arsenal | A | 0.70 | 2.15 | 11.7% |

The complete 20-side × eight-gameweek grid is stored in the normalized current
ratings artifact and is aggregated into every player horizon row.

## Decision impact and premium interrogation

The production training gate passed with 11/12 top-group wins over rolling form
and positive full-season and GW1 lifts. The rebuilt exact squad spends the full
£100.0m, projects 57.99 GW1 points and captains Bruno Fernandes.

That squad (`S001`) then survived three separate challenges:

- first of 128 in the 25,000-draw residual holdout;
- first under the equal free-transfer policy envelope;
- first under the evidence-weighted 25,000-draw match-component simulation, whose
  twelve adversarial promotion gates all passed.

Premium-bearing challengers were forced into the candidate population rather
than allowed to disappear during optimisation. Over five evidence-weighted
gameweeks, the strongest Saka, Palmer, Isak and Haaland structures trail S001 by
1.47, 2.52, 3.49 and 8.11 points respectively. Bruno is already S001's premium
and captain. This is why the output lacks a second marquee premium; it was tested,
not forgotten.

The £22.5m GW1 bench remains a legitimate warning. S001 leads under the model and
transfer policy, but the exact squad appears in only 5% of 20 perturbed optimiser
runs while retaining 84% of its players on average. The recommendation is strong
at its core and captain (100% stable), but several fringe places are close. That
is a reason to monitor preseason minutes and injuries, not a reason to override
the evidence today.

## Remaining adversarial concerns

1. Actual goals, not team xG, drive the dynamic rating updates. Opponent adjustment
   removes a major bias but cannot remove finishing and goalkeeping variance as
   efficiently as a reliable point-in-time xG feed could.
2. The promoted prior is league-level. It does not yet understand a specific
   entrant's Championship dominance, transfers, manager or tactical continuity.
3. Historical deadlines are conservatively inferred where the source lacks exact
   archived timestamps. This prevents target leakage but can omit information
   that might truly have been known before an unusually delayed deadline.
4. Venue residuals improve the main top-group metric, but their incremental gain
   is modest; the 240-day shrinkage must remain in place.
5. Rules such as defensive contributions have much less history than goals and
   clean sheets. The component engine therefore keeps strong xP anchoring and
   exposes its raw disagreement.
6. This is a retrospective foundation. Prospective 2026/27 calibration, closing
   lineups, transfers and injuries remain mandatory before every deadline.

## Reproducible artifacts

- Ratings: `data/model/normalized/opponent_adjusted_team_strength.parquet`
- Current rating grid: `data/model/normalized/current_opponent_adjusted_team_strength.parquet`
- Calibration: `data/model/normalized/team_strength_metrics.json`
- Fixture ablation: `data/model/artifacts/fixture_ablation_v1/metrics.json`
- Production model metrics: `data/model/artifacts/forecast_v2/metrics.json`
- Goal model metrics: `data/model/artifacts/component_v1/goal-model-metrics.json`
- Component gate: `data/model/component_backtest_v1/metrics.json`
- Current squad: `data/decisions/2026-27-gw1-initial-squad.json`
- Final tournament: `data/model/tournament_v2/component-gw1-5-results.json`

