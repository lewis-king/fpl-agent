# FPLAgent points-first product roadmap

**Updated:** 8 August 2026  
**North star:** maximise Lewis's season points with fresh evidence, calibrated forecasts and legal,
reproducible decisions. Chat explains and interrogates those decisions; it does not create them.

This is the product-level plan. The detailed research record and completed experiments remain in
[`reports/points-first-season-roadmap.md`](../reports/points-first-season-roadmap.md).

## The operating loop

Every app open invokes the same deadline orchestrator:

`serve last receipt -> collect current evidence -> validate -> diff hashes -> rebuild affected
features -> forecast -> generate legal actions -> simulate -> synthesise -> atomically publish`

The last valid receipt can render immediately while refresh runs. Invoking the orchestrator always
counts as a decision run, but content-addressed stages are reused when their inputs are byte-for-byte
unchanged. A changed official snapshot, authenticated squad, fixture allocation, price, availability
or model artifact invalidates only its dependent stages. Stale or incomplete evidence can never
silently replace the last valid decision.

The resulting immutable receipt contains the source timestamps and hashes, manager state, rules,
forecast generation, every serious alternative, selected squad/action, XI, bench order, captain,
vice-captain, uncertainty and the reason the strongest alternative lost.

The same loop now owns current-season feature supply. Once an event is final and data-checked it
archives the official event-live player outcomes, advances rolling xG/xA/minutes/points features,
updates opponent-adjusted team ratings with final scores, emits the next actionable horizon and
fails closed if the normalized stream does not reconcile to FPL's cumulative totals. The detailed
source and staleness contract is in the
[live feature availability report](../reports/live-feature-availability-contract.md).

## Prioritisation board

| Order | Capability | Why it can win points | Current state | Promotion evidence |
| --- | --- | --- | --- | --- |
| 0 | Freeze the bounded V9 LLM experiment | Prevents an unreliable chat layer from contradicting the engine | **Complete: rejected; app defaults unchanged and further LoRA work parked** | Locked evaluation rejected V9 despite better routing and screenshot extraction |
| 1 | App-open refresh and decision receipt | Makes every visible recommendation current and internally consistent | **Cached-first lifecycle, MCP sync, persisted single flight, deadline windows and semantic official-change triggers implemented** | Repeated-input byte identity, stale-source rejection, atomic UI switch |
| 2 | Fresh GW1 evidence and final squad tournament | A wrong availability assumption or stale fixture can sink the opening squad for weeks | **Reproducible staged GW1 funnel, rollback gate and live scheduled runner implemented** | Live runs at T-72h, T-24h, T-6h, T-60m and T-10m; independent simulation seed |
| 3 | Preseason minutes, role and availability | Participation error is the largest avoidable GW1 failure mode | **Live 18/20-club feed; squad-specific role scenario, threshold and watch now run inside the publication transaction** | Position-specific forward calibration plus legal squad/captain replay |
| 4 | First real weekly manager-state run | Converts the picker into roll/transfer/XI/bench/captain decisions | **State machine, weekly optimiser and event-calendar/scheduler handoff implemented; awaiting complete post-GW1 FPL state** | Exact authenticated state, legal transitions and published roll comparator |
| 5 | Price-change and early-transfer policy | Team value creates future feasible moves, but early transfers sacrifice information | **Official threshold/outcome calibration and exact affordability shadow implemented; operational advice remains wait** | Prospective midnight calibration plus move-now-versus-wait net-points replay; team value is diagnostic only |
| 6 | Blank/double and rearrangement scenarios | Fixture quantity, rotation and uncertainty alter transfers, chips and captaincy together | **Point-in-time rearrangement episodes and a correlated Monte Carlo shadow are integrated; the sparse historical gate rejects authority** | Reach 20 independent resolution batches across three seasons, then prospective calibration; never treat a speculative fixture as confirmed |
| 7 | Wildcard and Free Hit optimiser | These can repair structural decay or exploit a blank/double in one high-value action | **Exact permanent-WC/temporary-FH search and continuous retained-value replay are complete; historical downside rejects promotion** | Improve the frozen policy until untouched block downside passes, then joint four-chip and prospective replay |
| 8 | Bench Boost and Triple Captain authority | Concentrated upside, especially in doubles, but large opportunity cost | **Exact branches and a frozen selection/test timing replay are complete; forecast-oracle timing regret rejects promotion** | Beat the retained-timing safety gate, then joint four-chip and prospective replay |
| 9 | Forecast challenger programme | Better participation, team rates, returns and bonus ordering improve every decision | **A checksum-bound five-challenger registry now combines historical gates with paired live policy evidence; direct xP remains champion and automatic promotion is forbidden** | Ten paired prospective events, positive mean/downside gate and scheduled review for any historically passing challenger |
| 10 | Prospective learning and attribution | Stops us repeating errors or promoting a model because of luck | **Final-event scoring now attributes action, legal-XI/captain upper bounds, participation calibration and frozen challenger policy deltas; a season scoreboard aggregates the latest receipt per GW** | Six finalized events open diagnostic review; model/policy promotion still requires its separate gate |
| 11 | Late-season mini-league strategy | Overall points and opponent-aware risk can diverge near the finish | **Prior-GW rival-lineup context, gap pressure, exposure distance and an xP-sacrifice cap now produce a zero-authority late-season shadow** | Historical rank simulation plus prospective league receipts; points-first action remains operational |

Orders 1–4 are the immediate points path. Orders 5–8 should be built before their first likely use,
but they must not displace the deadline-critical GW1 work.

## 1. Preseason and GW1

### Freshness windows

- Capture official bootstrap and fixtures, authenticated squad state, forecast inputs and attributable
  availability evidence on app open and at scheduled deadline windows.
- Between those windows, probe decision-relevant official semantics on a deadline-sensitive cadence.
  Status/news, prices, set-piece orders, rules and fixture allocation trigger the full pipeline;
  transfer-counter noise is reserved for the cheaper price telemetry path.
- Tighten source TTLs as the deadline approaches. Team news can invalidate a run immediately.
- Poll current market odds on every refresh. Archive partial evidence, but admit only a complete,
  timestamp-safe event to paired match-world simulation. Its weekly transfer challenger failed the
  untouched season and therefore has zero decision weight.
- Record every publication candidate; never overwrite the active decision until all lineage and
  completeness checks pass.

### Final selection funnel

- Search legal 15-player squads globally, then protect high-value one-swap neighbours that a shortlist
  cutoff could miss.
- Evaluate 3/5/8-event horizons, future decay, open-transfer and fixed-squad views, bank constraints,
  formations, bench spending, player-role stress and correlated match simulations.
- For every candidate, jointly optimise the XI from all 15, bench order, captain and vice-captain.
- Prefer the evidence-weighted low-regret choice, not a fragile central-mean winner.

### Participation evidence

The next model work is targeted rather than another blanket calibration: DNP/1–59/60–89/90
probabilities, conditional minute quantiles, preseason starts/substitutions, injuries/suspensions,
new-signing and promoted-club priors, and explicit uncertainty for uncovered clubs. A position is
promoted only if probability metrics and downstream decision replay improve on forward seasons.

## 2. Weekly decision engine

The immutable state contains all 15 players, purchase/current/selling prices, bank, up to five free
transfers, committed hits, chip inventory, event status, XI, bench, captain and vice-captain. Every
gameweek generates comparable action bundles:

1. roll;
2. best one-free-transfer action;
3. best use of all currently useful free transfers;
4. paid routes only when the after-hit gain is stable;
5. eligible chip and no-chip variants; and
6. the best XI, bench order, captain and vice after every squad route.

All 15 players enter lineup and captain consideration. Actions run on shared correlated worlds so a
bench promotion, captain fallback or hit is compared on the same football outcomes. The UI should
lead with the selected action, gain versus roll, uncertainty and strongest rejected alternative,
then allow the player to inspect every assumption.

## 3. Price-change economics

Price is an option-value signal, never a substitute for expected points.

### Data

- Store append-only official Price Change Predictor and bootstrap player snapshots on the
  predictor's 15-minute cadence where practical, with current cost, event transfers in/out,
  ownership, availability and observation time.
- Derive ownership-normalised net-transfer velocity, acceleration, proximity to midnight, recent
  price moves and predictor state.
- The point-in-time feature builder for those fields is implemented and fails closed until two
  within-event observations exist. The first real two-observation 2026/27 generation is now ready;
  preseason counters are correctly flat. It remains evidence-only until policy validation.
- A prospective outcome builder now pairs the nearest observations around UK midnight, rejects
  gaps over four hours, labels actual £0.1m moves and scores rise/fall thresholds independently.
  It requires 14 nights, 30 predictions per direction and 75% precision per direction before its
  first calibration gate can pass.
- Preserve each manager holding's purchase and exact selling price; a rise does not always produce
  an immediate sale-value gain because profit is halved and rounded down.

### Decision policy

- Use the official progress threshold as the first challenger and calibrate it prospectively. Do
  not mislabel threshold progress as probability; fit a probability model only after enough clean
  point-in-time outcomes exist.
- Compare `move now`, `wait for information`, and alternative transfers. Include the value of a
  newly affordable route, the risk of being priced out, injury/line-up information expected before
  the deadline, and the value of the bank/free transfer retained.
- Reject price-only churn. An early move must already be a credible points move and its financing
  benefit must exceed the historical cost of lost information.
- The selected weekly transfer route now receives an exact one-update affordability stress using
  its post-transfer bank and every incoming/outgoing player. The result is lineage-bound in the
  decision receipt, but always returns operational `wait`; even `move_now_candidate` is shadow-only.

### Validation

Use historical price paths and transfer counts only where their timestamps are defensible. The
adjacent public weekly snapshots were explicitly rejected for this task: their next price labels
occurred a median 3.6–5.1 days after the decision deadline and therefore contain post-deadline
transfer behaviour. The 2026/27 15-minute stream is the clean prospective test. Report decision
feasibility and net points; team value is diagnostic, not the promotion metric. See the
[price-change and early-transfer policy](early-transfer-policy.md).

## 4. Chips, expiry, blanks and doubles

The live 2026/27 rules source is authoritative. The current captured rules provide one Wildcard,
Free Hit, Bench Boost and Triple Captain in GW1/2–19 and another complete set in GW20–38: eight
chips in total, rather than only two Wildcards. The first set expires at the GW19 deadline; it does
not carry over. The implementation must re-ingest and hash the official rules instead of carrying
this assumption into a later season. See the official
[2026/27 chip rules](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627).

### Wildcard

- Search a fresh legal 15-player squad with unlimited permanent transfers and the exact bank.
- Compare it with ordinary-transfer repair routes over multiple receding horizons and correlated
  scenarios.
- Charge retained-chip option value. That value naturally declines toward zero at the half-season
  expiry, but `use it or lose it` is not enough to justify a harmful restructure.
- Prefer Wildcard for coordinated structural gain—several weak holdings, bad price structure,
  availability damage or a fixture-regime change—not one tempting player.
- The exact legal search is implemented and carries its new squad through every simulated event.
  Its raw delta to the strongest ordinary route is receipt evidence only until retained-chip value
  is calibrated.

### Free Hit

- Optimise a one-event temporary squad for a confirmed blank/double or exceptional ordinary week.
- Restore the prior squad and bank at the next deadline with then-current prices; preserve the
  entering transfer bank under the current rules.
- Compare against normal transfers, hits and chip retention. Reject consecutive Free Hits, including
  GW19 to GW20.
- The exact legal search is implemented. Its event-by-event simulation uses the temporary squad
  only now, then restores the original 15 and bank for every later event. This is tested explicitly
  to prevent temporary players leaking into the horizon.

### Bench Boost

- Score all 15 players plus ordinary captaincy, per fixture.
- Optimise transfers and bench quality jointly; do not rate a chip on the existing bench alone.
- Compare current uplift with the best credible remaining same-half opportunity and the squad
  compromises needed to prepare it.

### Triple Captain

- Score the third captain copy with exact vice-captain fallback when the captain plays zero minutes.
- Evaluate haul distribution, minutes risk and correlation across every fixture in a double rather
  than multiplying a single point estimate.

### Blank/double handling

- Build schedule states from only what was knowable before each deadline: confirmed, provisional,
  probabilistically rearranged and unassigned.
- Score zero/one/multiple fixtures per club. In a double, appearance, clean sheets, concessions,
  saves, cards, defensive contributions and bonus are match-scoped before event aggregation.
- Model double-gameweek rotation and shared team/opponent outcomes; two fixtures do not mean twice
  the certainty.
- Block chip authority when schedule coverage is incomplete or the recommendation reverses under
  plausible rearrangements.

### Historical evidence

Past high-ranking-manager chip usage is useful as a descriptive baseline, not causal proof. The
promotion test is a point-in-time replay of our policy against no-chip and established heuristics.
Retained opportunity value must use only the fixture states knowable at each deadline, with one
season for selection, untouched forward seasons for testing, and prospective 2026/27 shadow
decisions frozen before every deadline.

See the [Wildcard and Free Hit decision shadow](squad-chip-shadow.md).

The present manager-level archive is informative but not large enough to learn a chip policy by
imitation: it contains 266 Gameweek states and all 56 chip uses for seven tracked 2025/26 managers,
plus 380 states for ten top managers from 2019/20 under a different rule/calendar regime. We will
use those choices as behavioural comparators. The causal promotion evidence must come from the much
larger player/fixture history, our own legal point-in-time policy simulation and the prospective
2026/27 stream.

## 5. Forecast improvements

### Historical/live feature parity

Every feature admitted to a challenger must declare both a point-in-time historical source and a
live serving source. Player event xG/xA and participation now come from immutable official
event-live outcomes after each data-checked GW; fixture scores advance the online team model. The
weekly builder rolls from the next actionable event rather than remaining anchored to GW1. Missing
or schema-changed live data blocks publication instead of silently falling back to last season.

Champion/challenger order:

1. participation and minutes by position;
2. current-rule bonus/BPS and defensive contributions;
3. player goal/assist/clean-sheet/save/card event rates;
4. team strength, promoted-team priors, rest/congestion, Europe and manager changes;
5. calibrated 5+/10+ return and full score distributions; and
6. market/Elo/xG challengers only where licensing and timestamps are safe.

The market challenger now has a live, event-aware evidence path into both the GW1 component
tournament and the in-season weekly simulator. It uses paired random worlds and records candidate or
action rank changes, but it is omitted from production scenario weights. Full provenance and the
promotion contract are documented in the
[market evidence subsystem](market-evidence-subsystem.md).

Every candidate uses time-forward folds, a frozen selection season and an untouched test season.
Statistical improvement is only permission to run legal squad/transfer/captain replay. A model is
promoted only when downstream outcomes also clear downside and legality gates.

## 6. Learning after every gameweek

Before the deadline, freeze the forecast for every selectable player and every serious action. Once
FPL marks the event final and data-checked:

- ingest final points and minutes;
- apply exact autosubs, captain fallback and hits;
- score the chosen action, roll and all frozen alternatives;
- attribute error to participation, team goals, player events, bonus/rules or optimisation;
- update calibration and policy-regret dashboards; and
- change a champion only at a scheduled review, never by hindsight after one bad result.

One manager gives only 38 path-dependent outcomes, so learning also uses every player/event forecast
and frozen counterfactual. Season points and rank remain the product result; forecast calibration
and counterfactual regret tell us whether the process is actually improving.

## Immediate delivery sequence

1. Operate the implemented app-open, material-change and deadline-window orchestrator; monitor its
   receipts rather than launching parallel decision paths.
2. Operate the live GW1 evidence windows; improve only attributable participation inputs that pass
   the full squad decision funnel.
3. Run and publish the final independent-seed GW1 tournament.
4. Exercise the exact authenticated weekly contract on the first complete post-GW1 response.
5. Operate the implemented price shadow and promote only after prospective threshold calibration
   plus move-now-versus-wait net-points replay.
6. Accumulate more point-in-time rearrangement episodes; the implemented probabilistic shadow stays
   diagnostic until its independent-batch and season-coverage gate passes.
7. Improve the rejected WC/FH and BB/TC retained-timing policies, then run one continuous joint
   four-chip replay using the implemented exact searches and point-in-time schedule ledger.
8. Accumulate prospective receipts and promote forecast/policy challengers only at declared reviews.

This order is open to product reprioritisation, but a lower item should move upward only if its likely
points value before its first decision deadline exceeds the operational or modelling risk above it.
