# FPLAgent Initial-Squad Decision Engine

## A technical whitepaper on the current 2026/27 algorithm

**Version:** 1.0  
**Prepared:** 3 August 2026  
**Decision snapshot:** official FPL data captured 2 August 2026 at 10:02:54 UTC  
**Current decision:** `R-dc7de17def`, provisional until the final pre-GW1 refresh  
**Implementation:** `src/fplagent_data` and `src/fplagent_engine`

> FPLAgent is not one model that ranks footballers. It is a versioned decision system that
> reconstructs what was knowable before historical deadlines, forecasts player participation and
> points, simulates correlated matches under current FPL scoring, searches a large legal squad
> space, and chooses the squad that is least regrettable across declared model and horizon stresses.

<!-- VISUAL:pipeline -->

## Abstract

This paper documents the algorithm that currently produces FPLAgent's provisional 2026/27
Gameweek 1 squad. It describes the implemented path from public data to the final 15-player
decision, including provenance, leakage controls, opponent-adjusted team ratings, CUDA-trained
player models, current-rule component simulation, exact squad and transfer constraints, global
candidate search, independent Monte Carlo holdouts, horizon analysis and the final regret
synthesis.

The engine currently recommends a £100.0m 4-3-3 squad captained by Bruno Fernandes. That answer is
not the squad with the highest value under every model. It is the best compromise among 38 squads
deeply tested by both the five-week scoring/model-risk family and the eight-week
horizon/transfer-risk family. The current selection has five-week robust regret of 0.709 points,
eight-week horizon regret of 0.781 points and synthesized regret of 0.752 points. The dedicated
eight-week model prefers a one-player variation by 0.697 decayed points, but that variation is
materially brittle when the scoring environment is more attacking than forecast.

This is a strong preseason decision engine, not a completed autonomous season agent. It does not
yet optimize paid hits, chip inventory, future prices or sell value. Its future transfer paths use
today's forecasts rather than information that will arrive later. The algorithm must be rerun at
the deadline and replanned every gameweek.

## 1. Scope, objective and non-claims

### 1.1 The decision being solved

The current system answers this question:

> Given the public information available in the current preseason snapshot, which legal 15-player
> squad, Gameweek 1 starting XI, captain, vice-captain and bench order offer the strongest robust
> expected-points route through the opening schedule?

The default policy targets expected FPL points. It does not award points for novelty, low ownership
or spending the entire budget. Those properties can emerge only when they improve the simulated
FPL result or preserve transfer option value.

The present GW1 decision is not mini-league-specific. League position, rival ownership and podium
probability become useful once actual league state exists. For the initial squad, maximizing a
robust overall-points distribution is the appropriate prior.

### 1.2 What the system does not claim

- It does not claim to predict the realized score of any individual match or player.
- It does not claim to enumerate every legal FPL squad. The raw position-valid space is on the
  order of `10^27` before budget and club constraints.
- A Monte Carlo confidence interval measures simulation noise under the implemented model. It does
  not include every unknown injury, transfer, tactical change or model misspecification.
- Public top-manager histories are descriptive evidence. They do not establish that an observed
  formation, bench spend or transfer pattern caused a high rank.
- Planned GW2+ transfers are option-value tests under today's forecast, not instructions that
  should be executed without replanning.
- The current output is provisional. A preseason answer that is not refreshed after material team
  news is no longer the output of this algorithm.

## 2. End-to-end architecture

The implementation separates six questions that fail in different ways:

1. **What data are publicly retrievable, and when were they knowable?**
2. **How strong are the two teams in each fixture after opponent and venue adjustment?**
3. **What are a player's probabilities of playing and scoring FPL points?**
4. **How do correlated football events become legal FPL squad scores?**
5. **Which legal squads deserve expensive simulation?**
6. **Which survivor is most robust to model, scoring, transfer and horizon assumptions?**

The executable flow is:

```text
public sources
    -> immutable/raw cache + provenance manifest
    -> normalized Parquet + DuckDB catalog
    -> deadline-safe player and fixture features
    -> opponent-adjusted team ratings
    -> position xP/minutes models + component challengers
    -> GW1-GW8 player forecast
    -> legal seed optimizers
    -> local + distant MILP + evolutionary squad search
    -> residual screen
    -> exact component simulation and autosubs
    -> five-week robust audit
    -> eight-week horizon audit
    -> cross-family decision synthesis
    -> versioned decision receipt
```

The numeric engine is deterministic for fixed artifacts and seeds. An LLM is not used to set xP,
choose players or resolve close optimizations. An LLM may eventually structure attributable news
or explain a completed numeric receipt, but the decision must be reproducible with that layer off.

## 3. Data acquisition, storage and provenance

### 3.1 Official current-season state

The current 2026/27 state comes from the public endpoints used by the official FPL application:

- `bootstrap-static`: player IDs, teams, prices, positions, availability fields, events, chips and
  rule fields;
- `fixtures`: the scheduled fixture grid, venues and event allocation.

The normalized preseason snapshot contains 559 currently selectable players over eight events,
producing 4,472 player-event rows. Live position IDs are authoritative; historical positions are
never carried into the current optimizer.

### 3.2 Historical player and match corpus

The main match and player history comes from the public Vaastav Fantasy Premier League archive.
The normalized engine table contains 244,425 player-gameweek training rows. Player identity is
joined across seasons through the more stable FPL player `code`, not the season-specific `element`
identifier.

The historical corpus also includes fixtures and team tables used for opponent-adjusted ratings,
plus smaller public manager datasets used for behavioral research:

- 2025/26 population and projected-quality evidence from Solio;
- factual 2025/26 top-100 decision trails from the public FPL Genius application endpoint;
- Vaastav and Paul top-manager archives;
- public veteran workbooks indexed from Mike Croft's posts;
- Titan and Soong supporting cohorts.

Third-party model scores are isolated from factual actions. Post-outcome selection bias means these
manager datasets influence hypotheses, horizon design and adversarial tests; they do not become
supervised labels saying “copy this manager.”

### 3.3 Deadline-proxy reconstruction

Final historical season files contain information that may not have been available before the
deadline: later injury flags, final prices and rescheduled fixtures. The pipeline queries public Git
history to select the latest observable player, team and fixture snapshot before an inferred FPL
deadline.

Every feature has an availability contract. Examples include:

- rolling outcomes must end at the previous event;
- snapshot fields must have `observed_at < deadline_at`;
- same-gameweek points and minutes are labels only;
- historical `xP`/`ep_this` is forbidden because its capture timing is unsafe;
- unavailable pre-era xG and defensive-contribution values remain null rather than being imputed
  as observed zeroes.

### 3.4 Physical data layout

The repository separates concerns:

| Layer | Location | Purpose |
|---|---|---|
| Raw source cache | `data/raw` | Original public payloads and files |
| Fetch manifest | `data/manifests/raw_files.jsonl` | URL, time, status, bytes and SHA-256 |
| Normalized source tables | `data/processed` | Stable typed Parquet contracts |
| Query catalog | `data/fpl_history.duckdb` | Views over normalized Parquet |
| Model features | `data/model/features` | Historical and current feature matrices |
| Model artifacts | `data/model/artifacts` | Trained models, metrics and hashes |
| Forecasts | `data/model/forecasts` | Current and rolling player projections |
| Decision artifacts | `data/model/*` and `data/decisions` | Funnel results and final receipts |

Every HTTP response is recorded with a SHA-256 digest. Model and decision receipts also retain
hashes of the forecast and candidate sources, making accidental input drift detectable.

## 4. Point-in-time feature engineering

### 4.1 Training unit

The supervised unit is a player-gameweek. Double gameweeks are aggregated into one decision row:
points and minutes are summed, while fixture count and home/context fields preserve the multiple
fixtures. The target row is excluded from every rolling feature by SQL windows ending at
`1 PRECEDING`.

### 4.2 Player history

The feature grid includes:

- prior-event points and minutes;
- 3-, 5-, 10- and 38-event points form;
- 3-, 5- and 10-event minutes form;
- five-event appearance and 60-minute start rates;
- five-event goals, assists, xG, xA, BPS, clean sheets and defensive contributions;
- historical event count and days since last event;
- current market price, ownership percentile, availability, set-piece orders and cold-start state.

Ownership is a normalized percentile feature and market prior. It is never directly rewarded in
the decision utility.

### 4.3 Production fixture features

The current champion uses 47 features. The older raw rolling team-goal features and official FPL
fixture difficulty are excluded from the production model. They remain only for controlled
champion/challenger ablation.

The replacement feature family contains opponent-adjusted attack and defence, venue-specific
ratings, expected goals for and against, clean-sheet probability, promoted/returning-club priors,
rating sample size and rest/staleness fields.

### 4.4 Executable data gate

Twenty current integrity checks pass. Important results include:

| Contract | Current result |
|---|---:|
| Historical training rows | 244,425 |
| Duplicate historical player-event keys | 0 |
| Null stable player codes | 0 |
| Incorrect `last_points` lag | 0 |
| `form5` windows containing target event | 0 |
| Snapshot observations after deadlines | 0 |
| Synthetic pre-era xG values | 0 |
| Current player-event rows | 4,472 = 559 × 8 |
| Missing current adjusted ratings | 0 |
| Official difficulty present in challenger allowlist | false |
| Selectable pool | 61 GK, 185 DEF, 247 MID, 66 FWD |

Passing these checks establishes internal consistency and blocks known leakage routes. It cannot
create historical information that was never archived.

## 5. Opponent-adjusted team and fixture model

### 5.1 Dynamic hierarchical ratings

`team_strength.py` implements an online Poisson rating model. Every team has shared attack and
defence ratings plus smaller home/away residuals. Before a fixture, expected goals are:

```math
lambda_home = exp(mu_home + attack_home + venue_attack_home
                  - defence_away - venue_defence_away)

lambda_away = exp(mu_away + attack_away + venue_attack_away
                  - defence_home - venue_defence_home)
```

Expectations are recorded before outcomes update the state. After a kickoff batch, clipped scoring
errors update the scoring team's attack and the opponent's defence. Calculating the whole kickoff
batch first prevents one simultaneous match from leaking into another.

The selected calibration uses a 540-day shared-rating half-life, 240-day venue half-life, 0.03 base
learning rate and 0.01 venue learning rate. Promoted teams receive a partially pooled prior derived
from earlier promoted cohorts; returning clubs blend 20% of their decayed old state with that prior.

### 5.2 Validation and fixture ablation

The rating model has 1,900 season-forward evaluation fixtures across 2021/22–2025/26. The
production opponent-adjusted feature contract passed a preregistered ablation gate: its mean
top-shortlist return improved without unacceptable MAE or ranking deterioration, while official
fixture difficulty remained excluded.

A separate CUDA Poisson goal model consumes the adjusted fixture features to generate the match
score rates used in simulation. It was trained on 5,643 team-fixture rows from 2018/19–2025/26 and
beat a home/away Poisson baseline on untouched 2024/25 and 2025/26 Poisson deviance:

| Test season | Home/away baseline | Goal model |
|---|---:|---:|
| 2024/25 | 1.188 | 1.109 |
| 2025/26 | 1.126 | 1.084 |

Current predicted rates range from 0.897 to 2.723 goals per team-fixture, averaging 1.516 for home
teams and 1.273 for away teams over the opening five gameweeks.

## 6. Primary player forecast

### 6.1 Position-specific hurdle structure

The primary marginal forecast is `forecast_v3_opponent_adjusted`, stored in the `forecast_v2`
artifact directory for compatibility. Four separate position bundles are trained: GK, DEF, MID and
FWD.

Each bundle contains:

1. a four-class minutes classifier for DNP, 1–59, 60–89 and 90+ minutes;
2. a points regressor trained only where the player appeared.

For feature vector `x`:

```math
p_play(x) = 1 - P(DNP | x)

xP(x) = p_play(x) * E[points | played, x]
```

Two models with seeds 17 and 43 are averaged for each target and position. The current final bundle
uses 250 estimators for both points and minutes. Points use squared-error XGBoost trees; minutes use
four-class soft probabilities. Both use histogram training on `cuda:0`. Training aborts rather than
silently falling back to CPU.

### 6.2 Model parameters

| Parameter | Points model | Minutes model |
|---|---:|---:|
| Learning rate | 0.035 | 0.040 |
| Maximum depth | 5 | 4 |
| Minimum child weight | 8 | 8 |
| Row subsample | 0.82 | 0.85 |
| Column subsample | 0.82 | 0.85 |
| L1 / L2 | 0.15 / 6.0 | 0.10 / 6.0 |

The trained environment records XGBoost 3.3.0 and an NVIDIA GeForce RTX 5090 on `cuda:0`. Hardware
reduces iteration cost; it is not evidence that the model is accurate.

### 6.3 Season-forward gate

The model is tested by training only on seasons before each of 2023/24, 2024/25 and 2025/26,
separately for four positions. It must beat an availability-adjusted five-game form baseline on
decision-relevant metrics, not merely global error.

Current gate results across 12 position-season slices are:

- MAE wins: 11 of 12;
- rank wins: 6 of 12;
- top-shortlist wins: 11 of 12;
- GW1 top-shortlist wins: 7 of 12;
- mean top-shortlist lift: +0.512 actual points per selected player-gameweek;
- mean GW1 shortlist lift: +0.418.

The final model receives 100% marginal weight against the five-game-form baseline because that
weight won the time-ordered selection procedure.

### 6.4 Appearance recalibration

Minutes probabilities receive a second champion/challenger test on the union of top xP and top
xP-per-price players—the population the optimizer is likely to select. A position-specific logistic
calibrator must improve both Brier score and log loss in both strict forward tests.

Only forwards passed all four required comparisons. Forward probabilities are recalibrated;
goalkeepers, defenders and midfielders remain untouched. This is deliberate model subtraction:
plausible corrections are rejected when their forward evidence is inconsistent.

### 6.5 Epistemic penalty

For search diversification the forecast also records:

```math
robust_points = xP - 0.15 * epistemic_uncertainty
```

Uncertainty combines disagreement across the two models, a 0.65 cold-start surcharge and a 0.20
penalty when fewer than five historical events exist. `robust_points` is one proxy view; it does
not replace xP as the central expected value.

## 7. Component models and current-rule scoring

### 7.1 Why a second model family exists

A direct points model provides strong marginal expectations but not coherent match paths. FPL
scores are correlated: one goal removes several clean sheets, a missed match activates a bench
player, and a captain DNP may pass the multiplier to the vice-captain. The component family exists
to create those dependencies and to adapt when the scoring rules change.

### 7.2 Player event challengers

CUDA event models predict goals, assists, bonus and saves from the 244,425-row point-in-time feature
grid. A component is promoted only after season-forward testing against a leakage-safe baseline.
Goals, assists and bonus passed in both 2024/25 and 2025/26. Saves failed the required rank gate and
remain on the empirical fallback.

### 7.3 Defensive contributions and 2026/27 BPS

Defensive-contribution points are simulated from position and minutes-class probabilities estimated
from 2025/26, the only complete rule-era season. Two points are awarded at the current thresholds.

The BPS reconstruction performs two different jobs:

1. it reproduces historical bonus allocation and tie handling from recorded BPS exactly—380 of 380
   fixtures and all 2,415 bonus points in the control season;
2. it estimates missing tackled events with a CUDA model trained on 2016/17–2017/18 and tested on
   2018/19. On players with at least 450 minutes, player-season rank correlation is 0.892 and MAE
   falls from 15.20 to 11.36.

Promoted outfield bonus deltas become player priors. Goalkeeper deltas remain neutral where complete
save-location and big-chance-save context is unavailable. The live Monte Carlo bonus allocator is
still BPS-inspired rather than a full Opta event replay: it ranks simulated performance plus the
promoted prior and awards 3/2/1. Exact historical tie allocation is therefore a reconstruction
control, not a claim that future simulated BPS ties are exact.

## 8. Correlated match Monte Carlo

### 8.1 Match generation

For every simulated fixture:

1. home and away goals are drawn from correlated Poisson marginals using a Gaussian copula;
2. every player receives a minutes class and sampled minutes from historical position/class pools;
3. each goal receives a simulated time;
4. the scorer is drawn from players on the pitch at that time, weighted by promoted goal propensity
   or a shrunk xG/goal/set-piece fallback;
5. at most one eligible assist is allocated, excluding the scorer;
6. every defender and goalkeeper on the pitch at the goal time receives a concession;
7. clean sheets, saves, penalties, cards, own goals, defensive contributions and bonus are sampled;
8. the current scoring formula converts components to integer FPL points.

Team goals are capped at eight per side to bound extreme simulation memory. Goal, card, save and
other rare-event distributions are approximations calibrated from recent Premier League data.

### 8.2 Football identity checks

The 25,000-world five-week component run represents 1.25 million match scenarios. Its identity
checks record:

- 3,483,418 simulated team goals;
- 3,483,359 allocated goals and 59 unattributed goals;
- goal reconciliation rate of 1.0;
- 3,173,897 allocated assists;
- zero assist-exceeds-goal violations;
- exact legal autosub and captain-fallback evaluation for every candidate path.

### 8.3 Exact FPL squad scoring

For each simulated player appearance pattern, the scoring layer:

- replaces a zero-minute goalkeeper only with the reserve goalkeeper;
- processes outfield substitutes in recorded bench order;
- preserves at least three defenders, two midfielders and one forward;
- doubles the captain if he plays;
- otherwise doubles the vice-captain if he plays.

Appearance patterns are memoized as 15-bit squad masks, allowing exact autosubs to be reused across
worlds with the same pattern.

### 8.4 Marginal anchoring and evidence blend

Raw component paths contain the desired covariance but their player means are not as trusted as the
primary xP model. An anchored path applies integer stochastic offsets only when a player appears so
that simulated player-event means reproduce xP.

The raw component weight was selected on 2024/25 top-shortlist returns and frozen before evaluating
2025/26. The selected value is 0.10:

```math
evidence_path = anchored_path + 0.10 * (raw_path - anchored_path)
              = 0.90 * anchored_path + 0.10 * raw_path
```

On untouched 2025/26 data, the blend produced 4.131 top-shortlist actual points against 4.126 for
pure xP. The small weight is intentional: the football model supplies covariance and a cautious
independent signal without letting an exciting but less calibrated raw simulation dominate.

## 9. Legal multi-period optimizer

### 9.1 Decision variables

The HiGHS mixed-integer program creates binary variables for every player and gameweek:

- squad membership;
- starting-XI membership;
- captaincy;
- inbound transfer;
- integer free-transfer bank.

### 9.2 Hard constraints

For each event the solver enforces:

- 15 players: 2 GK, 5 DEF, 5 MID and 3 FWD;
- maximum three players per club;
- budget no greater than £100.0m;
- exactly 11 starters and one starting captain;
- legal formation: 1 GK, 3–5 DEF, 2–5 MID and 1–3 FWD;
- inbound transfers no greater than the available free-transfer bank;
- free transfers accumulate to the live maximum of five.

The result is independently replayed through `validate_squad` and `validate_lineup`. Solver output
is never trusted solely because the optimization returned “optimal.”

### 9.3 Search objective

The seed optimizer uses a decayed multi-event objective:

```math
max sum_gw decay^(gw-1) * [XI_xP + captain_xP + 0.08 * bench_xP]
```

The default decay is 0.88. The 8% bench term is a cheap autosub/search proxy, not the final bench
valuation. Later component stages score legal autosubs exactly and counterfactual generators also
set the proxy to zero, constrain bench price bands and force 3-, 4- or 5-defender formations.

A `1e-6` transfer penalty only resolves objective ties in favor of fewer moves. The current solver
allows free transfers only: no paid hit is generated, and future prices and sell values are held
constant.

## 10. Candidate generation and global search

<!-- VISUAL:funnel -->

### 10.1 Seed strategies

The funnel begins with 149 independently generated residual and component candidates. Seeds vary:

- forecast perturbation and model family;
- future-point decay;
- formation and bench spend;
- premium-player inclusion;
- xP, robust-points and component weighting;
- fixed versus transfer-aware construction.

Named historical incumbents are protected through later elimination stages so a new method cannot
win by quietly dropping its strongest predecessor before equal evaluation.

### 10.2 Local neighborhood

Every seed receives exhaustive legal same-position one-player swaps, creating 321,629 unique
squads. The top 128 proxy leaders then receive another layer of swaps, producing 542,246 local
one/two-swap candidates.

### 10.3 Distant MILP restarts

Local search can miss a structurally different squad. The global solver therefore performs 256
mixed-integer restarts. Each restart:

- blends the 40 proxy utility scenarios with a Dirichlet draw;
- standardizes utility within position;
- adds one of six noise scales and one of five price tilts;
- enforces full legality;
- requires at least three player swaps from every seed;
- excludes already generated solutions.

### 10.4 Evolutionary search

The 256 distant squads initialize a 256-member population. Ten generations attempt 2,048 offspring
each. Legal same-position crossover is followed by one to four mutations. Population selection
protects specialists from every proxy scenario and then fills on aggregate and downside proxy
scores.

The completed run generated 19,996 unique evolutionary squads from 21,333 attempted offspring. It
rejected 240 illegal mutations and 469 squads too close to an original seed.

### 10.5 Proxy discovery

The deduplicated local/global universe contains 562,498 squads. Forty deterministic proxy views
span:

- raw component weights from 0 to 1;
- horizon decays 0.76, 0.82, 0.88, 0.94 and 1.00;
- central xP and uncertainty-adjusted player utility.

Sparse matrix scoring retains scenario specialists and protected benchmarks before reducing the
field to 10,000. This proxy is allowed to eliminate obviously dominated squads; it is never allowed
to promote the final decision.

## 11. Progressive simulation funnel

The funnel spends expensive computation only after breadth:

| Stage | Field | Evaluation |
|---|---:|---|
| Combined legal universe | 562,498 | 40 cheap deterministic proxy views |
| Discovery field | 10,000 | 2,000-world residual screen |
| Component shortlist | 512 | 5,000 exact component worlds |
| Deep finalists | 64 | 25,000 untouched base worlds |
| Scoring stress | 64 | 25,000 independent goals ×1.15 worlds |

Discovery, selection and holdout use independent seeds: 20260804, 20260805 and 20260806. Component
selection and deep holdout also offset their random streams. Reusing the same worlds across squads
within a stage is deliberate paired testing: it reduces Monte Carlo noise in squad differences.

Shortlist selection protects formations, bench bands, central mean, downside CVaR, upper tail,
named incumbents and global-search sources. The final 64 are not simply the 64 highest preliminary
means.

## 12. Five-week robust decision

### 12.1 Transfer-policy variants

Every finalist receives three policies:

- **fixed:** hold the original 15;
- **open:** use free transfers when today's forecast says they improve the route;
- **roll-GW2:** explicitly forbid a GW2 transfer, then optimize the remaining free-transfer path.

The policies are solved against the forecast and then scored in the same untouched component worlds.

### 12.2 Declared scenarios

| Scenario | Weight |
|---|---:|
| Evidence blend, open transfers | 30.0% |
| Evidence blend, forced GW2 roll | 20.0% |
| Evidence blend, fixed squad | 10.0% |
| Raw component, open transfers | 10.0% |
| Anchored xP, open transfers | 15.0% |
| Goals +15%, open transfers | 7.5% |
| Goals +15%, forced GW2 roll | 5.0% |
| Goals +15%, fixed squad | 2.5% |

For candidate `c` and scenario `s`:

```math
regret(c,s) = best_value(s) - value(c,s)

mean_regret(c) = sum_s weight(s) * regret(c,s)

robust_regret_5(c) = 0.75 * mean_regret(c)
                   + 0.25 * max_s regret(c,s)
```

Any candidate more than 1.0 point behind the best central evidence/open result is deprioritized
before regret ranking. This stops an extreme stress specialist from replacing a materially stronger
central squad.

The winner `R-dc7de17def` records:

- central evidence/open value: 307.574 points over GW1–5;
- weighted mean regret: 0.448;
- worst scenario regret: 1.493;
- robust regret: 0.709;
- central paired advantage over the runner-up: +0.107 points, 95% CI +0.085 to +0.129;
- the same winner in all eight leave-one-scenario-out tests.

The best remotely generated finalist has robust regret 2.117. The selected squad beats it by 0.204
central points with a paired 95% interval of +0.013 to +0.394.

## 13. Eight-week horizon adequacy audit

Five equal gameweeks can overfit an easy opening schedule. Eight equal gameweeks can overtrust
injury, role and fixture information that will change. The horizon audit therefore evaluates a grid
rather than declaring one natural lookahead.

It carries the 64 robust finalists forward, adds 128 new GW1–8 optimizer squads and screens all 192
in 5,000 worlds. Forty-eight finalists receive 25,000 untouched eight-week component worlds under
fixed, open and forced-GW2-roll policies.

The audit scenarios are:

| Scenario | Weight |
|---|---:|
| GW1–3, open, decay 0.88 | 10% |
| GW1–5, open, decay 0.88 | 15% |
| GW1–8, open, decay 0.70 | 10% |
| GW1–8, open, decay 0.80 | 10% |
| GW1–8, open, decay 0.88 | 15% |
| GW1–8, open, decay 0.94 | 10% |
| GW6–8 only, equal weight | 10% |
| GW1–8, fixed, decay 0.88 | 5% |
| GW1–8, forced GW2 roll, decay 0.88 | 15% |

The central 0.88 decay values GW8 at `0.88^7 = 0.409` times GW1. Horizon regret is 80% weighted
mean plus 20% worst scenario, with a 1.5-point central cap.

The horizon-only leader `R-2f0b2cc758` replaces Hill with Collins and starts 5-3-2. It beats the
five-week incumbent by 0.697 decayed central points, with paired 95% CI +0.596 to +0.798. However,
the five-week stress family shows 4.407 points of open-transfer high-goal regret for that challenger.

The retained 4-3-3 is not materially tied to the opening five fixtures:

- eight-week horizon rank: 12 of 48;
- central GW1–8 regret: 0.697;
- GW6–8-only regret: 0.696;
- forced-GW2-roll regret: 0.285;
- fixed-squad regret: 0.000, best in the deep field.

Public manager evidence informs, but does not fit, the decay grid. In the 2019/20 public elite
top-ten trail the median manager retained 13 original players in GW3, 6.5 in GW6 and 5.5 in GW8;
several early wildcards explain part of the decline. In the richer 2025/26 top-100 action trail, 61
managers rolled in GW2, then only 22 in GW3 and 19 in GW4. The observable pattern supports early
optionality followed by adaptation rather than a rigid eight-week XI.

## 14. Cross-family decision synthesis

<!-- VISUAL:synthesis -->

The five-week and eight-week audits measure different failure modes. Their regret numbers are kept
as separate families rather than concatenating all scenarios into a convenient single list.

For the 38 squads deeply tested in both families:

```math
family_mean(c) = 0.50 * robust_regret_5(c)
               + 0.50 * robust_regret_8(c)

synthesis(c) = 0.80 * family_mean(c)
             + 0.20 * max(robust_regret_5(c), robust_regret_8(c))
```

The 20% maximum-family term penalizes a squad that is excellent only because one modeling family
likes it. No normalization is applied: both inputs are regret measured in FPL points.

| Candidate | Five-week | Eight-week | Worst family | Synthesis |
|---|---:|---:|---:|---:|
| `R-dc7de17def` | 0.709 | 0.781 | 0.781 | **0.752** |
| `R-2f0b2cc758` | 1.874 | 0.129 | 1.874 | 1.176 |

The 4-3-3 remains the synthesis champion until the horizon family receives more than 79.2% of all
family weight. At that boundary the horizon/transfer family would be nearly four times as
influential as the scoring/calibration/high-goal family.

Ten new horizon-native squads reached the deep eight-week final. The best has horizon regret 0.814,
worse than the retained squad's 0.781, so the joint winner is not protected merely by excluding
new horizon constructions.

## 15. Current decision receipt

<!-- VISUAL:team -->

The current selected squad is:

| Role | Players |
|---|---|
| Starting GK | Donnarumma |
| Starting DEF | Tarkowski (vice), Maguire, Senesi, Truffert |
| Starting MID | Bruno Fernandes (captain), Mbeumo, Gibbs-White |
| Starting FWD | Igor Thiago, Watkins, Calvert-Lewin |
| Bench order | Szoboszlai, Hill, Tanaka, Verbruggen |

The squad costs £100.0m with £0.0m in the bank and £22.0m on the nominal GW1 bench. That bench is
not valued as 22 points of dead capital: later lineups may rotate those players, and exact autosubs
are scored in simulation. Nevertheless, the final answer is conditional on the deadline bench and
formation adversarial checks remaining favorable.

The eight-week open path currently banks transfers in GW2 and GW3 before a two-player change in
GW4. This path demonstrates option value under today's fixture model; it is not a pre-commitment.

The canonical receipt is `data/decisions/2026-27-gw1-synthesized.json`. It includes the full squad,
lineup, source audit metrics, ranking, synthesis weights, historical horizon evidence and SHA-256
hashes of its robust and horizon source artifacts.

## 16. Validation layers and acceptance philosophy

<!-- VISUAL:validation -->

FPLAgent uses champion/challenger gates rather than automatically adopting additional complexity.

| Layer | Acceptance evidence | Current state |
|---|---|---|
| Data | 20 leakage, uniqueness and coverage checks | Pass |
| Fixture context | Time-forward ablation versus player-only and legacy features | Pass |
| Primary xP | 12 position-season slices and decision shortlist gates | Pass |
| Appearance recalibration | Brier and log loss in both forward slices | FWD only |
| Goal model | Poisson deviance versus home/away baseline | Pass both test seasons |
| Event models | Poisson/rank/capture gates | Goals, assists, bonus only |
| Scoring reconstruction | Recent component formula exactness | Above 99.99% |
| BPS reconstruction | Historical bonus control and tackled proxy | Outfield promoted |
| Simulation identities | Goals, assists, bonus conservation and autosubs | Pass |
| Search | Protected incumbents plus distant global sources | Pass |
| Robustness | Base, raw, anchor, transfer and high-goal views | Pass |
| Horizon | Short, decayed long, late-only, fixed and banked | Pass |
| Code | Current automated suite | 60 tests passing |

The philosophy is asymmetric: an established simple signal remains active until a challenger wins
time-ordered tests. Complexity is not rewarded for being sophisticated.

## 17. Reproducibility and operational runbook

### 17.1 Full command sequence

```bash
uv sync
uv run fpl-data build
uv run fpl-data validate
uv run fpl-data analyse

uv run fplagent prepare --horizon 8
uv run fplagent gpu-check
uv run fplagent train
uv run fplagent audit-appearances
uv run fplagent reconstruct-bps --simulations 400 --seed 20260803
uv run fplagent forecast
uv run fplagent train-components
uv run fplagent train-component-events --force-targets
uv run fplagent forecast-components
uv run fplagent backtest-components
uv run fplagent component-candidates

uv run fplagent robust-search \
  --discovery-candidates 10000 \
  --screen-simulations 2000 \
  --shortlist 512 \
  --selection-simulations 5000 \
  --finalists 64 \
  --holdout-simulations 25000

uv run fplagent horizon-audit \
  --horizon-candidates 128 \
  --selection-simulations 5000 \
  --finalists 48 \
  --holdout-simulations 25000

uv run fplagent synthesize-gw1 \
  --horizon-family-weight 0.50 \
  --family-worst-weight 0.20
```

### 17.2 Seed discipline

| Purpose | Seed |
|---|---:|
| Global discovery | 20260804 |
| Five-week selection | 20260805 |
| Five-week holdout | 20260806 |
| Horizon candidate generation | 20260807 |
| Horizon selection | 20260808 |
| Horizon holdout | 20260809 |

Changing a seed is a sensitivity exercise, not an acceptable way to search for a preferred team.
The chosen decision should remain close to optimal across independent reruns before it is locked.

### 17.3 Canonical artifacts

| Artifact | Meaning |
|---|---|
| `data/model/artifacts/forecast_v2/metrics.json` | Primary forecast gate |
| `data/model/normalized/team_strength_metrics.json` | Team-rating calibration |
| `data/model/component_backtest_v1/metrics.json` | Frozen component blend |
| `data/model/robust_search_v2_global/results.json` | Five-week robust audit |
| `data/model/horizon_audit_v1/results.json` | Eight-week horizon audit |
| `data/model/gw1_decision_synthesis_v1/results.json` | Final cross-family ranking |
| `data/decisions/2026-27-gw1-synthesized.json` | User-facing machine receipt |

## 18. Known limitations and failure modes

### 18.1 Decisions not yet represented

The initial-squad engine models legal squads, lineups, captaincy, autosubs and free-transfer carry.
It does not yet optimize:

- paid transfers at an exact four-point cost;
- Wildcard, Free Hit, Bench Boost or Triple Captain inventory and expiry;
- non-consecutive Free Hit restrictions;
- price-change probability, sell value or early-transfer injury risk;
- provisional-versus-final gameweek state.

These omissions block a claim that the weekly season agent is complete. They do not make the GW1
squad illegal, but they matter immediately after the season starts.

### 18.2 Future information and adaptive policy

The open transfer optimizer solves the best path under current forecasts. It does not branch on
future injuries, roles, form or price changes. Decay, fixed-squad and forced-bank scenarios reduce
the chance that optimistic future execution manufactures the winner, but they do not turn the path
into a true adaptive policy.

The production weekly system should reforecast and reoptimize at every deadline. A full policy
simulation would model future observations and decisions conditionally; that is not implemented.

### 18.3 Model uncertainty

- New signings and promoted players can have thin or stale Premier League priors.
- Defensive-contribution calibration has one completed rule-era season.
- Bonus simulation does not reproduce every future micro-event or tie path.
- Match scores use Poisson-style marginals and a small estimated correlation; tactical score-state
  effects are simplified.
- Discipline, penalties, saves and own goals use empirical approximations.
- The high-goal +15% environment is an adversarial stress, not a calibrated alternative posterior.
- The same primary forecast helps generate and anchor candidates, creating shared model risk that
  paired simulations cannot remove.

### 18.4 Search uncertainty

The search is broad and deliberately global, but not exhaustive. Its guarantees are local legality,
exact optimization within each MILP objective and equal deep evaluation of survivors. It cannot
prove that no ungenerated legal squad would win the final regret objective.

### 18.5 Data and commercial risk

Public accessibility is not equivalent to a commercial redistribution licence. Unofficial
endpoints may change. A production service needs source-specific rights review, graceful fallback
and an append-only live collector.

## 19. What should happen before the GW1 lock

1. Refresh official players, prices, fixtures, rules and availability.
2. Ingest current injury, transfer and predicted-lineup evidence through attributable structured
   records; never let unverified prose directly alter xP.
3. Rebuild features and rerun every data gate.
4. Refit or refresh forecasts only under the frozen acceptance rules.
5. Regenerate the complete 562k-scale local/global search rather than patching the old winner.
6. Rerun independent five-week base and high-goal holdouts.
7. Rerun the eight-week horizon audit and final synthesis.
8. Inspect whether the leader, captain, formation and bench survive the declared sensitivity tests.
9. Freeze and hash the deadline receipt before manually entering the team.

## 20. Research roadmap

The highest-value improvements are not a larger LLM or a deeper generic network. They are:

1. **Prospective 2026/27 calibration:** preserve every pre-deadline forecast and compare it with
   finalized outcomes.
2. **Adaptive weekly action state:** paid hits, chips, prices, sell value and conditional replanning.
3. **Cross-league priors:** structured translation for promoted and newly transferred players.
4. **Richer minutes/news model:** source reliability, role competition and confirmed availability.
5. **Full future BPS path:** event-level save location, big-chance saves and realistic ties.
6. **Opponent policy simulation:** only when mini-league state makes podium probability actionable.
7. **Search replication:** additional independent global restarts and seed-sensitivity reporting.

An RTX 5090 is most useful for repeated time-forward experiments, large scenario batches and local
inference. Proprietary edge will come from the quality and prospective history of decisions—not
from training a model merely because the hardware is available.

## 21. Conclusion

The current FPLAgent algorithm is best understood as a sequence of vetoes. Historical data veto
leakage. Time-forward tests veto weak model additions. Rule validators veto illegal squads. Global
search vetoes local complacency. Component worlds veto independent-player arithmetic. Stress
scenarios veto fragile formations. Horizon analysis vetoes opening-fixture myopia. The final
synthesis vetoes a squad that wins only one modeling family.

The resulting `R-dc7de17def` selection is defensible because it survives that chain, not because an
optimizer printed it once. Its advantage is small in places, its assumptions are explicit, and its
status remains provisional. That is the correct posture for an uncertain game: maximize the
quality of the decision, preserve the receipt, and replan when reality supplies new information.

## Appendix A: current scenario formulas

```math
five_week_regret = 0.75 * weighted_scenario_regret
                   + 0.25 * worst_scenario_regret

eight_week_regret = 0.80 * weighted_horizon_regret
                    + 0.20 * worst_horizon_regret

family_mean = 0.50 * five_week_regret + 0.50 * eight_week_regret

final_synthesis = 0.80 * family_mean
                  + 0.20 * max(five_week_regret, eight_week_regret)
```

## Appendix B: principal code map

| Responsibility | Module |
|---|---|
| Public data pipeline | `src/fplagent_data` |
| Feature construction | `src/fplagent_engine/features.py` |
| Opponent ratings | `src/fplagent_engine/team_strength.py` |
| Player xP/minutes | `src/fplagent_engine/models.py` |
| Appearance calibration | `src/fplagent_engine/appearance_calibration.py` |
| Component event models | `src/fplagent_engine/component_models.py` |
| Match simulation | `src/fplagent_engine/component_simulator.py` |
| FPL rules and scoring | `src/fplagent_engine/rules.py` |
| HiGHS optimization | `src/fplagent_engine/optimizer.py` |
| Global squad generation | `src/fplagent_engine/global_search.py` |
| Five-week robust funnel | `src/fplagent_engine/robust_search.py` |
| Eight-week audit | `src/fplagent_engine/horizon_audit.py` |
| Final synthesis | `src/fplagent_engine/decision_synthesis.py` |

## Appendix C: source references

- Official FPL application data: `https://fantasy.premierleague.com/api/`
- Official FPL help: `https://fantasy.premierleague.com/help/`
- Vaastav historical repository: `https://github.com/vaastav/Fantasy-Premier-League`
- Local source and licensing caveats: `data/README.md`
- Rule audit: `reports/2026-27-rules-audit.md`
- Global robust audit: `reports/gw1-global-robust-search.md`
- Horizon audit: `reports/gw1-horizon-adequacy-audit.md`
- Final synthesis: `reports/gw1-synthesized-decision.md`
