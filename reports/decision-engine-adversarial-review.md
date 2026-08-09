# Adversarial review of the FPLAgent foundation

**Reviewed:** 2 August 2026  
**Target:** [decision-engine foundation](decision-engine-blueprint.md)

## Verdict

The plan is viable, but the data already fetched is not yet sufficient to justify a “bulletproof”
model or an honest full-season strategy backtest. The initial draft would have failed in three
material ways:

1. it treated final historical files as though they represented deadline knowledge;
2. it risked confusing outcome variance with model uncertainty and penalizing legitimate upside;
3. it gave a multi-period optimiser more confidence in distant fixtures and tiny xP differences
   than the forecasts deserve.

The revised blueprint fixes those design flaws with deadline-proxy reconstruction, separate
uncertainty types, current-rule target decomposition, perturbation-tested actions and a prospective
receipt stream. It is strong enough to implement. It is not evidence that the product will win
every league; that evidence can only begin accumulating before the first 2026/27 deadline.

## Attack matrix

| # | Attack | Severity | What would go wrong | Required defence |
| ---: | --- | --- | --- | --- |
| 1 | Post-deadline leakage | Critical | Offline metrics look extraordinary and collapse live | `observed_at < deadline`, feature allowlist, banned-field tests |
| 2 | Final fixture-calendar leakage | Critical | Chip/multi-week backtests know later postponements | Git-history fixture snapshots; label final-calendar runs as upper bounds |
| 3 | Scoring-rule drift | Critical | Old points teach the wrong 2026/27 player value | Stable component targets, `bps_era`, executable current rules |
| 4 | DNP dilution | Critical | Low RMSE comes from predicting near zero for everyone | Separate calibrated participation/minutes model and high-return metrics |
| 5 | Optimizer's curse | Critical | Solver makes churn/hits for noise measured in tenths | Forecast perturbation, route stability, roll comparator, learned buffer |
| 6 | Incorrect FPL state transitions | Critical | Attractive recommendation is unaffordable or illegal | Versioned state machine, golden/property tests, independent objective replay |
| 7 | LLM authority creep | Critical | Hallucinated news silently changes captain or transfer | Structured attributable claims only; numeric engine works with LLM off |
| 8 | Backtest overfitting | Critical | Architecture is selected after repeatedly inspecting the “test” seasons | Treat inspected seasons as development; freeze 2026/27 prospective holdout |
| 9 | Independent outcome simulation | High | Clean sheets, goals, bonus and captain tails are incoherent | Match-level correlated event generation |
| 10 | Direct-points target shrinkage | High | Haulers are systematically under-ranked | Component challenger, weighted objective and top-return decision metrics |
| 11 | Survivor bias from top managers | High | Mimicking lucky top-100 deviations is mistaken for causal edge | Use top-manager data descriptively, never as a decision target |
| 12 | GW1/new-player failure | High | Historic form is missing exactly when the first squad is chosen | Cold-start hierarchy, promoted/new-signing priors and wider uncertainty |
| 13 | Stale availability/news | High | A strong numeric forecast assumes an unavailable player starts | Snapshot TTL, last-update display and fail-closed recommendation state |
| 14 | Sparse DC/BPS evidence | High | One season is overfit under another season's scoring | Separate submodels, strong shrinkage, prospective recalibration |
| 15 | Mini-league overreaction | High | Early “differentials” sacrifice points for simulation noise | Expected-points default; late-only podium switch with sacrifice cap |
| 16 | Mistaking GPU capacity for signal | High | Large search/deep net memorizes a small drifting dataset | Frozen baselines, nested rolling validation, prefer tabular models |
| 17 | Source/licensing failure | High | A core feed disappears or cannot support a paid product | Source register, raw provenance, adapters, commercial-rights review |
| 18 | Identity/position errors | High | History joins to the wrong player or old position | Stable code/opta mapping, season position, one-to-one validation |
| 19 | Price/sell-value approximation | High | Multi-week route is infeasible after price movement | Exact purchase-price state; price scenarios; re-solve on material moves |
| 20 | False chip certainty | High | Solver spends a chip before later doubles/blanks are known | Schedule scenarios, terminal option value and high stability threshold |
| 21 | Data-label corrections | Medium | Training mixes provisional and final scores | Version labels; train on final, audit both |
| 22 | Metric gaming | Medium | Better MAE produces worse squads/captains | Proper scores plus legal policy replay and top-return metrics |
| 23 | Manual override hindsight | Medium | “Expert adjustments” become untracked leakage | Source, author, timestamp, reason, expiry and counterfactual logging |
| 24 | Serving drift | Medium | API uses a different feature/rule/model bundle from research | Content-addressed artifacts and receipt hashes |
| 25 | Herd-signal feedback | Medium | Ownership improves fit but turns consensus into a self-fulfilling recommendation | Deadline-safe ownership, ablation tests, never use it as the objective |

## Detailed challenges and revisions

### Challenge 1: “You have historical data” is not the same as “you have training data”

The match outcomes are strong. The deadline state is not. Final `fixtures.csv` files contain later
rescheduling knowledge, while final `players_raw.csv` files contain late-season price, ownership
and availability. A multi-week optimiser tested against them can leak without touching an obvious
same-row outcome column.

**Finding:** the source repository has near-weekly player/fixture commits for 2023/24 (39) and
2024/25 (37), but only 12 in 2025/26. These can create shifted deadline proxies, not exact news-at-
deadline states.

**Revision forced:** reconstruct all commit versions, add `is_deadline_proxy`, restrict strategic
claims to covered deadlines and make 2026/27 snapshots the only untouched truth set.

### Challenge 2: a single points regressor learns obsolete rules

Historic total points combine football skill with the scoring policy of the day. Defensive
contribution points began in 2025/26. In 2026/27, being tackled no longer loses BPS, CBI earns one
BPS per three rather than two, and goalkeeper save BPS changed. A defender's old target is not the
same economic object as a current defender's target.

**Revision forced:** predict stable components, DC and bonus separately; apply current scoring at
simulation time. Keep a direct points model only as a rule-era-aware challenger.

### Challenge 3: the easiest model can win RMSE by being useless

Even among the currently filtered historical candidates, 15–22% did not appear, depending on
position. Across the entire player pool zeroes dominate. A conservative model can improve RMSE
while missing the players whose hauls decide captaincy and transfers.

**Revision forced:** participation is its own calibrated task; the promotion gate includes proper
distribution scores, DNP calibration, top-15 yield and 5+/10+ return ranking. A separate haul head
may improve ranking, but outcome-based sample weights cannot redefine the primary expected-points
estimate without an explicit recalibration step.

### Challenge 4: “risk-adjusted” can be the wrong objective

Football variance is not automatically bad. Penalizing outcome variance all season would steer the
model toward low-ceiling assets even where their expected points are inferior. The real enemy is
forecast uncertainty and brittle optimization. Conversely, when chasing a late mini-league gap,
some variance and lower covariance with rivals can be valuable.

**Revision forced:** distinguish aleatoric outcome variance from epistemic model uncertainty. Base
policy maximizes expected points and is robust to estimation error. Outcome-shape preferences enter
only through a late, explicit podium-probability objective.

### Challenge 5: the solver is more certain than the forecast

MILP solvers optimize precisely; xP is imprecise. Without protection, the solver will spend a
transfer to gain 0.2 modeled points or make an implausibly concentrated team because it treats
every estimate as truth.

**Revision forced:** deterministic MILP only generates high-quality legal policies. A correlated
scenario stage re-ranks them, and each action publishes its stability under out-of-fold error
perturbations. Roll and low-churn routes are mandatory comparators.

### Challenge 6: multi-period precision is fictional beyond the information horizon

An eight-gameweek horizon is useful for transfer value, but injuries, role changes, cup draws and
rescheduling make its raw xP less reliable. A naive sum over eight weeks gives the distant forecast
false authority and can mishandle chip option value.

**Revision forced:** horizon-specific calibration, decreasing decision weight, re-planning every
deadline, schedule scenarios for uncertain fixtures and a terminal value for retained transfers,
bank and chips. Eight weeks is a planning horizon, not a fixed plan.

### Challenge 7: top-manager actions are selected on success

The 2025/26 top 100 often beat a template captain when they deviated, but they were selected because
their realized seasons were excellent. Training an imitation model on those deviations would learn
survivorship and variance.

**Revision forced:** top-manager data informs hypotheses and policy diagnostics only. Player outcome
models train on the full player outcome universe; policies are graded against pre-deadline forecasts
and unbiased/replay comparators.

### Challenge 8: cold start may decide the season before the main model is usable

The existing benchmark waits for three player observations. That excludes GW1 and loses the value
of reacting correctly in GW2–3. Sixty-seven current players have no match in the ten-season player
identity union, and promoted clubs change the team distribution.

**Revision forced:** a separate preseason hierarchy, returning-player joins, promoted-team priors,
structured role evidence and uncertainty widening. It blends out gradually; it is not a zero-filled
version of the in-season model.

### Challenge 9: bonus and DC are not fully reconstructable

FPL exposes total BPS but not a consistent decade of every underlying Opta action, and 2026/27 adds
new save distinctions. Pretending to apply the full new BPS formula to old incomplete events would
be false precision.

**Revision forced:** bonus is a calibrated rule-era residual/ranking model, not claimed exact.
Defensive contributions use explicit counts where available and conservative priors elsewhere.
Prospective 2026/27 collection becomes the decisive calibration set.

### Challenge 10: the LLM creates a tempting untestable back door

News and tactical context matter, but free-form LLM judgement can change any result after the fact.
That destroys reproducibility and exposes the system to hallucination or prompt injection.

**Revision forced:** an LLM can produce only provenance-bearing structured claims or prose derived
from a finished receipt. Numeric changes occur through deterministic, versioned feature mappings.

### Challenge 11: the 5090 can accelerate the wrong work

Roughly a quarter-million fixture rows with heavy within-player/team dependence do not support an
unconstrained deep model or thousands of independent hyperparameter trials. Compute does not create
independent seasons.

**Revision forced:** XGBoost/RF, hierarchical count models and rolling-fold searches first. Use the
GPU for speed and simulations. A neural model must later beat those baselines under identical
point-in-time gates; architecture novelty receives no credit.

### Challenge 12: one guinea pig cannot validate a forecast model

Lewis's realized score is the product goal, but one squad produces only 38 path-dependent samples.
Changing models after each bad captain outcome would overfit noise; following one strong season
could equally enshrine luck.

**Revision forced:** grade forecasts over every player/fixture and decisions over frozen historical
states plus all prospective receipts. Lewis's season is a policy case study and the primary user
outcome, not the statistical training set.

## What the review rejected

- A monolithic “FPL points” neural network.
- Random row cross-validation.
- Treating OpenFPL's paper result as proof our reproduction will work.
- Re-scoring every old match under 2026/27 BPS without the underlying events.
- A generic mean-minus-variance objective.
- A fixed differential bonus or target ownership range.
- A blanket penalty for cash in the bank.
- A hard-coded “never take hits” policy.
- Exact claims from backtests using the final fixture calendar.
- Letting an LLM turn a journalist's adjective directly into an xP adjustment.

## First vertical-slice audit result — 2 August 2026

The implemented `forecast_v2` slice clears a deliberately narrower bar than the complete system
above:

- 244,425 historical player/gameweek rows and 4,472 live player/horizon rows pass 13 hard data
  checks, including exact lag reconstruction and zero post-deadline proxy observations;
- XGBoost trains on the RTX 5090 and records `cuda:0` in the artifact; CPU fallback aborts;
- rolling tests cover 2023/24, 2024/25 and 2025/26, separately by position: the model beats
  five-match form in 10/12 MAE slices and all 12 top-shortlist slices, with +0.428 actual points
  per shortlisted player/gameweek;
- the GW1-only shortlist wins 8/12 position-season slices and gains +0.461 actual points on
  average;
- legal end-to-end GW1 squad replays tie form in 2023/24, gain 16 points in 2024/25 and gain two
  in 2025/26; and
- the current initial squad retains 92% of its players across 20 model-error perturbations, keeps
  its captain in 85%, and is unchanged under 0.80, 0.88 and 0.95 future-point decay.

One challenger—a separate binary participation model—passed the form baseline but was rejected
because GW1 shortlist lift fell from +0.461 to +0.211. This is the intended champion/challenger
behaviour: a more intuitive-looking premium forecast does not override worse out-of-season
decisions.

The direct forecast remains the marginal-mean incumbent, but it now has a separately implemented
match-component challenger. That challenger simulates correlated scores, goal timing, on-pitch
intervals, scorer/assister allocation, clean sheets, concessions, current-rule components, exact
autosubs and captaincy. Its player-event blend was selected on 2024/25 and frozen for 2025/26;
the accepted weight is 5% raw component signal, not the more dramatic 100% raw result. Full BPS
micro-events, cross-league new-signing priors and prospective in-season calibration remain open.

## Residual risks we cannot engineer away yet

1. **Football randomness:** red cards, penalties, deflections and substitutions can defeat the best
   calibrated action in any single week.
2. **Private information:** managers and clubs know lineup/injury information that public sources
   do not.
3. **Small rule-era samples:** 2026/27 BPS and DC calibration begins with little directly comparable
   data.
4. **New-player translation:** some incoming players have no legally usable structured prior-league
   data.
5. **Unofficial API stability and rights:** access can change, and commercial terms need review
   before public monetization.
6. **Mini-league opponent behavior:** future transfers and captain choices are themselves uncertain,
   particularly for casual managers.

The correct response is calibrated uncertainty, graceful fallback and rapid prospective learning,
not claiming these risks do not exist.

## Foundation go/no-go checklist

Implementation can begin now, but the decision engine cannot be called production-ready until:

- [ ] deadline-history reconstruction and the live collector are running;
- [ ] every feature has a tested availability contract;
- [ ] rules and state transitions pass golden and property tests;
- [ ] minutes and cold-start models pass calibration gates;
- [ ] the direct model beats the frozen ridge on time-forward folds;
- [x] scenarios reproduce marginal forecasts and match-level correlations;
- [x] all generated action bundles are legal and independently replayable;
- [ ] hits, captain/vice, bench and chips survive perturbation tests;
- [ ] the full recommendation is reproducible from its receipt; and
- [ ] at least one complete pre-deadline shadow run succeeds before GW1.

The mini-league risk layer is not required for GW1. It should remain context-only until its own
late-season policy tests pass. The foundation's immediate competitive value is better expected
points, participation calibration, transfer option value and exact execution of every ordinary FPL
decision.
