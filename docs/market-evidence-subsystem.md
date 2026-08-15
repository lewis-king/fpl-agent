# Market evidence subsystem

**Implemented:** 10 August 2026
**Status:** live collection and paired simulation; bounded 20% preseason defender-feature authority, zero direct simulator or weekly-transfer authority

FPLAgent uses football betting prices as an independent estimate of the scoring environment of a
fixture. The useful signal is not “which bet should be placed”. It is the market's aggregate view
of home goals, away goals and clean-sheet probability, which affects every FPL player in that
match.

## Why this belongs in the engine

The internal team model learns from past scores, xG, venue and opponent strength. A pre-deadline
market can also incorporate injuries, likely line-ups, tactical news and collective forecasting
that are not yet represented in those features. The two sources fail differently, making their
disagreement useful even when the market is not allowed to select the squad.

Historical evidence supports the fixture signal but not yet an authoritative transfer policy:

- On the untouched 2023/24–2025/26 fixture set, market Poisson deviance is `1.0514` versus
  `1.0892` for the incumbent; goal MAE is `0.9179` versus `0.9331`; clean-sheet Brier is `0.1678`
  versus `0.1702`.
- A sequential legal transfer replay selected a 25% market blend on 2024/25, then lost two net
  points on untouched 2025/26. Its four-GW block interval crossed zero.

The fixture prediction passed; the naïve decision policy did not. That is why the current system
uses market-derived match worlds as a measured challenger and gives them no production weight.
See [the fixture challenger](../reports/market-goal-rate-challenger.md) and
[the sequential policy replay](../reports/market-goal-sequential-transfer-replay.md).

## Data and transformation

The preferred provider remains [Football-Data](https://www.football-data.co.uk/matches.php) when it
has a complete event because its market-average columns match the historical evaluation contract.
When that forward file is incomplete or unavailable, the collector now falls back to the public,
delayed [Betfair Exchange football surface](https://www.betfair.com/exchange/plus/en/football)
read-only surface. Football-Data contributes only its non-closing, pre-deadline columns:

- market-average home/draw/away prices: `AvgH`, `AvgD`, `AvgA`;
- market-average over/under 2.5 prices: `Avg>2.5`, `Avg<2.5`;
- individual sportsbook and Betfair Exchange prices for disagreement diagnostics; and
- the current Asian-handicap line and average prices as preserved evidence, not yet as a fitted
  target.

No closing-price column enters a current decision or point-in-time historical test. Implied
probabilities are de-vigged. Two independent Poisson rates are fitted jointly to the 1X2 and total
goal probabilities. From those coherent home and away rates the artifact derives:

- expected home, away and total goals;
- home and away clean-sheet probabilities;
- both-teams-to-score and 0–0 probabilities; and
- fit error, overround and cross-book disagreement.

The market average remains the central estimate. Individual books are used to quantify agreement,
not counted as fully independent models. This avoids false confidence from several prices that are
all reacting to the same information.

For Betfair, no account, session or browser automation is used. The adapter reads the public page's
EDS application key, searches the public competition facet for the exact football competition name
`English Premier League`, and uses the returned competition ID. The familiar numeric URL suffix is
therefore a discovered value, not a permanent configuration constant. The adapter then discovers
official competition events, resolves the `MATCH_ODDS` and
`OVER_UNDER_25` market IDs, then retrieves delayed best back and lay books from anonymous read-only
JSON endpoints. Each selection's estimate is the midpoint in implied-probability space between its
best back and lay prices. The receipt preserves both sides, available sizes, market matched volume,
spread and delayed-data flag. Betfair is a single exchange source, not a market average, so its live
shadow remains separately labelled.

Betfair now has its own historical calibration rather than inheriting the market-average result.
The non-closing `BFEH/BFED/BFEA` and `BFE>2.5/BFE<2.5` archive covers 377/380 fixtures in 2024/25
and 360/380 in 2025/26. On the untouched 2025/26 covered fixtures, its Poisson deviance is `1.0501`
versus `1.0848` internally, while the broader bookmaker average is slightly better at `1.0472`.
Validation selected a 20% Betfair player-component blend, but the untouched continuous legal FPL
path scored `2005` versus `2007` for the incumbent. See
[the provider-specific calibration](../reports/betfair-exchange-calibration.md).

## Live collection contract

`fplagent collect-current-market-goals --horizon 5` now:

1. selects the official next FPL event rather than assuming GW1;
2. maps a configurable forward event horizon to exact official fixture and team IDs;
3. archives the downloaded CSV by content hash even when coverage is partial;
4. records coverage separately for every event;
5. verifies that the provider upload time precedes each FPL deadline;
6. materialises every complete fixture, but marks an event ready only when all its official
   fixtures have complete 1X2 and totals prices; and
7. tries Betfair when Football-Data cannot complete the primary event, while retaining both source
   outcomes in provenance; and
8. writes an idempotent semantic receipt, so unchanged source bytes do not trigger a needless full
   decision run; and
9. feeds a cheap material-change probe that archives every observation but launches the full
   optimizer only when event coverage/provider changes, team goal expectation moves by at least
   `0.10`, or clean-sheet probability moves by at least `0.025`.

Partial data has no decision authority. A missing fixture, stale timestamp, schema mismatch,
artifact hash mismatch or simulator fixture mismatch disables the challenger. If collection fails,
the pipeline writes an unavailable receipt so an older apparently-ready snapshot cannot be reused.

On 9 August 2026 Football-Data still contained no Premier League rows, but the Betfair fallback
resolved all ten official GW1 fixtures with complete 1X2 and O/U 2.5 books. The resulting receipt is
`ready`, timestamp-safe and backed by immutable source documents. Explicit aliases reconcile four
provider names—Coventry, Hull, Ipswich and Nottm Forest—to the official FPL catalog; any other
unmatched fixture still fails closed. Events GW2–GW5 remain incomplete and therefore continue to
use internal rates only.

## How it enters the FPL simulations

The deadline refresh collects market evidence after the official FPL snapshot is preprocessed.
Its status and content hashes form part of both the GW1 and weekly pipeline identities. Between
scheduled full runs, the decision-change probe separates raw exchange movement from material
football movement; a small price tick is archived without launching a roughly 40-minute search.
The scheduled T-72h/T-24h/T-6h/T-60m/T-10m windows still validate the complete generation.

The first live comparison on 10 August observed a maximum `0.0493` team-goal move and `0.0131`
clean-sheet-probability move. Official FPL semantics were unchanged, so the probe correctly
recorded `changed: false` and retained the validated decision.

When an event is complete and timestamp-safe, its market rates replace internal fixture rates in a
second paired simulation. Uncovered future events continue to use internal rates. The challenger
uses the same seed, player universe, fixture schedule, component forecasts and action candidates as
the incumbent, isolating the effect of the changed match environment.

There are now three integration points:

- **Preseason/GW1:** the component tournament re-scores its fixed, transfer-policy and
  component-native candidate universes under paired market worlds. It records leader changes,
  rank movement and the largest expected-point shifts. It cannot change the robust GW1 synthesis.
- **In-season:** the weekly engine re-scores every roll, transfer, hit and chip-shadow route under
  paired market worlds after XI, bench, captain and vice-captain optimisation from all 15 players.
  It records action-value and rank changes but is not included in production scenario weights.
- **Preseason player forecast:** a season-forward defender model consumes Betfair team scoring,
  opponent scoring and clean-sheet expectations alongside the existing player, role, minutes and
  price features. Only a checksum-bound, fully covered event is eligible. The promoted blend is
  capped at 20%, so 80% of defender expected points remains the incumbent player forecast. Other
  positions and uncovered events are unchanged.

Every ready decision receipt includes the exact market rate artifact and receipt hashes. The UI can
therefore explain statements such as “the market is more optimistic about this attack” without
quietly changing the official recommendation.

The runtime also has two fail-closed production-blend paths. Direct replacement of simulator goal
rates requires the current provider to match
the provider-specific calibration, exact event coverage, a valid pre-deadline receipt and a passing
held-out legal-policy gate. A passing Betfair result would start at no more than 25% goal-rate
weight; a missing, rejected or malformed calibration yields exactly 0%. The current Betfair result
is `REJECT`, so direct simulator rates remain byte-for-byte equivalent to the incumbent.

The separate player-feature policy passed its bounded preseason gate. Defender top-k realised
points and MAE improved in all three forward seasons. A 20% stability blend changed continuous
legal-policy net points by +64 in 2023/24, +76 in 2024/25 and +90 on frozen 2025/26; independent
2025/26 weekly squad rebuilds improved by +27. The frozen continuous-season four-GW block interval
was +0.816 to +4.132 points per GW. This grants **preseason squad/XI authority only**. The direct
forecast manifest includes the policy, model, market receipt and rate hashes, and a changed Betfair
snapshot invalidates forecast reuse. The full receipt is in
[the market-feature player policy](../reports/market-feature-player-policy.md).

The phase boundary is executable, not documentary: once the official GW1 deadline passes, the
feature policy resolves to `weekly`, whose promoted weight is exactly zero. A regression test
covers both sides of that deadline.

## Promotion path

The subsystem deliberately separates four questions:

1. Are the source and timestamp valid?
2. Are team goals and clean sheets better calibrated?
3. Do better team probabilities improve legal squad, XI, bench and captain decisions?
4. Do they improve a continuous season path after transfers, hits, prices and retained options?

The blunt Betfair fixture-rate replacement passed the first two questions but lost two points on
the untouched legal season and remains rejected. Treating the market as player-model features,
rather than substituting the whole fixture model, passed all three defender forecast screens and
all three season-total decision replays. The conservative 20% preseason blend is therefore live.
Weekly transfer authority remains disabled: although every season total was positive, the pooled
out-of-selection downside bound was -0.158 points/GW against the declared -0.10 threshold. Frozen
prospective 2026/27 receipts will decide that later promotion; a single successful gameweek cannot.

## Provider roadmap

Football-Data plus Betfair provides operational fallback, but not two independent market-average
estimates. The next provider improvement is a supported Betfair Exchange API application or a
licensed odds API with timestamped 1X2, totals and handicap observations. Consensus should be built
at a common observation cutoff, with provider reliability, liquidity and disagreement calibrated
historically. Private API keys must stay server-side and raw responses remain immutable.

The next decision work is evidence accumulation, not more plumbing: collect every deadline
snapshot, score the frozen market shadow after each finalised event, attribute gains or losses to
team-rate calibration versus player allocation, and revisit authority only at a declared review.
