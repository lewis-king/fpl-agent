# FPL 2026/27 rulebook audit

**Audited:** 2026-08-15T16:15:43.111619+00:00
**Live snapshot:** 2026-08-15T10:35:12.446572+00:00
**Verdict:** the initial-squad legality layer is current, but the engine is not yet a complete weekly decision agent.

## Confirmed 2026/27 state

- £100.0m buys 15 players in a 2 GK / 5 DEF / 5 MID / 3 FWD squad, with at most three per club.
- Free transfers roll to five. Additional transfers cost four points.
- There are eight chips: Wildcard, Free Hit, Bench Boost and Triple Captain once in GW1/2–19 and once in GW20–38.
- There is **no Assistant Manager chip** in 2026/27.
- Defensive-contribution points remain: two points at 10 CBIT for defenders or 12 CBIRT for midfielders/forwards, capped once per match.
- The Bonus Points System changed for 2026/27 and needs an updated simulator.
- Eleven players have new position classifications; live player position IDs are authoritative.
- The official Price Change Predictor refreshes every 15 minutes; actual price changes occur at 00:00 UK time after GW1.
- Gameweek scores remain provisional until the new 09:00 UK lock on the morning after the final match.

## Bootstrap-versus-rulebook matrix

| Area | Status | Official rule | Bootstrap | Current engine | Required action |
| --- | --- | --- | --- | --- | --- |
| Squad and formation | **captured** | £100m; 15 players; 2/5/5/3; max three per club; legal XI 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD. | Captured in rules and positions. | Captured and validated. | Keep live snapshot validation. |
| Free transfers | **captured** | One new FT per Gameweek, bank up to five; additional transfers cost four points. | Five-transfer cap and transfer cap captured; hit cost is prose/scoring behaviour. | Immutable weekly transitions roll to five and charge exactly four points per transfer beyond the available bank. | Generate and compare roll, free-transfer and paid-transfer bundles in the weekly optimiser. |
| Wildcard and Free Hit transfer bank | **captured** | Previously saved FTs survive; activating the chip uses that Gameweek's newly granted FT. | Not encoded by chip rows. | Wildcard and Free Hit preserve the entering transfer bank while preventing a new transfer from being banked. | Cover these transitions in policy-route replay as well as unit tests. |
| Chip inventory | **partial** | Wildcard, Free Hit, Bench Boost and Triple Captain once in each half: eight chips total. | Eight rows correctly encode GW1/2–19 and GW20–38 windows. | Eight immutable chip slots are represented and consumed by legal weekly actions. Bench Boost and Triple Captain run as exact shared-world variants. Wildcard searches a permanent multi-week squad; Free Hit searches the current event and restores the original squad later. Separate continuous WC/FH and BB/TC retention replays are frozen and both rejected their downside gates. All remain shadow-only. | Improve the rejected retained-timing policies, replay all four chip types jointly and pass prospective validation before granting authority. |
| Chip expiry/reset | **partial** | First set expires at the GW19 deadline and cannot carry; second set becomes available GW20. | Start/stop events captured. | Unused first-half slots expire and the second set unlocks at GW20. Team-chip shadow routes compare current simulated uplift with the best visible opportunity before expiry and fail closed when the half-season horizon is incomplete. Historical replays apply the same two-half inventory counterfactually and never promote rejected thresholds. | Calibrate beyond-horizon opportunity value and validate chip gates in historical and prospective replay. |
| Free Hit restrictions | **captured** | Unavailable in GW1 and cannot be played in consecutive Gameweeks, including GW19→20. | GW1 exclusion captured; consecutive-use restriction is not. | GW1 and consecutive-GW Free Hits, including GW19→20, are rejected by the weekly state transition. | Keep golden transition tests when rules change. |
| One chip per Gameweek | **captured** | Only one chip may be active in a Gameweek. | Not explicit in individual chip rows. | A weekly action has at most one typed chip and consumes exactly one matching half-season slot. | Keep chip variants mutually exclusive in action generation. |
| Assistant Manager chip | **captured** | Not part of 2026/27; the current game has only the four named chip types. | Absent, consistently with the official 2026/27 list. | No Assistant Manager action. | Keep an explicit absence assertion so a future return is detected. |
| Defensive contributions | **captured** | Two points, capped per match: DEF at 10 CBIT; MID/FWD at 12 CBIRT. | Point value captured; thresholds are not present in the normalized rules row. | Thresholds and empirical occurrence model captured from 2025/26. | Recalibrate continuously; only one completed season exists. |
| 2026/27 Bonus Points System | **partial** | No tackled penalty; one BPS per three CBI; revised GK save and big-chance-save BPS; penalty-save BPS becomes seven. | Not encoded in scoring_json. | Historical tie allocation and the CBI delta are exact. The removed tackled penalty is modelled and the shrunk outfield correction prior beats no-correction and position-only baselines on an external 537-player reconstruction. Goalkeeper save context and the live match allocator remain approximate. | Retain the validated outfield prior, keep goalkeeper correction neutral, and require complete reliable event context plus forward replay before claiming an exact current-rule allocator. |
| Position reclassifications | **captured** | Eleven named players changed FPL position for 2026/27. | Current positions captured on every player. | Captured through current position IDs and position-specific scoring. | Never carry historical position labels into the live optimiser. |
| Price changes | **partial** | Daily at 00:00 UK after GW1; official predictor refreshes every 15 minutes and remains probabilistic. | Current price only; predictor trajectory is not in bootstrap. | Purchase, current and exact selling prices plus half-profit rounding are represented; future predictor scenarios are missing. | Ingest predictor state and value early moves against information and injury risk. |
| Gameweek deadline and final lock | **partial** | Deadline 90 minutes before first kick-off; results now finalise at 09:00 UK after the last match. | Deadline timestamp captured; final-lock time is prose-only. | Deadline-open, locked, live, provisional and final states advance monotonically; automatic 09:00 lock ingestion is missing. | Mark live scores provisional and delay training labels/receipts until final lock. |
| Autosubs and captain fallback | **partial** | Zero-minute starters autosub in bench order subject to legal formation; captain passes to vice only on zero minutes. | Not completely encoded. | Exact in tournament simulation; optimizer uses a flat 8% bench search proxy. | Replace the flat proxy with appearance-scenario optimisation or zero-proxy candidate generation. |
| Blank/double fixture scoring | **partial** | A Gameweek can contain zero, one or multiple fixtures for a club; match-scoped points and thresholds are awarded separately in each fixture. | Fixture event, kickoff and provisional-start fields expose the currently assigned official schedule; postponed matches can remain unassigned. | A content-addressed receipt classifies confirmed, provisional and unassigned fixtures without speculative placement. Component outcomes are scored per match then aggregated, with event-level appearance probability preserved and historical double-gameweek rotation calibrated. Exact chip searches consume those event worlds; a pre-deadline opportunity ledger and correlated rearrangement Monte Carlo shadow are frozen. The rearrangement evidence gate and both retained-chip replay gates currently reject authority. | Accumulate at least 20 independent rearrangement batches across three seasons, improve retained timing and validate jointly/prospectively; keep unresolved schedules as a chip-gate failure. |
| No AFCON transfer top-up | **captured** | The special December five-FT top-up from 2025/26 will not occur in 2026/27. | No scheduled top-up row. | Normal transfer recurrence only. | Do not import last season's exceptional transition. |

## Blocking work before weekly automation

1. Exercise the authenticated manager-state contract on the first complete post-GW1 response.
2. Improve the historically rejected Bench Boost and Triple Captain retention policy, then validate it jointly and prospectively.
3. Improve the historically rejected Wildcard and Free Hit retention policy, then validate it jointly and prospectively.
4. Prospectively calibrate the ingested price threshold and move-now-versus-wait net-points policy.
5. Aggregate frozen prospective receipts before allowing any forecast or policy promotion.

## Important prose-only constraints

- Only one chip can be active in a Gameweek.
- Free Hit and Wildcard are unavailable for the opening Gameweek; Bench Boost and Triple Captain are available.
- Free Hits cannot be used in consecutive Gameweeks, including across the GW19/GW20 refresh.
- First-half chips expire after GW19; unused chips do not carry.
- Previously banked transfers survive a Wildcard or Free Hit, but the transfer newly granted for the chip Gameweek is consumed by activation.
- Triple Captain passes to the vice-captain only if the captain plays zero minutes; it is lost if both play zero and is not returned.
- A Free Hit restores the prior squad and bank at the following deadline, with intervening price changes reflected; temporary bank changes are lost.
- The exceptional AFCON transfer top-up used in 2025/26 does not recur in 2026/27.

## 2026/27 BPS changes the model must reproduce

- Remove the old -1 BPS penalty each time a player is tackled.
- Award one BPS per three clearances, blocks and interceptions, rather than per two.
- Goalkeepers receive two BPS for any save, plus one for an inside-box save and one for a big-chance save.
- Penalty-save BPS becomes seven; the new big-chance-save addition restores one BPS for that event.

These changes can move bonus probability from centre-backs toward goalkeepers, full-backs and attackers. That directly affects the current five-defender question.

## Sources

- official_changes: https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627
- official_chips: https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627
- official_bps: https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system
- official_defensive_contributions: https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy
- official_positions: https://www.premierleague.com/en/news/4679886/position-changes-for-202627-fantasy-premier-league/
- official_price_predictor: https://www.premierleague.com/en/news/4680462
- official_help: https://fantasy.premierleague.com/help/
