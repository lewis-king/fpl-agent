# Participation and predicted-lineup evidence

**Updated:** 15 August 2026
**Production authority:** official FPL status/news plus the historically validated minute model
**Predicted-lineup authority:** prospective shadow, weight `0.0`

Participation is a large source of avoidable FPL error, but it is also where stale pages, copied
predictions and hindsight leakage can most easily create false confidence. FPLAgent therefore keeps
three different claims separate:

1. official FPL availability/status, which is aligned into the production forecast generation;
2. modelled DNP, 1–59, 60–89 and 90+ probabilities, learned only from information available before
   the target event; and
3. public predicted XIs, which can open a deadline review but cannot currently alter xP, the squad,
   transfers, XI or captaincy.

## Current sources and provenance

`fpl-data collect-participation-consensus` captures two independently published, server-rendered
pages:

- Fantasy Football Scout: `https://cdn.fantasyfootballscout.co.uk/team-news`
- RotoWire: `https://www.rotowire.com/soccer/lineups.php?league=EPL`

Every response is archived by SHA-256 under
`data/raw/supporting/participation/2026-27/archive/`. Normalized observations are joined to the
current official FPL team, fixture and player generation using team-scoped conservative aliases.
An incomplete XI, unmatched source player, wrong opponent, wrong event or post-deadline capture
cannot cast a negative vote.

The Fantasy Football Scout page exposes `dateModified`; that source timestamp must be no more than
seven days old. RotoWire does not expose an equivalent update timestamp, so its evidence is marked
`observation_timestamp_only`. A capture timestamp never masquerades as a publisher update time.

The 10 August capture found:

- both pages reachable and all 20 clubs parsed;
- 16 complete, fully matched FFScout XIs and 17 complete RotoWire XIs;
- FFScout's advertised 20 July modification timestamp is stale, so it is archived but ineligible;
- RotoWire is the only currently eligible provider; and
- all 15 players in the active GW1 squad appear in RotoWire's predicted XI.

That final point is useful reassurance, not proof. The UI says `15/15` with `1 of 2` captured
providers eligible and retains production weight zero.

## Normalized contract

The current artifacts are:

- `data/processed/supporting/participation/2026-27/predicted_lineup_observations.parquet`
- `data/processed/supporting/participation/2026-27/participation_consensus.parquet`
- `data/manifests/participation_consensus_current.json`
- immutable event/timestamp snapshots under
  `data/processed/supporting/participation/2026-27/snapshots/`

Each observation records the source and URL, capture and publisher timestamps, event deadline,
official fixture/team IDs, source completeness, source player name, conservative FPL player match,
lineup state and decision eligibility. Each player consensus records positive and negative source
votes, source disagreement, aligned champion `p_play`/`p_start`, official status and an explicit
`production_adjustment_authorized=false`.

If a team has more than one fixture in an event, a team-only prediction is ambiguous and is
excluded. A fixture-specific source can be aligned only when its named opponent identifies exactly
one official fixture. This prevents a normal single-XI page from being misrepresented as coverage
of both legs of a double gameweek.

## Prospective promotion gate

There is no honest point-in-time historical archive of these exact providers with the same parser,
timestamp and update policy. Actual historical lineups are outcomes, not pre-deadline predictions;
training on them would leak the answer. The source consensus must therefore prove itself live.

The existing historical alternatives do not justify an indirect shortcut. Four-class appearance
recalibration was tested on 6,872 candidate rows across the 2024/25 and 2025/26 forward slices; no
position passed all probability, minutes and decision-value gates. A richer leakage-safe rolling
role feature set produced a statistical pass only for goalkeepers, then lost `0.013` points per GW
in the 76-GW exact legal policy replay, with a 95% interval of `[-0.426, +0.400]` and a negative
season floor. Both challengers remain rejected.

`fplagent participation-scoreboard` selects the latest immutable capture made before every
deadline, waits for the official event-live outcome to be final, and scores exact official
`starts`. For every singly-fixtured covered club it compares:

- the production model's top eleven by start probability;
- every independent provider XI; and
- a consensus XI ranked by provider vote share, with champion start probability only as a
  tie-breaker.

The gate requires at least six completed events, two eligible independent providers across at
least ten teams in every qualifying event, positive mean lineup-hit lift, no negative event and a
non-negative 95% lower bound. The same frozen consensus now applies a bounded participation
adjustment to the champion xP and passes both forecasts through the identical legal £100m squad,
XI, bench and captain solver. Positive aggregate legal-policy lift with no negative event is also
required. Passing authorizes a bounded production challenger review; it does not silently promote
the feed.

Before GW1 the scoreboard correctly contains zero completed events and reports
`awaiting_prospective_evidence`.

## Runtime behavior

The GW1 and weekly deadline pipelines recollect the feed after refreshing official data. Source
failure is fail-soft because the layer has zero authority: official evidence and the last validated
decision stay usable. The participation receipt is intentionally excluded from the expensive
decision fingerprint, so an advisory page update does not launch a complete squad tournament.

The availability watch validates predicted-lineup hashes against the exact official players and
forecast generation. Its UI projection can show start support, a two-source bench flag or provider
disagreement. Only official evidence or a separately promoted model can change the production
probabilities.

Useful commands:

```bash
uv run fpl-data collect-participation-consensus --event 1
uv run fplagent availability-status
uv run fplagent participation-scoreboard
```
