# FPLAgent 2026/27 Decision Engine

## A technical whitepaper on building a deadline-grade FPL decision system

**Version:** 2.0  
**Prepared:** 16 August 2026  
**Decision snapshot:** official FPL state captured 16 August 2026 at 06:10:27 UTC  
**Published decision:** `R-92c8534bfc` · 3-4-3 · Bruno Fernandes captain · £20.5m nominal GW1 bench  
**Implementation:** `src/fplagent_data`, `src/fplagent_engine`, `src/fplagent_api` and `web`  
**Evidence status:** deadline-grade research system; not yet state-of-the-art proven

> FPLAgent is not a list of players sorted by a single expected-points number. It is a
> point-in-time decision system: it reconstructs what was knowable, predicts participation and
> returns without using FPL's own expected-points field, simulates correlated football and exact
> game rules, searches hundreds of thousands of legal squads, and rejects answers that are too
> dependent on one model, horizon, scoring assumption or piece of uncertain team news.

<!-- VISUAL:pipeline -->

## Abstract

This paper documents the system that produced FPLAgent's current 2026/27 Gameweek 1 recommendation.
The objective is not to make the most confident-looking forecast. It is to make the strongest
decision that the available evidence supports, preserve its lineage, and expose the conditions
under which that decision should change.

The published squad is `R-92c8534bfc`, a £100.0m 3-4-3 captained by Bruno Fernandes. It emerged from
a fresh 551,183-squad local and global search, was rescored in independent 25,000-world five-week
and eight-week holdouts, survived a high-scoring stress, exact autosub and scoring-rule ablations,
and remained the lowest-regret compromise across the five-week model-risk family and the
eight-week transfer/horizon family. It is not the winner of every view. The dedicated horizon model
prefers `R-1ca68907f5` by 1.045 decayed points, while a GW1 structure-only audit slightly prefers
`R-1ced0705f3`. Those disagreements are retained as evidence rather than hidden. The synthesis
chooses the squad with the best balance, not the squad favoured by the last test that happened to
run.

The system's strongest demonstrated edges are: leakage-safe player forecasting that beat the
declared form baseline in 11 of 12 time-forward shortlist slices; a legal GW1 picker that recorded
two wins, one tie and no losses across three historical seasons; opponent-adjusted match rates that
beat a simple Poisson benchmark on both frozen seasons; a bounded Betfair defender feature that
improved time-forward defender selection in all three tested seasons; exact FPL rules and
correlated simulation; wide local and distant squad search; and explicit robustness, horizon,
bench and availability vetoes.

The paper also draws a hard line around evidence that has not earned production authority.
Understat is collected and replayed but currently receives zero weight. RotoWire and FFScout
predicted lineups are captured but remain prospective shadow evidence. Price timing, full
distribution calibration and chip timing are implemented as measurement frameworks, not promoted
decision signals. No 2026/27 event has yet finished, so no honest claim can be made that the engine
is objectively best in the world. The defensible claim is narrower and useful: this is the
best-supported current GW1 decision produced by the declared, checksum-bound FPLAgent process.

## 1. The decision, in plain English

### 1.1 What the engine is solving

Before Gameweek 1 the manager must choose 15 players, a legal starting XI, a captain, a
vice-captain and an ordered bench under a £100.0m budget and the live club/position rules. That is
already a joint decision. A cheap substitute can be false economy if a starter misses out; a player
with the best opening fixture can be a poor purchase if he immediately creates a transfer problem;
and the highest mean XI can be fragile if its result depends on one optimistic minutes assumption.

FPLAgent therefore asks:

> Given only information available before the current deadline, which legal 15-player squad and
> GW1 configuration offer the best robust points route through the opening schedule, while
> preserving the ability to adapt as new information arrives?

The default utility is FPL points. Ownership, novelty, team value and visual symmetry are not
rewards in themselves. Ownership can be evidence about market expectations and later becomes
relevant to mini-league risk, but the preseason engine does not buy a player because he is popular
or reject him because he is template.

### 1.2 What “best” means here

“Best” does not mean highest displayed GW1 xP. The selected squad's direct GW1 lineup forecast is
57.01 points in the final synthesis artifact, while the exact one-week structure stress scores it
at 58.09 under that audit's component world and gives another squad 58.23. Those values answer
different questions and use different scoring paths. Treating the extra 0.14 as decisive would
discard transfer value, later fixtures and model-risk evidence.

The production selector minimizes regret. For each declared scenario it measures how far a squad
falls behind that scenario's leader. It then penalizes both average regret and worst-case regret.
This deliberately accepts that the true model is unknown. A candidate that is second or third
everywhere can be a better FPL decision than a candidate that is first in one favourite model and
poor everywhere else.

### 1.3 Claim boundary

The system can defend the following statement:

> `R-92c8534bfc` is the best-supported GW1 squad produced by FPLAgent under the current immutable
> evidence, legal rules and declared risk policy.

It cannot yet defend these stronger statements:

- that the realized GW1 score will be high;
- that no ungenerated legal squad is better;
- that FPLAgent is already proven state of the art against every strong public or private model;
- that its p10 and p90 simulation tails are empirically calibrated for 2026/27;
- that a role, injury or transfer reported after the snapshot is already reflected; or
- that a strong process will be spared ordinary football variance.

This distinction matters. A decision system is credible when it states where its evidence ends.

## 2. Current recommendation and receipt

<!-- VISUAL:team -->

The current starting XI is:

| Position | Player | Club | Price | Role |
|---|---|---|---:|---|
| GK | Donnarumma | Man City | £5.5m | Start |
| DEF | Tarkowski | Everton | £6.0m | Start · vice-captain |
| DEF | Maguire | Man Utd | £5.0m | Start |
| DEF | Truffert | Bournemouth | £5.5m | Start |
| MID | Bruno Fernandes | Man Utd | £12.0m | Start · captain |
| MID | Mbeumo | Man Utd | £8.0m | Start |
| MID | Semenyo | Man City | £8.5m | Start |
| MID | Szoboszlai | Liverpool | £7.0m | Start |
| FWD | Igor Thiago | Brentford | £8.0m | Start |
| FWD | Watkins | Aston Villa | £8.0m | Start · verify role |
| FWD | Calvert-Lewin | Leeds | £6.0m | Start |
| Bench 1 | Xhaka | Sunderland | £5.5m | First outfield substitute |
| Bench 2 | N.Williams | Nott'm Forest | £5.0m | Second outfield substitute |
| Bench 3 | Hill | Bournemouth | £5.5m | Third outfield substitute |
| Bench GK | Verbruggen | Brighton | £4.5m | Goalkeeper substitute |

The squad spends £100.0m and leaves £0.0m in the bank. Its nominal GW1 bench costs £20.5m, while
the four cheapest players owned cost £20.0m. That distinction is important: the bench price is
partly a one-week rotation choice, not a permanent instruction to keep expensive assets unused.

### 2.1 Why Bruno Fernandes is captain

Captaincy is solved inside the legal XI, not in a disconnected chat heuristic. The simulator
doubles the captain's realized score and moves the multiplier to the vice-captain only when the
captain plays zero minutes. Bruno remains captain across the published five-week, horizon and GW1
configuration receipts. Tarkowski is vice in the selected baseline XI.

This is a model decision rather than a certainty claim. The app must quote the same versioned
captain receipt everywhere; a language model is allowed to explain the answer but not invent a
different captain from stale context.

### 2.2 What is genuinely uncertain

The final availability watch found zero official-attention players, complete club-feed coverage,
and one role-verification item among the 15: Watkins. Preseason lineup absence is not treated as an
injury label. Instead, the engine runs conditional appearance stresses and requires attributable
deadline evidence before changing the production probability.

The role audit found that alternative squads can win under deliberately adverse Watkins-like
appearance assumptions. That is a verification trigger, not a silent automatic transfer. The
correct operational action is to check authoritative team news, translate confirmed evidence into
the appearance model, and rerun the whole pipeline. Manually swapping one player would break the
joint optimization of budget, XI, bench and later transfers.

### 2.3 Lineage

The publication is bound to input fingerprint
`0fb5197b72166f19b6d3a76842f7ce1a0a3242dfdcb283d9dfe406a9b37b1e8c`. The pipeline observed the
published input generation at 06:10:27 UTC and released it only after all 12 stages completed. The
canonical machine artifacts are the synthesis result, robust audit, horizon audit, structure
stress, role scenario, role threshold and pipeline manifest listed in Appendix C.

## 3. Architecture: many vetoes, one decision

The design separates questions that fail differently:

1. What was knowable before each deadline?
2. How strong are the teams and fixtures after opponent and venue adjustment?
3. What is each player's probability of appearing, minutes class and point return?
4. How should bookmaker, component and independent-source evidence be weighted?
5. How do correlated match events become exact FPL scores?
6. Which legal squads merit expensive simulation?
7. Which result survives alternative scoring, horizon and role assumptions?
8. Is the whole artifact set coherent enough to publish atomically?

The executable flow is:

```text
official + historical + independently timestamped sources
    -> immutable raw cache and SHA-256 manifests
    -> typed Parquet tables and DuckDB catalog
    -> deadline-safe player, team and fixture features
    -> position-specific appearance and points models
    -> opponent-adjusted team-goal model
    -> bounded promoted evidence + zero-authority shadow evidence
    -> GW1-GW8 player forecast
    -> legal seed optimization
    -> local swaps + distant MILP + evolutionary search
    -> residual screen + exact correlated component simulation
    -> five-week robust audit
    -> eight-week transfer/horizon audit
    -> cross-family synthesis
    -> structure, role and availability vetoes
    -> atomic published receipt
```

An LLM is not in this chain. The fine-tuned Qwen adapter powers conversation and explanation, but
it does not set xP, choose a squad or resolve contradictions. Numeric tools produce a receipt; the
chat layer is grounded on that receipt. This separation prevents fluent prose from becoming an
unreviewable decision rule.

## 4. Data, temporal correctness and source authority

### 4.1 Official current state

The official FPL application endpoints remain authoritative for the live game definition:

- `bootstrap-static` for player identifiers, clubs, positions, prices, statuses, events, chips and
  rule fields;
- `fixtures` for the schedule, venue, kickoff and event allocation;
- event-live and authenticated manager data for finalized outcomes and the manager's actual squad,
  bank, transfer state, purchase/selling prices and chips when those become available.

The current immutable snapshot contains 587 players, 20 teams, 380 fixtures and 38 events. The
forecast pool contains 568 modeled players over eight events, or 4,544 player-event rows. Official
FPL `ep_this`, `ep_next` and equivalent expected-points values are prohibited from the production
feature allowlist. FPLAgent is therefore not repackaging the game's own forecast.

### 4.2 Historical corpus

The core historical player table contains 244,425 player-gameweek training rows. Vaastav's public
FPL archive supplies player and match history, while stable FPL player `code` is preferred to the
season-specific `element` ID for identity joins. Historical fixtures and teams support the
opponent model. Smaller public manager datasets support behavioral audits such as initial-squad
retention, transfer banking and bench context; they are not labels that tell the model to copy a
winner.

The catalog exposes 14,351,814 rows through 158 views. Size is not evidence of quality. The edge
comes from temporal contracts, stable mapping, explicit nulls and validation.

### 4.3 Point-in-time reconstruction

Final historical files can contain facts learned after the deadline: later injury statuses,
rescheduled fixtures and final prices. The feature pipeline selects the latest archived state
observable before an inferred deadline. Rolling windows end at the previous event. Same-gameweek
minutes and points are labels only. Missing pre-era xG is null, not a fabricated zero.

The current data gate has 22 declared checks and zero failures. It tests duplicate keys, player
identity, lag correctness, deadline order, forbidden feature presence, fixture coverage, adjusted
ratings, live-rule consistency and current forecast completeness. A passing gate does not prove
the data are perfect; it blocks known leakage and schema failures before they can influence a
decision.

### 4.4 Authority ladder

Every source has an explicit role:

| Source | Current purpose | Production authority | Why |
|---|---|---|---|
| Official FPL | Rules, prices, positions, fixtures, statuses, outcomes, manager state | Full for those facts | Defines the game |
| Vaastav historical FPL | Deadline-safe training and replay | Full after validation | Broad public event history |
| Internal team model | Team attack/defence and goal rates | Full | Passed frozen goal-model tests |
| Betfair delayed exchange | De-vigged 1X2 and O/U team context | 20% defender-only in preseason | Passed bounded time-forward and legal-decision gates |
| Understat | Independent xG/xA/process challenger | Zero | Mixed time-forward results; legal selector chose 0% |
| RotoWire + FFScout | Predicted-XI consensus and role watch | Zero | No completed prospective events yet |
| SofaScore | Research-only independent event challenger | Zero | Slight MAE gain but lost 15 legal-policy points; live 403 instability |
| FBref | No live dependency | None | Automated access unavailable and advanced data changed in 2026 |

More sources are not automatically better. A source adds edge only when its mapped, timestamp-safe
signal improves legal FPL decisions. Otherwise it adds correlated noise, fragility or false
confidence.

## 5. Feature engineering and regression to the mean

### 5.1 Player-deadline feature set

The production player model uses 47 features. They include lagged points and minutes, 3/5/10/38
event form, start and appearance rates, goals, assists, xG, xA, BPS, clean sheets, defensive
contributions, price, ownership percentile, availability, set-piece order, cold-start state,
opponent-adjusted team attack/defence, venue, expected goals for/against, clean-sheet probability,
promoted-club priors, sample size and rest/staleness.

Official fixture difficulty and the old raw rolling team-goal features are excluded from the
champion. They remain available only as controlled challengers. Feature availability is a contract:
if a signal could not have been observed before the deadline, it cannot enter the row.

### 5.2 Why the engine does not chase last week's points

Recent points combine underlying opportunity with finishing, saves, bonus ties and other noise. A
lagged historical audit compared three-event form with ten-event form after controls. Only 9.1% of
the short-versus-medium-term deviation persisted into the next event, which is strong evidence of
mean reversion.

The process split makes the idea concrete. Hot midfielders/forwards with strong underlying xGI/90
continued at 4.13 points next event, while hot players with weak process fell to 3.05. Cold players
with strong process recovered to 3.69, compared with 2.87 for weak-process cold players. The lesson
is not “ignore form.” It is “separate repeatable role and chance generation from noisy recent
conversion.”

A 10% process-reversion correction improved the untouched 2025/26 continuous replay by 23 net
points, while naive form chasing made 91 transfers, paid 212 hit points and finished 301 net points
behind the selected reversion policy. The correction still remains shadow-only because its
four-event uncertainty interval crossed zero. The production advantage today is therefore
discipline: the main forecast already pools longer history and underlying process, while an
unproven extra correction is not promoted simply because its total looked attractive.

### 5.3 Cold starts and epistemic uncertainty

New signings, promoted players and players with thin Premier League histories have wider model
risk. Search diversification records:

```math
robust_points = xP - 0.15 * epistemic_uncertainty
```

Uncertainty combines disagreement between seeded models, a cold-start surcharge and a thin-history
penalty. This is one search view, not a replacement for the central mean. It helps generate squads
that do not all inherit the same optimistic newcomer assumptions.

## 6. Opponent-adjusted team and fixture model

### 6.1 Online hierarchical ratings

Each club carries shared attack and defence ratings plus smaller home/away residuals. Before a
fixture the expected scoring rates are:

```math
lambda_home = exp(mu_home + attack_home + venue_attack_home
                  - defence_away - venue_defence_away)

lambda_away = exp(mu_away + attack_away + venue_attack_away
                  - defence_home - venue_defence_home)
```

The expected rates are recorded before the result updates the state. All matches in the same
kickoff batch are predicted before any of them update ratings, preventing a simultaneous fixture
from leaking into another. Ratings decay, venue effects are partially pooled, and promoted teams
start from a cohort prior rather than an invented Premier League record.

### 6.2 Demonstrated edge

The selected online team model uses a 540-day shared-rating half-life, 240-day venue half-life,
0.03 base learning rate and 0.01 venue learning rate. It was evaluated on 1,140 frozen fixtures:
goal MAE 0.933, Poisson deviance 1.089 and clean-sheet Brier score 0.170.

A separate CUDA Poisson goal model was trained on 5,643 team-fixture rows and beat the simple
home/away Poisson baseline on both untouched seasons:

| Test season | Simple Poisson deviance | FPLAgent goal-model deviance | Result |
|---|---:|---:|---|
| 2024/25 | 1.188 | 1.109 | FPLAgent lower |
| 2025/26 | 1.126 | 1.084 | FPLAgent lower |

This is a direct competitive advantage for defenders, goalkeepers and attackers because it
improves the shared estimates of team goals and clean-sheet probability rather than relying on the
official fixture-difficulty badge.

## 7. Player appearance and points forecast

### 7.1 Position-specific hurdle model

The champion artifact is named `forecast_v3_opponent_adjusted`. Goalkeepers, defenders,
midfielders and forwards have separate bundles. Each bundle contains:

1. a four-class minutes classifier for DNP, 1–59, 60–89 and 90+ minutes; and
2. a points regressor trained only on appearances.

For player features `x`:

```math
p_play(x) = 1 - P(DNP | x)

xP(x) = p_play(x) * E[points | played, x]
```

Two XGBoost models with seeds 17 and 43 are averaged for each target and position. The training
receipt records 244,425 rows, XGBoost 3.3.0 and CUDA execution on an RTX 5090. The GPU allows more
time-forward experiments; it is not itself an accuracy claim.

### 7.2 Time-forward forecast evidence

The model is trained only on seasons preceding each test season for 2023/24, 2024/25 and 2025/26,
giving 12 position-season slices. Against an availability-adjusted five-game form baseline it
records:

- 11/12 MAE wins;
- 6/12 within-event rank wins;
- 11/12 top-shortlist wins;
- 7/12 GW1 top-shortlist wins;
- +0.512 actual points per selected player-gameweek on the general shortlist; and
- +0.418 actual points per selected player-gameweek on the GW1 shortlist.

The legal GW1 replay is more important than row-level accuracy. On identical historical budgets,
club rules, XI, captain and bench selection, the FPLAgent picker beat the form baseline twice, tied
once and lost zero times across the three tested seasons, for +18 realized points in total. Three
seasons are not enough for a universal claim, but this is the right shape of evidence: forecasts
must improve legal actions, not merely spreadsheet metrics.

### 7.3 Appearance recalibration

A logistic recalibrator is tested only on the top xP and xP-per-price population that the optimizer
is likely to select. It must improve both Brier score and log loss in both forward tests. Only
forwards passed every comparison, so only forward probabilities are recalibrated. Goalkeeper,
defender and midfielder calibrators were rejected.

That rejection is a feature of the process. An intuitively plausible calibration cannot alter the
squad unless it generalizes through the predeclared gate.

## 8. Independent football evidence

### 8.1 Understat

Understat supplies an independent view of prior-season shot quality and chance creation. It is not
treated as an xP oracle: FPLAgent retains ownership of minutes, fixtures and scoring. Only data from
the prior completed season are joined to a target season.

The time-forward results were mixed. Some midfielder/forward slices improved MAE or top-k return;
others deteriorated. The exact legal decision replay selected a 0% blend in all three seasons.
Understat is therefore valuable research coverage but currently contributes no production weight.
This avoids the common mistake of assuming that a respected football metric must add incremental
FPL value after the incumbent already contains related xG/xA signals.

### 8.2 Predicted lineups

RotoWire is the primary predicted-XI feed and FFScout is the independent cross-check. Captures are
immutable and deadline-bound. The consensus scorer will compare predicted starters with actual
starters, by club and event, and then replay the signal through the legal squad/XI/captain policy.

At publication, zero events have completed. The signal has zero production authority. It must
reach at least six completed events, achieve two-source coverage on at least ten teams per event,
show positive mean hit-rate lift, avoid a negative event floor and clear an uncertainty bound
before it can even enter a challenger replay. This is particularly important for current role
questions: source disagreement should widen uncertainty, not masquerade as a precise minutes cut.

### 8.3 Why SofaScore and FBref are not dependencies

The SofaScore challenger produced a small player-row MAE improvement but lost 15 points in the
matched legal FPL replay. Its public endpoint also returned live HTTP 403 responses. It receives
zero weight and normal deadline refreshes do not depend on recollecting it. FBref automated access
also returned HTTP 403, and third-party wrappers inspected locally ultimately call the same web
pages or invoke browser CAPTCHA handling. The system keeps Understat and the predicted-lineup pair,
with `soccerdata` reserved for future research, rather than building a fragile bot-evasion
dependency.

## 9. Betting markets as a bounded team prior

### 9.1 What is collected

The current market generation uses delayed public Betfair Exchange Match Odds and over/under 2.5
markets. Competition and market identifiers are discovered rather than hardcoded. Prices are
de-vigged, timestamped and mapped to official fixtures. The current GW1 snapshot covers 10 of 10
fixtures; GW2–GW8 have no market coverage yet and therefore fall back to the internal team model.

Markets inform team scoring and clean-sheet context. They do not directly declare that a specific
player will start, take penalties or receive bonus.

### 9.2 Why the active weight is only 20% and defender-only

An unconstrained one-season search selected a 70% market weight and then lost 16 points on the
independent season. That failure is precisely why weight selection needs sequential stability.
The bounded 20% defender blend improved top-k realized points and MAE in all three forward seasons:

| Season | Defender top-k lift | Defender MAE improvement |
|---|---:|---:|
| 2023/24 | +0.084 points/player-GW | +0.0082 |
| 2024/25 | +0.128 | +0.0098 |
| 2025/26 | +0.160 | +0.0048 |

At 20%, frozen initial-squad decisions gained 27 realized points. The continuous development paths
gained 64 and 76 points, and the frozen 2025/26 follow-up gained 90 points, or 2.368 per gameweek.
The four-event moving-block interval was +0.816 to +4.132 per gameweek. However, the pooled
out-of-selection lower bound crossed below zero. Production authority is therefore deliberately
split:

- preseason defender squad/XI decisions: 20% market blend;
- weekly transfer decisions: 0% until stronger continuous or prospective evidence passes.

This is one of the clearest competitive edges in the system because it combines a near-efficient
football market with strict protection against overfitting that market.

## 10. Current-rule components and correlated simulation

### 10.1 Why marginal xP is insufficient

Independent xP addition misses football dependencies. One goal can create attacker points while
removing clean sheets from several opponents. A starter DNP activates an ordered substitute only
if the resulting formation remains legal. Captaincy depends on realized appearance, not just mean
points. A coherent decision therefore needs shared match worlds.

### 10.2 Component models

Separate event models predict goals, assists, bonus and saves from point-in-time features. Goals,
assists and bonus passed their time-forward gates. Saves failed the rank requirement and remain on
an empirical fallback. The direct points model anchors residual player value so explicit match
components do not discard signal that the component family cannot yet explain.

The 2026/27 scoring layer includes appearance, goals, assists, clean sheets, goals conceded,
defensive contributions, saves, bonus, discipline and penalties. Historical BPS reconstruction
exactly recovered all 2,415 bonus points across 380 control fixtures. The defensive-contribution
proxy improved player-season MAE from 15.20 to 11.36 and Spearman rank from 0.786 to 0.892 on its
frozen historical test; the promoted current-rule layer applies to outfield positions.

### 10.3 Monte Carlo world construction

For each fixture, the simulator samples correlated team scores from calibrated goal rates, assigns
goals and assists to eligible players, samples minutes/appearance jointly, reconstructs FPL point
components and bonus, and aggregates all fixtures in an event. The same random world is reused
across candidate squads within a stage. That paired design removes much of the simulation noise
from squad differences.

Identity checks enforce goal allocation, assist-to-goal limits, six bonus points per match,
appearance marginals, fixture counts, and empty/double-fixture handling. The current eight-week
holdout simulated two million match scenarios with 5,544,813 team goals; only 31 were unattributed,
for a 1.0 reconciliation rate at the reported precision.

### 10.4 Exact FPL configuration scoring

Every deep candidate is scored as a full 15:

- a legal XI with one goalkeeper, at least three defenders, at least two midfielders and at least
  one forward;
- goalkeeper-only goalkeeper substitution;
- ordered outfield autosubs subject to the post-substitution formation;
- captain-to-vice fallback only on zero captain minutes; and
- the current per-component scoring table.

The initial optimizer's small bench coefficient is only a candidate-generation proxy. It has no
vote in the final structure gate, which exhaustively challenges all synthesis finalists and five
bench-proxy settings with actual DNP worlds and legal autosubs.

## 11. Legal optimization and search breadth

### 11.1 Hard constraints

Every generated squad must satisfy the live budget, exact position counts, maximum players per
club, 15-player roster, 11-player formation, captain/vice eligibility and ordered bench rules.
Future policies also carry free transfers and prohibit the five-week/horizon planner from silently
spending hit points.

The initial linear objective is a search instrument:

```math
utility = sum(selected player horizon value)
        + captain uplift
        + small bench/autosub proxy
```

The final selector never treats this proxy as truth. It uses exact shared-world scoring and regret.
The separate weekly action engine adds the historically calibrated terminal value of a banked free
transfer when a planning horizon ends; that value is not smuggled into this initial squad proxy.

### 11.2 Global and local candidate generation

The 16 August run began with 141 seed squads covering residual/component models, horizon decays,
formations, bench bands, premium structures and transfer-aware views. It generated:

- 298,359 legal exhaustive same-position one-swap squads;
- 530,947 local one/two-swap squads;
- 256 distant mixed-integer squads at least three swaps from every seed; and
- 19,980 evolutionary squads across legal crossover and mutation.

After deduplication the universe contained 551,183 legal candidates and 261 distinct players.
Within the 10,000 retained discovery field, all legal formations and four bench bands were
represented. Search breadth is an edge because a sophisticated evaluator cannot rescue a squad it
never generates.

### 11.3 Progressive compute funnel

<!-- VISUAL:funnel -->

| Stage | Field | Evaluation |
|---|---:|---|
| Legal search universe | 551,183 | 40 deterministic proxy views |
| Discovery | 10,000 | 2,000 residual worlds |
| Component shortlist | 512 | 5,000 exact component worlds |
| Five-week deep holdout | 64 | 25,000 untouched base worlds |
| High-goal stress | 64 | 25,000 independent goal-rate ×1.15 worlds |
| Eight-week combined field | 224 | Existing finalists + 128 horizon challengers + 32 neighbours |
| Eight-week deep holdout | 48 | 25,000 untouched worlds and three transfer policies |
| Cross-family synthesis | 23 | Candidates measured in both families |

Independent seeds separate discovery, selection and holdout. Named incumbents and scenario
specialists are protected through early cuts, so a new method cannot “win” by eliminating the old
champion before equal evaluation.

## 12. Five-week robustness family

Each of 64 finalists receives fixed, open-free-transfer and forced-GW2-roll policies. The audit
combines central evidence, raw component, xP-anchored and high-scoring environments:

| Scenario | Weight | Selected squad regret |
|---|---:|---:|
| Base evidence · open transfers | 30.0% | 0.304 |
| Base evidence · force GW2 roll | 20.0% | 0.302 |
| Base evidence · fixed squad | 10.0% | 0.560 |
| Raw component · open | 10.0% | 2.046 |
| Anchored xP · open | 15.0% | 0.490 |
| Goals +15% · open | 7.5% | 1.866 |
| Goals +15% · force GW2 roll | 5.0% | 1.360 |
| Goals +15% · fixed | 2.5% | 3.247 |

For candidate `c` and scenario `s`:

```math
regret(c,s) = best_value(s) - value(c,s)

robust_regret_5(c) = 0.75 * weighted_mean_regret(c)
                   + 0.25 * worst_scenario_regret(c)
```

The selected squad records weighted mean regret 0.775, worst regret 3.247 and five-week robust
regret 1.393. It remains the winner in all eight leave-one-scenario-out tests. Its paired central
edge over the previous robust incumbent is +0.419 points with a 95% Monte Carlo interval of +0.234
to +0.604.

The highest central mean belongs to another candidate. The selected squad consciously gives up
0.304 points to the central scenario leader in exchange for materially better cross-environment
stability. This is risk management in point units, not vague conservatism.

## 13. Eight-week horizon and transfer policy

### 13.1 Why an eight-week audit exists

Optimizing only GW1 can buy eleven good fixtures and four future problems. Treating all eight weeks
equally creates the opposite error: it pretends today's injury and role information is still precise
two months later. The engine evaluates a portfolio of horizons rather than declaring one natural
constant.

The central 0.88 decay gives GW1 weight 1.00 and GW8 weight `0.88^7 = 0.409`. Alternative views use
0.70, 0.80 and 0.94, plus separate GW1–3, GW1–5 and equal-weight GW6–8 scenarios. Fixed, open and
forced-GW2-roll paths distinguish squad quality from optimistic transfer execution.

### 13.2 Outcome-based calibration

A separate rolling historical replay re-optimized at every deadline using only out-of-fold
forecasts, carried legal squad and transfer state, and realized autosubs/captaincy. Selection on
2023/24–2024/25 preferred five weeks at 0.88, but it tied the eight-week incumbent on the untouched
2025/26 GW1–8 path. The candidate failed local-support and positive-test gates, so production kept
the broader eight-week/0.88 sensitivity portfolio.

This result prevents a convenient story. The engine uses eight weeks as an adversarial adequacy
audit, not because history proved eight to be universally optimal.

### 13.3 Current disagreement

The horizon-only leader is `R-1ca68907f5`, a 4-4-2. It beats the selected squad by 1.045 decayed
central points, with a paired interval of +0.910 to +1.180. Its horizon robust regret is only 0.193,
versus 0.917 for the published squad.

But it performs worse in the five-week model-risk family: robust regret 2.684 and open-transfer
high-goal regret 4.579. An eight-week winner is therefore not automatically the overall winner.
FPLAgent retains both facts.

Public manager histories support early optionality and later adaptation, not a fixed eight-week
team. In the 2025/26 top-100 trail, 61 managers rolled in GW2, only 22 in GW3 and 19 in GW4. Those
observations shape stress design but are descriptive and survivorship-selected; they do not set the
decay coefficient.

## 14. Cross-family synthesis

<!-- VISUAL:synthesis -->

For every candidate measured in both families:

```math
family_mean(c) = 0.50 * robust_regret_5(c)
               + 0.50 * robust_regret_8(c)

synthesis(c) = 0.80 * family_mean(c)
             + 0.20 * max(robust_regret_5(c), robust_regret_8(c))
```

The 20% maximum-family term penalizes specialists that are excellent only because one model family
likes them. Both inputs remain in FPL point-regret units; they are not rescaled to manufacture a
preferred answer.

| Candidate | Shape | Five-week regret | Eight-week regret | Synthesis | Rank |
|---|---|---:|---:|---:|---:|
| `R-92c8534bfc` | 3-4-3 | 1.393 | 0.917 | **1.202** | 1 |
| `R-5f3c2a2518` | 4-4-2 | 2.105 | 0.273 | 1.372 | 2 |
| `R-2ef866d551` | 4-4-2 | 2.158 | 0.334 | 1.428 | 3 |
| Previous incumbent `R-dc7de17def` | 4-4-2 | 1.534 | 1.312 | 1.445 | 4 |
| Horizon leader `R-1ca68907f5` | 4-4-2 | 2.684 | 0.193 | 1.688 | 9 |

The published 3-4-3 remains champion while the horizon family receives between 0% and 65.6% of
family weight. Beyond that, another 4-4-2—not necessarily the pure horizon leader—becomes the best
compromise. The balanced 50/50 policy lies comfortably inside the champion interval.

## 15. Bench allocation: rotation, not bench worship

The £20.5m visible bench initially looks expensive. The targeted audit asked whether the model was
overvaluing reserves.

Forty-two candidates received fresh five- and eight-week simulations, including eight squads at
or below £18.5m and the strongest historical-band challengers through £20.0m. The active squad was
the exact fresh winner. The strongest ≤£20.0m alternative shared 14 of 15 players but lost:

| View | Active minus ≤£20m challenger | 95% interval |
|---|---:|---:|
| Five-week base open | +0.27 | +0.22 to +0.32 |
| Five-week high-goal open | +1.06 | +1.01 to +1.12 |
| Eight-week open, decay 0.88 | +0.27 | +0.15 to +0.39 |
| GW6–8 only | +0.16 | +0.08 to +0.23 |
| Eight-week fixed | +0.37 | +0.32 to +0.43 |

The mechanism is rotation. Three of the four GW1 substitutes are scheduled to start later and the
group supplies eight planned starts across GW2–5. N.Williams is planned for GW3–5, Hill for GW2–5,
and Verbruggen for GW4. Xhaka is the one current non-rotator. The system is purchasing a flexible
15, not expecting £20.5m to remain unused.

Recent elite examples show observed opening/early-wildcard benches from £18.5m to £21.0m, but that
evidence is descriptive. The production rule is not “spend more on the bench.” It is “score all 15,
test cheaper matched alternatives, and keep depth only when autosub and planned-start value beats
the opportunity cost.”

## 16. Structure, scoring and role stress

### 16.1 Scoring and formation stress

Every synthesis finalist and five bench-proxy challengers was rescored under central rules, bonus
removed, defensive-contribution points removed, both removed, and both doubled. Exact autosubs and
captain fallback were used in all views.

The stress-specific leader was `R-1ced0705f3`; the published squad ranked third in the one-week
structure table, at 58.09 central xP versus 58.23. The publication gate still passed because there
was no supported one-week reversal that justified overturning the declared multiweek synthesis.
This prevents a narrow audit from silently changing the objective after candidate selection.

### 16.2 Preseason role scenarios

The role audit perturbs conditional appearance rates for players repeatedly absent from independent
preseason lineups and for players with low recent start shares. Baseline, moderate, severe and
not-listed-DNP boundary scenarios are tested in independent residual and component worlds. Winning
challenger squads are given the same exhaustive 550-configuration XI, bench, captain and vice
search as the incumbent.

Alternatives do win under the counterfactuals. That result is labeled
`material_counterfactual_reversal_requires_live_verification`, while `production_changed` remains
false. Conditional stresses are not source-authoritative probabilities. Their purpose is to tell
the manager exactly which news can change the answer. At publication, Watkins is the one selected
player requiring role verification.

### 16.3 Availability gate

The pipeline cannot publish a partially refreshed decision. Official status/news, price, fixture,
forecast, market, participation and role lineages are checked together. A stale or incoherent
availability watch blocks publication and retains the last valid workspace. On the current run all
clubs had feed coverage, no player had official-attention evidence, and the Watkins role item was
surfaced as scenario attention.

## 17. External benchmark and competitive evidence

Internal baselines are necessary but insufficient. A strong system should face a method it did not
invent. FPLAgent reproduces the public OpenFPL modeling shape—position models and matching feature
contract—on identical point-in-time folds and passes both models through the same legal £100m
squad, XI, bench and captain solver.

The matched benchmark contains 84,999 player-deadline forecasts, 12 position-season folds and 114
legal event decisions:

| Model | MAE | RMSE | Legal policy total relative to FPLAgent |
|---|---:|---:|---:|
| FPLAgent | **0.9779** | 1.9409 | 0 |
| OpenFPL-method reproduction | 0.9934 | **1.9373** | -69 points |

OpenFPL won the 2023/24 legal path by 41 points; FPLAgent won 2024/25 by 103 and 2025/26 by 7. The
benchmark therefore passes, but it is one reproducible public method—not proof that every external
model has been beaten. It provides meaningful competitive evidence because the comparison uses
the same rows and legal decisions rather than different leaderboards or post-hoc examples.

## 18. Season-long decision engine

The preseason squad is the first state of a longer system. Once the season begins, the dominant
question shifts from “which 15 should I buy?” to “given my actual squad and state, should I roll,
transfer, take a hit, change XI/captain or use a chip?”

### 18.1 Weekly state and transfers

The authenticated manager state includes the actual 15, XI, captain/vice, bank, free transfers,
purchase prices, selling prices and chips. Weekly action generation supports roll, one-transfer,
multi-free-transfer and paid-transfer routes, always rebuilding the best XI and captain from all 15.
FPL's half-profit selling rule is modeled exactly. A terminal value for banked free transfers was
learned from historical replay so the horizon does not spend a transfer merely because the last
visible week has no value for saving it.

The initial-squad five/eight-week audits deliberately allow no hits. Paid transfers matter after
the manager state exists and are evaluated net of four-point costs in the weekly engine.

### 18.2 Blanks and double gameweeks

The schedule receipt classifies confirmed, provisional and unassigned fixtures. Component outcomes
are simulated per fixture and then aggregated to the FPL event, so a player can have zero, one or
multiple matches. Historical double-gameweek rotation informs appearance handling. Unresolved
rearrangement probability remains shadow-only and blocks authoritative chip timing rather than
being guessed.

### 18.3 Chips and expiry

The 2026/27 rules provide Wildcard, Free Hit, Bench Boost and Triple Captain once in each half of
the season—eight chip slots—with first-half expiry after GW19. The engine represents permanent
Wildcard squad replacement, temporary Free Hit restoration, exact Bench Boost scoring and captain
tripling, transfer-bank transitions and one-chip-per-event legality.

Chip searches and historical retention replays exist, but their downside gates have not passed.
Operational advice therefore remains `no_chip` unless and until retained option value is validated.
This fail-closed behavior is a competitive advantage over a horizon that spends a chip simply
because it cannot see a better opportunity beyond its endpoint.

### 18.4 Price and execution timing

Current/purchase/selling prices and future affordability stresses are modeled. A prospective
rise/flat/fall collector and net-points timing scorer exist, but preseason has produced zero price
nights and zero timing decisions. Price forecasts receive no authority. Team value is diagnostic;
only realized net FPL points can promote an early-transfer policy. Until then the operational
recommendation is to wait for information unless the exact decision receipt has stronger evidence.

## 19. Evidence ledger: where each edge comes from

<!-- VISUAL:validation -->

| Addition | Decision mechanism | Evidence | Current authority |
|---|---|---|---|
| Point-in-time features | Blocks future information and stale-schema errors | 22 checks, 0 failures | Production |
| Own player xP | Ranks opportunity and availability without FPL `ep_next` | 11/12 MAE and top-k wins; +18 legal GW1 replay | Production |
| Opponent model | Replaces coarse fixture badges with attack/defence rates | Lower Poisson deviance on 2024/25 and 2025/26 | Production |
| Appearance calibration | Corrects over/under-confident DNP probabilities | Both Brier and log-loss gates passed for FWD only | FWD production only |
| Component simulation | Captures goals, clean sheets, bonus, autosubs and captain fallback jointly | Current-rule identities and historical BPS control | Production |
| Betfair team prior | Adds efficient scoring/clean-sheet information | Defender gains in 3/3 seasons; +27 frozen initial-squad points | 20% preseason DEF only |
| Global search | Challenges local roster structures | 551,183 legal candidates; distant MILP/evolution finalists | Production |
| Regret selector | Avoids a squad dependent on one preferred model | 8/8 leave-one-scenario-out wins | Production |
| Horizon portfolio | Prices future fixtures and transfer optionality without a rigid plan | 48 deep policies; historical decay replay retained broad incumbent | Production sensitivity family |
| Bench audit | Tests rotation value against cheap matched alternatives | 42-candidate fresh holdout; active exact winner | Production |
| Structure stress | Challenges scoring rules, formations and bench proxy | All finalists, five rule views, no supported reversal | Publication gate |
| Role stress | Identifies the exact news that can overturn the squad | Deep residual/component counterfactual reversals | Verification trigger only |
| OpenFPL benchmark | Tests against a strong external method | Lower MAE; +69 legal points over 114 decisions | Evidence, not a model input |
| Understat | Independent chance-quality ontology | Mixed folds; 0% legal selector | Shadow |
| Predicted lineups | Potential role/minutes edge | 0 completed prospective events | Shadow |
| Mean-reversion correction | Resists recency chasing | +23 untouched points but uncertainty crosses zero | Shadow |
| Full tail calibration | Tests p10/p90/CVaR reliability | 0 2026/27 events | Measurement only |
| Price/liquidity | Avoids forced affordability loss | 0 price nights | Measurement only |
| Chip timing | Values current gain against future expiry opportunity | Retention replay gates rejected | Shadow / no-chip |

This ledger is the heart of the methodology. “Implemented” and “used” are different states. A
feature can be useful because it proves that a tempting idea should stay out.

## 20. Why we are confident—and why variance still matters

Confidence comes from convergence of independent protections:

1. The forecast is independent of FPL's own expected-points field and beats a declared simple
   baseline on time-forward and legal-decision tests.
2. Team scoring rates beat a simpler fixture model on two untouched seasons.
3. The only external live feature with production weight—Betfair for defenders—passed bounded
   player and legal-policy gates; more aggressive weights failed and were rejected.
4. The selected structure emerged from more than half a million legal candidates and survived
   distant optimization, not just swaps around a favourite team.
5. Final comparisons use shared correlated worlds, exact autosubs and independent holdouts.
6. Five-week model/scoring risk and eight-week horizon/transfer risk disagree, and the final squad
   is the best balanced answer across both rather than a hidden cherry-pick.
7. Bench spend, scoring rules, formations and role uncertainty received dedicated adversarial
   tests after synthesis.
8. Publication is atomic and checksum-bound; stale partial runs cannot silently replace the last
   coherent decision.
9. A matched public-model reproduction gives external evidence rather than relying only on
   internal baselines.
10. Unproven complexity is kept at zero authority, reducing the risk of an impressive but fragile
    preseason model.

None of those protections eliminates football variance. A 57-point expectation is an average over
many possible worlds, not a promise. Red cards, penalties, deflections, late injuries and bonus
ties can dominate one gameweek. Even a genuinely superior season-long policy can lose a mini-league
over 38 events. The goal is to repeatedly choose actions with positive expected value, control
avoidable downside and update when evidence changes. The “variance gods” still get a vote.

## 21. Prospective 2026/27 proof plan

The current readiness verdict is
`DEADLINE_GRADE_RESEARCH_SYSTEM_NOT_SOTA_PROVEN`: all ten production gates passed in the readiness
audit, while only one of six research-frontier gates had passed before the season.

Every deadline will freeze the forecast, available alternatives and chosen action before outcomes.
After finalization the scoreboard will measure:

- player MAE, rank and legal decision points;
- appearance Brier score and log loss;
- OpenFPL-method and other matched challengers;
- RotoWire/FFScout lineup hit-rate and legal-policy lift;
- CRPS, 50%/80% interval coverage, p10/p90 tails by position;
- captain, starter and bench tail calibration;
- price-direction Brier/log loss and net-points timing value; and
- regret of squad, transfer, XI, captain, bench and chip decisions using only pre-deadline options.

Six completed events trigger diagnosis, not promotion by anecdote. At least 19 are required before
the first formal SOTA evidence claim, and even that must pass matched benchmark and decision gates.
The system is designed to learn from this season without rewriting history after seeing outcomes.

## 22. Reproducibility and operations

### 22.1 Transactional refresh

The web app refreshes official evidence on open only when the prior coherent decision is too old or
a semantic input changed. The current schedule is six hours outside T-24, two hours from T-24 to
T-3, and 30 minutes inside T-3. Manual refresh bypasses reuse. Price, availability, fixture,
market-generation or forecast checksum changes trigger the full pipeline immediately.

A full run stages outputs separately and publishes only when all gates pass. Closing the browser
does not cancel the backend process. If a run fails, the previous published workspace remains
active and the UI exposes the blocking receipt.

### 22.2 Rebuild command

```bash
uv sync
uv run fpl-data build
uv run fpl-data validate
uv run fplagent pipeline-gw1 --force
uv run python scripts/build_algorithm_whitepaper.py
```

Individual research commands are documented in the linked audit reports. The canonical deadline
run should use the transactional pipeline rather than manually composing a partial sequence.

### 22.3 Seed discipline

Simulation seeds are versioned by purpose. Discovery, selection, five-week holdout, high-goal
stress, horizon selection and horizon holdout use independent streams. Changing a seed is a
sensitivity test; repeatedly changing it until a preferred squad appears is not valid research.

## 23. Limitations and failure modes

### 23.1 Shared model risk

The direct xP model helps generate candidates and anchor component means. Independent holdouts
remove Monte Carlo selection noise, but they do not eliminate a shared wrong belief about a player
or team. The external data and market program is intended to reduce this risk only when incremental
legal-policy evidence is positive.

### 23.2 Search is broad, not exhaustive

There are vastly more legal budget/club-valid combinations than 551,183. MILP restarts and
evolutionary search give global reach, but the engine cannot prove an ungenerated squad would not
win. Protected benchmarks, one/two-swap enumeration and distant finalists make the search claim
stronger without turning it into a mathematical global proof.

### 23.3 Tail metrics are model-world diagnostics

Current p10, p90 and CVaR values compare candidates under shared simulated worlds. They are useful
for relative downside selection. They are not yet proven calibrated prediction intervals, because
zero 2026/27 events have been scored by the prospective distribution framework.

### 23.4 Current-role uncertainty

Predicted-lineup feeds have zero authority, and post-World-Cup preseason participation is unusually
difficult to interpret. The Watkins verification item is real. The answer should be rerun after
credible press-conference or squad evidence rather than assuming the current receipt is permanent.

### 23.5 Season-long frontiers

Ordinary weekly transfer mechanics are operational, but price forecasting, schedule-rearrangement
probability and retained chip value remain unpromoted. The system can calculate candidate actions;
it intentionally refuses to authorize the speculative parts until their point-in-time replays pass.

### 23.6 Source and rights risk

Public accessibility is not a commercial redistribution licence. This project is a local research
system. Any public product would need source-specific rights review, retention rules and paid data
contracts. Endpoints can change; every source needs a checksum, freshness policy and zero-authority
fallback.

## 24. Final deadline protocol

Before entering the team:

1. Refresh after the final relevant press conferences and near the GW1 deadline.
2. Verify Watkins and any new official status, transfer or registration changes.
3. Confirm all ten GW1 market fixtures still map cleanly; missing markets must fall back to the
   internal team model rather than stale prices.
4. Rebuild the forecast and complete all 12 pipeline stages when the semantic fingerprint changes.
5. Require the data, structure, role, availability and transactional publication gates to pass.
6. Compare the new receipt with `R-92c8534bfc`: squad, XI, captain, bench, family regrets and role
   items—not only the headline GW1 xP.
7. Freeze and hash the final receipt, then enter that exact legal team in FPL.

If no material evidence changes, reusing the checksum-identical receipt is more rigorous than
rerunning repeatedly and interpreting Monte Carlo noise as new information.

## 25. Conclusion

FPLAgent's competitive case is not one clever formula. It is the accumulation of disciplined
small edges and vetoes. Point-in-time reconstruction blocks leakage. The player model improves on
recent form. Opponent-adjusted rates improve fixture context. A carefully bounded market signal
adds defender information. Correlated simulation values all 15 players and exact game mechanics.
Global search challenges roster assumptions. Independent holdouts reduce selection noise. Regret
and horizon families stop one model from owning the answer. Bench, structure, role and availability
audits attack the final squad from different directions. Atomic publication stops incoherent
artifacts reaching the app.

The current result is a 3-4-3 built around Bruno Fernandes captaincy, a rotating £20.5m nominal
bench and a single live role-verification item. It is supported more deeply than the earlier squad,
but it is still a decision under uncertainty. The strongest reason for confidence is not that every
model agrees—they do not. It is that disagreement is measured, the selected squad remains near the
frontier across those disagreements, and unsupported signals are prevented from voting.

That is the standard the project should carry through the season: freeze what was known, choose the
best legal action, expose the counterfactuals, score the result honestly, and improve only when the
new method earns its place.

## Appendix A: current equations

```math
five_week_regret = 0.75 * weighted_scenario_regret
                   + 0.25 * worst_scenario_regret

eight_week_regret = 0.80 * weighted_horizon_regret
                    + 0.20 * worst_horizon_regret

family_mean = 0.50 * five_week_regret
            + 0.50 * eight_week_regret

final_synthesis = 0.80 * family_mean
                + 0.20 * max(five_week_regret, eight_week_regret)
```

The formulas are policy choices, not constants of nature. The receipt includes weight-sensitivity
intervals so a reviewer can see when another candidate becomes preferable.

## Appendix B: principal code map

| Responsibility | Module |
|---|---|
| Public data and immutable manifests | `src/fplagent_data` |
| Feature construction and allowlists | `src/fplagent_engine/features.py` |
| Opponent-adjusted ratings | `src/fplagent_engine/team_strength.py` |
| Player xP and appearance | `src/fplagent_engine/models.py` |
| Appearance calibration | `src/fplagent_engine/appearance_calibration.py` |
| Component event models | `src/fplagent_engine/component_models.py` |
| Correlated match simulation | `src/fplagent_engine/component_simulator.py` |
| FPL rules and scoring | `src/fplagent_engine/rules.py` |
| Legal optimizer | `src/fplagent_engine/optimizer.py` |
| Global squad generation | `src/fplagent_engine/global_search.py` |
| Five-week robust funnel | `src/fplagent_engine/robust_search.py` |
| Eight-week horizon audit | `src/fplagent_engine/horizon_audit.py` |
| Decision synthesis | `src/fplagent_engine/decision_synthesis.py` |
| Structure and autosub stress | `src/fplagent_engine/structure_stress.py` |
| Role scenario and threshold | `src/fplagent_engine/preseason_role_scenario.py` |
| Transactional pipeline | `src/fplagent_engine/deadline_pipeline.py` |
| Weekly state/action engine | `src/fplagent_engine/weekly.py` |
| API workspace and refresh | `src/fplagent_api` |
| Decision cockpit | `web/src/components/DeadlineCockpit.tsx` |

## Appendix C: canonical evidence artifacts

| Artifact | Meaning |
|---|---|
| `data/manifests/fpl-gw1-deadline-pipeline.json` | Atomic publication and input lineage |
| `data/model/artifacts/forecast_v2/metrics.json` | Champion player forecast and time-forward gate |
| `data/model/normalized/team_strength_metrics.json` | Team-rating validation |
| `data/model/component_backtest_v1/metrics.json` | Component blend selection |
| `data/model/bps_2026_27_v1/metrics.json` | Current-rule BPS and defensive-contribution reconstruction |
| `data/model/market_feature_v1/results.json` | Betfair feature promotion boundary |
| `data/model/external_forecast_benchmark_v1/results.json` | Matched OpenFPL-method benchmark |
| `data/model/robust_search_v2_global/results.json` | Five-week global robust audit |
| `data/model/horizon_audit_v1/results.json` | Eight-week policy audit |
| `data/model/gw1_decision_synthesis_v1/results.json` | Cross-family ranking and selected squad |
| `data/model/gw1_structure_stress_v1/results.json` | Scoring, formation and autosub stress |
| `data/model/preseason_role_scenario_v1/results.json` | Role counterfactuals |
| `data/model/preseason_role_threshold_v1/results.json` | Appearance reversal boundary |
| `data/model/bench_allocation_audit_v2/results.json` | Matched bench-depth challenge |
| `data/model/sota_readiness_v1/results.json` | Production/SOTA claim boundary |
| `data/model/prospective_2026_27_scoreboard_v1/results.json` | Frozen prospective season scoreboard |
| `data/decisions/2026-27-gw1-synthesized.json` | User-facing machine decision receipt |

## Appendix D: source references and further reading

- Official FPL application API: `https://fantasy.premierleague.com/api/`
- Official FPL help and current rules: `https://fantasy.premierleague.com/help/`
- Vaastav historical repository: `https://github.com/vaastav/Fantasy-Premier-League`
- Source authority contract: `docs/forecast-source-authority.md`
- Market subsystem: `docs/market-evidence-subsystem.md`
- Participation evidence: `docs/participation-evidence.md`
- SOTA evidence framework: `docs/sota-evidence-framework.md`
- Current project status: `docs/project-status.md`
- Global robust audit: `reports/gw1-global-robust-search.md`
- Horizon audit: `reports/gw1-horizon-adequacy-audit.md`
- Synthesis: `reports/gw1-synthesized-decision.md`
- Bench allocation audit: `reports/current-season-bench-allocation-audit.md`
- OpenFPL benchmark: `reports/openfpl-matched-benchmark.md`
- State-of-the-art readiness audit: `reports/fplagent-sota-readiness-audit.md`
