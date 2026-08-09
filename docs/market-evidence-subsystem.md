# Market evidence subsystem

**Implemented:** 8 August 2026  
**Status:** live collection and paired shadow simulation; zero decision authority

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

The current provider is [Football-Data](https://www.football-data.co.uk/matches.php). The collector
uses only its non-closing, pre-deadline columns:

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

## Live collection contract

`fplagent collect-current-market-goals --horizon 5` now:

1. selects the official next FPL event rather than assuming GW1;
2. maps a configurable forward event horizon to exact official fixture and team IDs;
3. archives the downloaded CSV by content hash even when coverage is partial;
4. records coverage separately for every event;
5. verifies that the provider upload time precedes each FPL deadline;
6. materialises every complete fixture, but marks an event ready only when all its official
   fixtures have complete 1X2 and totals prices; and
7. writes an idempotent semantic receipt, so unchanged source bytes do not trigger a needless full
   decision run.

Partial data has no decision authority. A missing fixture, stale timestamp, schema mismatch,
artifact hash mismatch or simulator fixture mismatch disables the challenger. If collection fails,
the pipeline writes an unavailable receipt so an older apparently-ready snapshot cannot be reused.

On 8 August 2026 the provider file contains no Premier League rows. The receipt correctly reports
zero of ten GW1 fixtures, while retaining the source upload time of 7 August. Nothing is inferred or
fabricated while the prices are absent.

## How it enters the FPL simulations

The deadline refresh collects market evidence after the official FPL snapshot is preprocessed.
Its status and content hashes form part of both the GW1 and weekly pipeline identities, so a newly
published price batch invalidates the affected cached decision.

When an event is complete and timestamp-safe, its market rates replace internal fixture rates in a
second paired simulation. Uncovered future events continue to use internal rates. The challenger
uses the same seed, player universe, fixture schedule, component forecasts and action candidates as
the incumbent, isolating the effect of the changed match environment.

There are two integration points:

- **Preseason/GW1:** the component tournament re-scores its fixed, transfer-policy and
  component-native candidate universes under paired market worlds. It records leader changes,
  rank movement and the largest expected-point shifts. It cannot change the robust GW1 synthesis.
- **In-season:** the weekly engine re-scores every roll, transfer, hit and chip-shadow route under
  paired market worlds after XI, bench, captain and vice-captain optimisation from all 15 players.
  It records action-value and rank changes but is not included in production scenario weights.

Every ready decision receipt includes the exact market rate artifact and receipt hashes. The UI can
therefore explain statements such as “the market is more optimistic about this attack” without
quietly changing the official recommendation.

## Promotion path

The subsystem deliberately separates four questions:

1. Are the source and timestamp valid?
2. Are team goals and clean sheets better calibrated?
3. Do better team probabilities improve legal squad, XI, bench and captain decisions?
4. Do they improve a continuous season path after transfers, hits, prices and retained options?

Only the first two currently pass. Promotion requires frozen prospective 2026/27 shadow receipts
and a new sequential policy that turns the signal into stable net points rather than extra churn.
Candidate generation from market player marginals and a learned confidence-aware blend can then be
tested. The current zero weight must not be raised because one gameweek happens to look persuasive.

## Provider roadmap

Football-Data is a useful research-safe first source, but one feed is not operational redundancy.
The schema is provider-neutral enough to add a licensed odds API later. A second provider should
contribute timestamped 1X2, totals and handicap observations; consensus should be built at a common
observation cutoff, with provider reliability and disagreement calibrated historically. API keys
must stay server-side and raw responses must remain immutable.

The next decision work is evidence accumulation, not more plumbing: collect every deadline
snapshot, score the frozen market shadow after each finalised event, attribute gains or losses to
team-rate calibration versus player allocation, and revisit authority only at a declared review.
