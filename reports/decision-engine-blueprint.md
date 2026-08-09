# FPLAgent decision-engine foundation

**Status:** proposed architecture after corpus audit and adversarial review  
**Prepared:** 2 August 2026  
**First 2026/27 deadline:** 21 August 2026, 18:30 BST  
**Companion:** [adversarial review](decision-engine-adversarial-review.md)

## The decision

FPLAgent should not be one model that predicts a player's next score. It should be a versioned
decision system with five independently testable layers:

1. a point-in-time data and rules layer;
2. probabilistic forecasts of participation, matches and player events;
3. a current-rules scoring and correlated scenario simulator;
4. a legal, multi-period action generator and optimiser; and
5. a policy layer that converts the scenarios into one answer, with a receipt explaining why.

The production forecast should begin as a **position-specific gradient-boosted direct points model
plus an explicit minutes model**. In parallel, we should build a component model that forecasts
events and applies the current scoring rules. Neither earns ensemble weight by design: each must
win time-ordered tests. The direct model is the fastest route to a strong forecast; the component
model is the route to coherent uncertainty, rule changes and correlated simulations.

The default policy is to maximize expected season points while being robust to **model error**.
It must not penalize football variance merely because it is variance. Only late in a season, when
mini-league simulations become informative, may the policy trade a bounded amount of expected
points for a higher probability of finishing on the podium in every tracked league. Ownership is
then used to model covariance with opponents, never as a generic “differential bonus”.

An LLM does not set expected points or choose transfers. It may extract attributable claims from
news into a strict schema and turn a completed numeric decision receipt into concise prose. The
numeric engine must produce the same decision with the LLM turned off.

## Why this is the right shape

The local evidence already rejects a simplistic model:

- The corpus contains **253,890 player/fixture rows**, **244,737 player/gameweeks** and 3,800
  fixtures across ten seasons. That is excellent tabular-data scale, not foundation-model scale.
- After applying the existing eligibility filter, a player still fails to appear in roughly 15%
  of goalkeeper, midfielder and forward observations and 22% of defender observations. Predicting
  minutes is therefore not a secondary detail; it is part of the target.
- Match-level xG/xA and starts exist only from 2022/23 onward. Defensive-action components exist
  in 2016/17–2018/19 and 2025/26, while the actual defensive-contribution field exists only in
  2025/26. One universal feature matrix would either discard most history or silently impute entire
  eras.
- Of the 564 players currently in the 2026/27 game, 457 match a 2025/26 player code, while 67 have
  no match in any of the ten Premier League seasons. GW1 must have an explicit cold-start policy.
- The current leakage-safe ridge benchmark materially beats five-gameweek form, but adding raw
  rolling underlying statistics did not improve every test season. More columns are not an edge.
- The direct historical target has drifted. Defensive contribution points arrived in 2025/26,
  and the Bonus Points System changed again for 2026/27. Historical `total_points` is not one
  stationary label.

OpenFPL is the strongest public benchmark direction we found. It uses separate XGBoost and Random
Forest ensembles by position, player/team/opponent features over 1, 3, 5, 10 and 38 matches, and a
prospective 2024/25 evaluation. It demonstrates that public tabular data can compete. It does not
settle our architecture: its reported prospective set is only GW32–38, its development folds are
split by team rather than chronology, it predicts points directly, and it uses Understat data that
we have not yet ingested. We should reproduce it as a challenger, not inherit its claims.

## System boundary

```text
official/public sources + user state + timestamped news
                         |
                  immutable snapshot
                         |
             feature availability contract
                         |
       +-----------------+------------------+
       |                 |                  |
 participation      match state       player events
       |                 |                  |
       +-----------------+------------------+
                         |
           current-rules scenario simulator
                         |
             legal action-bundle generator
                         |
       multi-period optimisation + robustness
                         |
     expected-points policy / late podium policy
                         |
         recommendation + alternatives + receipt
```

The interfaces between these boxes are more important than the first model chosen inside each
box. A better model can be promoted without rewriting the optimiser, and a rule change can be
applied without relabelling every stable football event.

## 1. Point-in-time data contract

### Every record needs two times

`effective_at` says when an event happened; `observed_at` says when FPLAgent first knew it. A
feature is legal for deadline `D` only when `observed_at < D`. When a source does not expose its
own update timestamp, our retrieval time is the upper bound and the value is never backdated.

Every model row must also carry:

- `season`, `event`, `fixture_id`, stable `player_code` and season-specific `element_id`;
- source name, raw object checksum and normalizer version;
- the fixture schedule version known at that time;
- scoring-rules version and position at that season's deadline;
- a feature-by-feature `available_at` audit result; and
- an `is_deadline_proxy` flag when historical data is only approximately point-in-time.

Training fails if a feature lacks an availability declaration. There is no “probably safe” path.
Historical `xP`/`ep_this` remains banned because its scraper ran after gameweeks and its timing is
uncertain.

### The historical dataset needs one more preprocessing pass

The final-season files are safe for lagged match outcomes, but not sufficient for exact strategic
replay. Final fixture files know later postponements and season player snapshots know later price,
ownership and availability states.

The Vaastav repository history makes a partial repair possible. Its `players_raw.csv` and
`fixtures.csv` paths have 39 commits for 2023/24, 37 for 2024/25 and 12 for 2025/26. We should
download every version and map each post-GW commit forward to the next deadline. These remain
**deadline proxies**, because a post-match update may precede subsequent press-conference news,
but they are materially safer than a final-season snapshot. Multi-week fixture backtests must use
the contemporaneous fixture version, not today's reconstructed schedule.

Required processed additions:

| Table | Grain | Purpose |
| --- | --- | --- |
| `deadline_player_snapshots` | player/deadline/source commit | Price, ownership, status, news and set-piece state known approximately then |
| `deadline_fixture_snapshots` | fixture/deadline/source commit | Schedule and event allocation known then |
| `player_identity` | stable player/season | `code`, `opta_code`, element IDs, position and team history |
| `scoring_rules` | season/rule version | Executable scoring and BPS-era metadata |
| `feature_availability` | feature/version | Source, earliest safe time, TTL, prohibited uses |
| `deadline_outcomes` | player/fixture/finalization version | Provisional and final labels kept separately |

The 2026/27 collector is still mandatory. The official game now finalizes a gameweek at 09:00 on
the day after its last match so Opta corrections can change BPS and defensive contributions. We
must train against the finalized label and retain the provisional versions for audit.

### Live collection schedule

For each event, store immutable official API responses at:

- once daily during quiet periods;
- T-72h, T-24h, T-6h, T-60m and T-10m before the deadline;
- immediately after the deadline for public picks and transfer state;
- after material fixture, injury, suspension or player-price changes;
- after each match; and
- after the gameweek is marked final.

The recommendation service selects the newest complete snapshot and fails closed when a critical
source is stale. A cached recommendation can be shown, clearly dated, but it cannot be described as
live. Source terms and commercial reuse rights need an explicit register; public accessibility is
not by itself a redistribution licence.

## 2. Prediction target and grain

### Forecast fixtures first, aggregate to gameweeks second

The atomic forecast is player/fixture. A gameweek forecast is the sum of its fixture scenarios.
This handles doubles, blanks, postponements and the rule that one minute in either double-gameweek
fixture prevents an autosub for the entire event.

For each player/fixture, the forecast contract is:

```text
p(DNP), p(1-59), p(60-89), p(90)
expected_minutes and minute quantiles
component event distributions
expected FPL points and p10/p25/p50/p75/p90
p(return >= 3), p(return >= 5), p(return >= 10)
aleatoric uncertainty, epistemic uncertainty and cold-start flag
model versions, snapshot hash and rule version
```

Do not train only on players who appeared. The universe is every selectable player at the
deadline, with DNP as a real outcome. Candidate-pool filtering belongs after a calibrated DNP
forecast, not before target construction.

### Decompose the unstable points label

Create a current-rules target from components:

1. **stable base points:** appearance, goals, assists, clean sheets, goals conceded, saves,
   penalties, cards and own goals;
2. **defensive contribution:** threshold probability from CBIT/CBIRT counts;
3. **bonus:** a separate rule-era model; and
4. **total points:** the sum under the requested rule version.

This lets ten seasons teach stable football rates while recent seasons teach new scoring. We
cannot perfectly re-create 2026/27 bonus from old data because the complete proprietary BPS input
stream is unavailable. Bonus must therefore remain a calibrated probabilistic residual/ranking
model with a `bps_era` feature, heavily checked on 2025/26 and then updated prospectively.

## 3. Forecast models

### Model A — participation and minutes

This model is mandatory and ships before a more elaborate points model.

- Target: four classes—DNP, 1–59, 60–89 and 90 minutes—plus conditional minute quantiles.
- Candidate: calibrated XGBoost multiclass classifier; logistic and empirical role-rate baselines.
- Features: starts/minutes over 1/3/5/10 fixtures, days of rest, fixture congestion, status and
  chance-of-playing, timestamped news flags, team/role, recent substitutions, price, position and
  horizon.
- Calibration: time-forward isotonic or sigmoid calibration chosen only on validation folds.
- Output: probabilities, not a hard “starter” label.

For horizons beyond the imminent fixture, temporary injury/news features decay toward a learned
role prior. A current 25% availability tag should not imply 25% availability in six weeks.

### Model B — team and match state

Start with a dynamic Poisson/Dixon-Coles-style goals model with home advantage, recency-weighted
attack/defence strengths, promoted-team shrinkage and rest/congestion. It produces a joint score
distribution, clean-sheet probabilities and team goal totals for every fixture.

Challengers may add lagged team xG, shots, public Elo or properly licensed bookmaker probabilities.
Market odds are potentially valuable, particularly before GW1, but they are an optional source
until a provider's commercial rights, cost and incremental out-of-time lift are verified. FPL's
fixture difficulty rating is a baseline, not ground truth.

### Model C — player events conditional on minutes

Use hierarchical rate models and gradient-boosted challengers for:

- non-penalty goals and assists;
- clean-sheet eligibility and goals conceded while on pitch;
- saves and penalty saves for goalkeepers;
- cards, own goals and penalty misses with strong shrinkage; and
- CBIT/CBIRT counts for defensive-contribution thresholds.

The hierarchy shrinks sparse players toward position, team, price and role priors. Features include
per-90 outcomes, xG/xA where safely available, share of team events, set-piece order, opponent
strength, venue and predicted minutes. Low-frequency outcomes should not be handed to an
unregularized tree simply because the GPU can fit it.

Defensive-contribution training should use 2025/26 as the primary era and 2016/17–2018/19 only as
an explicitly down-weighted auxiliary source. The seven-season hole makes automatic pooling
unsafe.

Bonus needs a match-level latent BPS/rank model conditioned on simulated events and each player's
lagged BPS profile. Award 3/2/1 inside the simulated fixture, including the official tie rules, so
independently sampled players cannot all receive maximum bonus. Because some 2026/27 BPS inputs are
missing historically, calibrate the resulting residual by rule era and do not claim exact BPS
reconstruction.

### Model D — direct FPL-points challenger

Reproduce the proven public shape before inventing something exotic:

- one model family per position;
- XGBoost and Random Forest candidates;
- player, team and opponent rolling features over 1/3/5/10 and season/prior-season horizons;
- current availability and projected fixture count;
- direct 1-, 2-, 3-, 5- and 8-gameweek targets, with distant horizons discounted only in the
  decision layer; and
- an unweighted proper loss for the conditional mean, plus a separate return/haul classifier or
  ranker. Target-based sample weighting is permitted only as a calibrated challenger because it
  otherwise changes the meaning of “expected points”.

This is benchmark `direct_v1`. It must beat the existing ridge and a clean OpenFPL reproduction on
our folds. OpenFPL's released weights can be used as an external comparator, not silently mixed
into production.

### Model E — cold start

GW1–3 use a separate prior, gradually blended into the in-season models through approximately
GW4–6.

- Returning players: join seasons by stable `code`; use prior-season role, minutes, per-90 events
  and team strength.
- Promoted clubs: shrink team attack/defence toward historical promoted-team distributions, then
  allow licensed market odds and preseason evidence to move the prior.
- New Premier League signings: translate prior-league rates only when the source and league
  strength mapping are defensible; otherwise use position/price/team-role priors with wide
  uncertainty.
- Academy/fringe players: role prior and DNP probability dominate.
- Manual evidence: permitted only as a timestamped structured override—expected role, set pieces,
  injury or suspension—with a source and expiry. No undocumented “eye test” number.

### Champion/challenger and ensembling

The structural model and direct model each publish a full model card. Non-negative stacking is
allowed only from time-forward out-of-fold predictions and only if it improves proper scores and
decision outcomes. Otherwise the single best calibrated model stays champion.

The proposed production progression is:

| Version | Content | Purpose |
| --- | --- | --- |
| `ridge_form_v0` | Existing position-specific ridge | Frozen floor |
| `minutes_v1` | Calibrated participation/minutes | Removes the largest structural miss |
| `direct_v1` | Position-specific XGBoost/RF | Fast strong mean forecast |
| `structural_v1` | Match + event components + current rules | Coherent scenarios and rule adaptation |
| `ensemble_v1` | Time-forward weighted combination | Ships only if empirically superior |

The 5090 should run GPU XGBoost searches, rolling-fold experiments and large scenario batches.
The processed set fits comfortably in memory, so external-memory machinery and deep networks add
complexity without a data-driven reason. Production inference is a batch job and can be served
from cheap CPU/database infrastructure; no online GPU is required.

## 4. Uncertainty and match simulation

Expected points alone cannot choose a vice-captain, value autosubs or estimate podium probability.
For each policy evaluation, generate at least 20,000 seeded season/gameweek scenarios offline and
continue adaptively until the Monte Carlo error of the leading action's edge is below a registered
tolerance:

1. sample fixture scorelines from the match model;
2. sample correlated player availability and minutes, including team-level rotation shocks and
   the constraint that a club fields only 11 starters;
3. allocate goals/assists and other events conditional on score and minutes;
4. apply the versioned FPL scoring rules, defensive-contribution thresholds and bonus model;
5. aggregate doubles/blanks; and
6. apply captaincy, vice-captaincy, bench order and autosubs exactly.

Players in the same match cannot be independent. A clean sheet is shared, attackers compete for a
finite number of team goals, and goalkeeper saves are related to opponent attacks. The simulation
must preserve those relationships. Epistemic uncertainty—uncertain role, promoted side, new
signing—must also be tagged separately from ordinary match randomness.

Calibration tests include discrete CRPS/log score, quantile coverage, reliability of return/haul
probabilities and correlation diagnostics at team and match level. A visually plausible fan chart
is not evidence of calibrated scenarios.

## 5. Rules and state engine

Rules are executable versioned data, not scattered `if` statements. The state transition accepts
a user state and action, then returns the next legal state.

It must encode:

- £100.0m starting budget, 15-player positional composition and maximum three per club;
- legal formations and bench-order/autosub behavior;
- one free transfer per event, up to five stored, and four points per excess transfer;
- exact purchase/selling prices and the 50% profit rule rounded down to £0.1m;
- Wildcard and Free Hit effects on saved transfers and squad restoration;
- two half-season copies of Wildcard, Free Hit, Bench Boost and Triple Captain;
- first-set expiry before GW19, one chip per event, Free Hit restrictions; and
- double/blank gameweek, captain/vice and finalized score behavior.

The official API snapshot is the primary machine-readable source; official help is the semantic
cross-check. The 2026/27 API reports five bankable transfers and eight chip instances. Golden tests
must cover every boundary state, especially a Wildcard or Free Hit with 1–5 saved transfers. We do
not infer these transitions from an old season.

## 6. Action generation and optimisation

### Generate complete action bundles

The unit of comparison is not “player A versus player B”. It is a complete legal policy:

```text
transfers now / roll
chip or no chip
15-player squad and bank
starting XI and formation
bench order
captain and vice-captain
conditional plan for future gameweeks
```

The generator must always include no transfer, one-transfer routes, combinations up to available
free transfers, justified paid-hit routes and chip branches. Candidate pruning may use dominance
and upper bounds, never ownership or hand-written favorite lists.

### Multi-period solver

Use HiGHS through `highspy` for the mixed-integer linear core. It is MIT licensed, has a Python
interface and solves MILPs. A rolling horizon of 6–8 gameweeks is long enough to expose fixture
turns and transfer option value while limiting false precision. Re-solve at every material update.

Chip screening additionally needs a lower-resolution view to the end of the chip's availability
window, because an eight-week tactical horizon cannot value a chip that expires later. Use schedule
scenarios and terminal value outside the detailed horizon; do not present distant speculative
doubles as confirmed fixtures.

Decision variables represent squad, lineup, bench, captain/vice, transfers, bank, free-transfer
state and chip branch per event. Constraints enforce the rules above. Free-transfer carry is safest
as an explicit finite-state transition rather than a fragile `min/max` formula. Chip schedules can
be enumerated outside the MILP and compared, which is easier to test than one enormous model.

The deterministic solver maximizes expected points after hits. A second-stage scenario evaluator
then re-ranks the best policies using exact autosubs, correlated outcomes, model uncertainty and
chip opportunity. This separation keeps the MILP auditable while retaining nonlinear realities.

### Bank and transfer option value

Money in the bank is not penalized. Its cost is the best forgone robust upgrade; its value is
future flexibility, price resilience and avoided hits. In a multi-period model that value emerges
from future feasible states. The receipt should still report:

- current bank;
- best legal use of the cash;
- expected multi-horizon improvement of spending it; and
- value of retaining it in the preferred route.

This directly audits the old app's suspicious unused budgets without forcing wasteful spending.

### Optimizer's-curse protection

An optimiser will eagerly exploit a meaningless 0.1-point model difference. For every proposed
route:

- perturb forecasts using calibrated epistemic distributions;
- report how often the action remains best;
- compare it with roll/no-chip and the best low-transaction alternative;
- require paid transfers to clear both their point cost and uncertainty buffer; and
- label a winner with low stability as a **thin edge**, while still returning one answer.

The buffer is learned from out-of-fold forecast errors, not an arbitrary “avoid hits” rule.

## 7. Mini-league objective

For most of the season the best response to every mini-league is the same: accumulate the most
expected points. A leader-specific or differential-specific strategy early in the season mostly
adds estimation error.

Late-season policy should simulate the user's same team against all tracked classic-league
opponents and estimate:

- expected final score and percentile;
- probability of a podium in each league; and
- probability of a podium in **every** tracked league.

Opponent ownership affects covariance: captaining a popular player can protect a lead, while a
credible alternative can improve an otherwise remote catch-up path. It never changes that
player's football forecast.

Activate opponent-aware optimization only when both conditions hold:

1. the remaining horizon is short enough for podium probabilities to be stable; and
2. the recommended deviation survives simulation and a pre-registered expected-points sacrifice
   cap.

The activation rule and cap must be tuned on synthetic/historical league states, then frozen. They
cannot be changed because Lewis happens to be losing a league. Until this module passes, the app
shows mini-league context but uses the expected-points policy.

## 8. Timing: transfer now or wait

Every request should answer not only what to do, but whether to do it now. Compare two policies:

- **act now:** captures a likely price move or known opportunity, but accepts exposure to later
  training/news injuries;
- **wait:** gains information and reduces avoidable injury risk, but may lose affordability.

This needs a separately calibrated price-change probability, injury/news arrival model and exact
bank state. The official 2026/27 game includes a price-change indicator, which should be captured
and benchmarked before building a scraper-based predictor. Near deadline, waiting value approaches
zero; early in a week it can dominate a small projected transfer edge.

## 9. LLM boundary

Allowed uses:

- extract `{player, claim_type, probability_language, source, published_at, expires_at}` from
  official/team/reputable reports;
- resolve ambiguous player names for review;
- summarize numeric reasons and alternatives in the product voice; and
- answer follow-up questions from the immutable decision receipt.

Forbidden uses:

- writing an untraceable availability probability into the feature store;
- changing expected points, captain or transfer actions directly;
- inventing a source, quote, injury or tactical role;
- browsing arbitrary user-supplied instructions as trusted evidence; and
- making a recommendation when the numeric engine failed.

Every extracted claim needs provenance, confidence, TTL and a deterministic mapping to model
features. Conflicting reports remain conflicting inputs; prose does not “decide” which is true.
A local language model on the 5090 may reduce marginal cost, but it receives the same restricted
schema and tests as a hosted one.

## 10. Evaluation protocol

### Splits

- Never random-split player rows.
- Use rolling-origin seasons and deadline order within seasons.
- Treat 2025/26 as a development/audit set because we have already inspected it.
- Freeze all architecture, metrics and thresholds before evaluating the prospective 2026/27
  receipt stream.
- Use block bootstraps by gameweek/fixture; player rows within a match are not independent.

The reconstructed 2023/24 and 2024/25 commit histories support stronger replay. The sparse 2025/26
history supports only the deadlines actually present. A final-schedule backtest is reported as a
retrospective upper bound, never a point-in-time strategy result.

### Baselines

Every candidate faces:

- season-to-date and five-gameweek form;
- the frozen position-specific ridge;
- ownership and price as ranking-only market priors;
- OpenFPL reproduction where its required data is licensed and reproducible;
- the previous production model; and
- the roll/no-chip decision policy.

### Forecast metrics

| Question | Metrics |
| --- | --- |
| Will the player play? | Multiclass log loss, Brier scores, ECE/reliability, DNP recall |
| How long? | MAE, pinball loss and interval coverage |
| What is the points distribution? | CRPS/log score, MAE/RMSE, 50%/80%/90% coverage |
| Does it rank useful players? | Per-GW Spearman, NDCG, top-15 points, recall/precision of 5+ and 10+ returns |
| Is it stable across the game? | Position, horizon, price, rule era, cold-start and congestion slices |

### Decision metrics

- legal points from an exact replay after transfer hits;
- lineup and captain expected regret against the **pre-deadline distribution**;
- transfer route versus roll over 1/3/5/8 events;
- hit clearance rate and realized net, with wide uncertainty shown;
- chip value versus the best hold counterfactual available then;
- unused-budget opportunity cost and free-transfer value;
- action stability under forecast perturbations; and
- simulated expected score and podium probability calibration.

Realized hindsight “best captain” is a diagnostic, not the grading target for one decision.

## 11. Pre-registered promotion gates

These thresholds must be committed before candidate training. They are deliberately multi-part so
a model cannot win by optimizing one convenient metric.

### Hard gates

- zero known feature-availability violations;
- 100% valid schema and player/team identity checks;
- 100% legal actions across historical replays and at least 10,000 generated boundary states;
- exact rules-engine score reproduction on finalized historical events for reconstructable
  components;
- no LLM-dependent numeric output; and
- a complete model/action receipt for every recommendation.

### Forecast gate

A challenger is eligible only when, against the best existing baseline:

- gameweek-block bootstrap probability of lower aggregate proper loss is at least 90%;
- it improves at least two of the three latest rolling-origin folds and is no worse than 2% on the
  remaining fold;
- no position's proper loss regresses by more than 3% without a documented sample-size exception;
- 80% prediction intervals cover 76–84% overall and remain within 10 percentage points in each
  core position; and
- high-return ranking improves or remains statistically indistinguishable while zero/DNP
  calibration does not materially regress.

### Policy gate

- after hits, the policy beats roll/form policies in at least two replay seasons and has no
  catastrophic season regression outside the pre-registered bootstrap tolerance;
- paid-hit and chip recommendations remain superior under calibrated forecast perturbations, or
  are explicitly marked thin-edge and excluded from autonomous mode;
- the solver's reported objective can be recomputed independently to numerical tolerance; and
- a shadow recommendation is produced successfully at every 2026/27 test deadline before it can
  become champion.

“Statistically indistinguishable” means we keep the simpler/cheaper incumbent. The threshold
values themselves should receive one dry-run feasibility review, then be frozen before seeing the
challenger scores.

## 12. Decision receipt

Every answer is immutable and contains:

```json
{
  "as_of": "timestamp",
  "valid_until": "timestamp or material-event condition",
  "snapshot_hash": "...",
  "rules_version": "2026-27.x",
  "model_bundle": "...",
  "user_state_hash": "...",
  "action": {
    "transfers": [],
    "chip": null,
    "lineup": [],
    "bench_order": [],
    "captain": 0,
    "vice_captain": 0
  },
  "expected_points": {"gw1": 0, "gw3": 0, "gw5": 0, "gw8": 0},
  "uncertainty": {"p10": 0, "p50": 0, "p90": 0},
  "best_alternative": {},
  "edge_over_alternative": 0,
  "action_stability": 0,
  "mini_league_context_used": false,
  "assumptions_and_stale_inputs": []
}
```

This is the real proprietary dataset. Historical public data teaches the first model; prospective
receipts teach whether FPLAgent knew the right thing at the right time and whether the policy made
the right decision from it.

## 13. Build order and exit criteria

### Foundation 0 — collector, identity and leakage guard

Build the 2026/27 collector immediately, reconstruct Git-history deadline proxies, create the
feature-availability registry and run leakage tests. **Exit:** any training row can explain exactly
what was knowable at its deadline.

### Foundation 1 — executable rules and replay

Implement score calculation, user-state transitions, autosubs, transfer economics and chips with
golden/property tests. **Exit:** finalized scores and generated boundary states reproduce legally.

### Foundation 2 — cold start, minutes and direct forecast

Ship returning-player joins, hierarchical priors, `minutes_v1` and `direct_v1`; reproduce the
ridge/OpenFPL baselines. **Exit:** promotion gate passed on rolling folds, with GW1 uncertainty
explicitly calibrated.

### Foundation 3 — scenarios and deterministic optimizer

Generate correlated gameweek outcomes, build the HiGHS multi-period solver and exact second-stage
policy evaluator. **Exit:** every possible game action can be recommended, including roll, lineup,
bench, captain/vice and each legal chip.

### Foundation 4 — structural model and robust policy

Add team, event, DC and bonus models; compare structural/direct/ensemble forecasts; add optimizer
perturbation tests. **Exit:** calibrated distributions and stable decisions beat Foundation 3.

### Foundation 5 — mini-league policy

Simulate tracked opponents and pre-register the late-season switch. **Exit:** synthetic and replay
league tests improve podium probability without violating the expected-points sacrifice cap.

Only then should automatic execution be considered. Recommendations are sufficient for 2026/27
and preserve a human verification step while the engine establishes prospective credibility.

## What we are explicitly not doing

- no end-to-end LLM agent making football decisions;
- no deep-learning project justified by owning a fast GPU;
- no random train/test splits;
- no historic `xP` as a feature;
- no reward for low ownership by default;
- no blanket spend-all-money, never-hit or always-transfer heuristic;
- no chip backtest that knows the final rescheduled fixture calendar;
- no optimizing Lewis's model after seeing each unlucky or lucky result; and
- no claim that any process can remove the irreducible variance between a strong expected finish
  and an actual mini-league podium.

## Sources

- [OpenFPL paper](https://arxiv.org/html/2508.09992) and
  [released code](https://github.com/daniegr/OpenFPL) — public position-specific ensemble and
  prospective benchmark.
- [Vaastav data dictionary](https://github.com/vaastav/Fantasy-Premier-League/blob/master/DATA_DICTIONARY.md)
  — field definitions and the historical `xP` timing warning.
- [Official 2026/27 changes](https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627),
  [defensive contribution rules](https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy),
  [BPS changes](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system), and
  [chip rules](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627).
- [HiGHS documentation](https://ergo-code.github.io/HiGHS/dev/) — MIT-licensed LP/MILP solver and
  Python interface.
- [XGBoost GPU documentation](https://xgboost.readthedocs.io/en/stable/gpu/) — local CUDA training.
- [Scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html)
  — proper scores and reliability diagnostics.
