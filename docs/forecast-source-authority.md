# Forecast source authority

FPLAgent owns its expected-points forecast. The official FPL fields `ep_this`, `ep_next` and the
common alias `xP` are forbidden as model features, baselines, fallbacks and tie-breakers in
production. They remain visible only in raw source snapshots so that ingestion is lossless.
The denylist is enforced when a model matrix is built as well as by tests and the release-readiness
audit, so an old or malformed model artifact cannot quietly reintroduce them at inference time.

## What produces our xP

The production forecast is a position-specific XGBoost hurdle system trained on point-in-time
deadline rows. One model estimates conditional FPL points when a player appears; a second estimates
the probability of DNP, 1–59, 60–89 and 90+ minutes. Their product is our expected points. Inputs
include lagged realised FPL outcomes, lagged FPL/Opta xG and xA, minutes, starts, BPS, defensive
contributions, set-piece order, price, availability, venue and an opponent-adjusted team-strength
model. Same-gameweek outcomes are labels only.

Bookmaker prices are independent evidence rather than a replacement forecast. De-vigged Betfair
Match Odds and over/under 2.5 prices are converted into team scoring and clean-sheet priors. The
historical legal-policy gate currently permits a 20% preseason blend for defenders only. It gives
zero weekly transfer authority until its continuous weekly replay passes.

## Independent football-stat feeds

Understat EPL snapshots from 2014/15 through 2025/26 are immutable and checksum-bound. For a target
season, the challenger may use only the previous completed season's npxG, xA, shots, key passes,
xGChain and xGBuildup. Exact full, known or web names are mapped; ambiguous matches fail closed.

The first time-forward challenger completed forecast tests, continuous legal transfer replays and
an untouched 2025/26 test. Its development selector chose a 0% blend, so Understat currently remains
shadow evidence. This is still useful: it gives an independent diagnostic and a reproducible route
to re-test as new seasons arrive. It is not forced into production merely because the source is
respected.

FBref's automated page returned HTTP 403 during this research run. FPLAgent does not bypass that
response, count it as a provider or substitute an undocumented scraper. A permitted second source
with a point-in-time archive remains a research-frontier gate.

SofaScore was subsequently tested as that second historical event source. Its bounded challenger
slightly improved frozen player MAE but lost 15 realised points in the untouched 2025/26 legal
policy replay, so its production weight is zero. Cloudflare or another access failure is therefore
not a reason to add browser-evasion infrastructure: the source has not earned decision authority.

These event sources are distinct from predicted lineups. Understat and FBref describe realised
performance; neither supplies a dependable next-match XI. The separate participation layer uses
deadline-bound Fantasy Football Scout and RotoWire captures, but remains at zero weight until its
prospective lineup and legal-policy gate passes.

## Promotion rule

Any new data source must:

1. have an immutable observation timestamp and checksum;
2. map players and teams deterministically, with coverage and ambiguity reported;
3. be available under the same information constraints during historical replay;
4. improve season-forward player ranking or calibration;
5. improve legal squad/transfer decisions on development seasons and an untouched season; and
6. receive a bounded initial weight recorded in a machine-readable receipt.

A failed gate leaves the current forecast unchanged.
