from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.paths import PROCESSED

from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

SEASON_DIR = PROCESSED / "fpl" / "2026-27" / "preseason"
OUTPUT_DIR = MODEL_DATA / "rules_audit_v1"
RESULTS_JSON = OUTPUT_DIR / "2026-27.json"
REPORT = REPORTS / "2026-27-rules-audit.md"

SOURCES = {
    "official_changes": (
        "https://www.premierleague.com/en/news/4679873/"
        "all-you-need-to-know-about-changes-to-fpl-for-202627"
    ),
    "official_chips": (
        "https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627"
    ),
    "official_bps": (
        "https://www.premierleague.com/en/news/4679946/"
        "whats-new-in-202627-fantasy-changes-to-bonus-points-system"
    ),
    "official_defensive_contributions": (
        "https://www.premierleague.com/en/news/4361991/"
        "whats-happening-with-defensive-contribution-points-in-202627-fantasy"
    ),
    "official_positions": (
        "https://www.premierleague.com/en/news/4679886/"
        "position-changes-for-202627-fantasy-premier-league/"
    ),
    "official_price_predictor": "https://www.premierleague.com/en/news/4680462",
    "official_help": "https://fantasy.premierleague.com/help/",
}

POSITION_CHANGES = [
    {"player": "Myles Lewis-Skelly", "old": "DEF", "new": "MID"},
    {"player": "Lamare Bogarde", "old": "DEF", "new": "MID"},
    {"player": "Junior Kroupi", "old": "FWD", "new": "MID"},
    {"player": "Keane Lewis-Potter", "old": "DEF", "new": "MID"},
    {"player": "Mats Wieffer", "old": "MID", "new": "DEF"},
    {"player": "Georginio Rutter", "old": "MID", "new": "FWD"},
    {"player": "Rio Cardines", "old": "MID", "new": "DEF"},
    {"player": "Ryan Sessegnon", "old": "MID", "new": "DEF"},
    {"player": "Omar Marmoush", "old": "MID", "new": "FWD"},
    {"player": "Patrick Dorgu", "old": "DEF", "new": "MID"},
    {"player": "Eric Moreira", "old": "MID", "new": "DEF"},
]


def _rule_matrix() -> list[dict[str, str]]:
    return [
        {
            "area": "Squad and formation",
            "official_rule": "£100m; 15 players; 2/5/5/3; max three per club; legal XI 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD.",
            "bootstrap": "Captured in rules and positions.",
            "engine": "Captured and validated.",
            "status": "captured",
            "action": "Keep live snapshot validation.",
        },
        {
            "area": "Free transfers",
            "official_rule": "One new FT per Gameweek, bank up to five; additional transfers cost four points.",
            "bootstrap": "Five-transfer cap and transfer cap captured; hit cost is prose/scoring behaviour.",
            "engine": "Immutable weekly transitions roll to five and charge exactly four points per transfer beyond the available bank.",
            "status": "captured",
            "action": "Generate and compare roll, free-transfer and paid-transfer bundles in the weekly optimiser.",
        },
        {
            "area": "Wildcard and Free Hit transfer bank",
            "official_rule": "Previously saved FTs survive; activating the chip uses that Gameweek's newly granted FT.",
            "bootstrap": "Not encoded by chip rows.",
            "engine": "Wildcard and Free Hit preserve the entering transfer bank while preventing a new transfer from being banked.",
            "status": "captured",
            "action": "Cover these transitions in policy-route replay as well as unit tests.",
        },
        {
            "area": "Chip inventory",
            "official_rule": "Wildcard, Free Hit, Bench Boost and Triple Captain once in each half: eight chips total.",
            "bootstrap": "Eight rows correctly encode GW1/2–19 and GW20–38 windows.",
            "engine": "Eight immutable chip slots are represented and consumed by legal weekly actions. Bench Boost and Triple Captain run as exact shared-world variants. Wildcard searches a permanent multi-week squad; Free Hit searches the current event and restores the original squad later. Separate continuous WC/FH and BB/TC retention replays are frozen and both rejected their downside gates. All remain shadow-only.",
            "status": "partial",
            "action": "Improve the rejected retained-timing policies, replay all four chip types jointly and pass prospective validation before granting authority.",
        },
        {
            "area": "Chip expiry/reset",
            "official_rule": "First set expires at the GW19 deadline and cannot carry; second set becomes available GW20.",
            "bootstrap": "Start/stop events captured.",
            "engine": "Unused first-half slots expire and the second set unlocks at GW20. Team-chip shadow routes compare current simulated uplift with the best visible opportunity before expiry and fail closed when the half-season horizon is incomplete. Historical replays apply the same two-half inventory counterfactually and never promote rejected thresholds.",
            "status": "partial",
            "action": "Calibrate beyond-horizon opportunity value and validate chip gates in historical and prospective replay.",
        },
        {
            "area": "Free Hit restrictions",
            "official_rule": "Unavailable in GW1 and cannot be played in consecutive Gameweeks, including GW19→20.",
            "bootstrap": "GW1 exclusion captured; consecutive-use restriction is not.",
            "engine": "GW1 and consecutive-GW Free Hits, including GW19→20, are rejected by the weekly state transition.",
            "status": "captured",
            "action": "Keep golden transition tests when rules change.",
        },
        {
            "area": "One chip per Gameweek",
            "official_rule": "Only one chip may be active in a Gameweek.",
            "bootstrap": "Not explicit in individual chip rows.",
            "engine": "A weekly action has at most one typed chip and consumes exactly one matching half-season slot.",
            "status": "captured",
            "action": "Keep chip variants mutually exclusive in action generation.",
        },
        {
            "area": "Assistant Manager chip",
            "official_rule": "Not part of 2026/27; the current game has only the four named chip types.",
            "bootstrap": "Absent, consistently with the official 2026/27 list.",
            "engine": "No Assistant Manager action.",
            "status": "captured",
            "action": "Keep an explicit absence assertion so a future return is detected.",
        },
        {
            "area": "Defensive contributions",
            "official_rule": "Two points, capped per match: DEF at 10 CBIT; MID/FWD at 12 CBIRT.",
            "bootstrap": "Point value captured; thresholds are not present in the normalized rules row.",
            "engine": "Thresholds and empirical occurrence model captured from 2025/26.",
            "status": "captured",
            "action": "Recalibrate continuously; only one completed season exists.",
        },
        {
            "area": "2026/27 Bonus Points System",
            "official_rule": "No tackled penalty; one BPS per three CBI; revised GK save and big-chance-save BPS; penalty-save BPS becomes seven.",
            "bootstrap": "Not encoded in scoring_json.",
            "engine": "Historical tie allocation and the CBI delta are exact. The removed tackled penalty is modelled and the shrunk outfield correction prior beats no-correction and position-only baselines on an external 537-player reconstruction. Goalkeeper save context and the live match allocator remain approximate.",
            "status": "partial",
            "action": "Retain the validated outfield prior, keep goalkeeper correction neutral, and require complete reliable event context plus forward replay before claiming an exact current-rule allocator.",
        },
        {
            "area": "Position reclassifications",
            "official_rule": "Eleven named players changed FPL position for 2026/27.",
            "bootstrap": "Current positions captured on every player.",
            "engine": "Captured through current position IDs and position-specific scoring.",
            "status": "captured",
            "action": "Never carry historical position labels into the live optimiser.",
        },
        {
            "area": "Price changes",
            "official_rule": "Daily at 00:00 UK after GW1; official predictor refreshes every 15 minutes and remains probabilistic.",
            "bootstrap": "Current price only; predictor trajectory is not in bootstrap.",
            "engine": "Purchase, current and exact selling prices plus half-profit rounding are represented; future predictor scenarios are missing.",
            "status": "partial",
            "action": "Ingest predictor state and value early moves against information and injury risk.",
        },
        {
            "area": "Gameweek deadline and final lock",
            "official_rule": "Deadline 90 minutes before first kick-off; results now finalise at 09:00 UK after the last match.",
            "bootstrap": "Deadline timestamp captured; final-lock time is prose-only.",
            "engine": "Deadline-open, locked, live, provisional and final states advance monotonically; automatic 09:00 lock ingestion is missing.",
            "status": "partial",
            "action": "Mark live scores provisional and delay training labels/receipts until final lock.",
        },
        {
            "area": "Autosubs and captain fallback",
            "official_rule": "Zero-minute starters autosub in bench order subject to legal formation; captain passes to vice only on zero minutes.",
            "bootstrap": "Not completely encoded.",
            "engine": "Exact in tournament simulation; optimizer uses a flat 8% bench search proxy.",
            "status": "partial",
            "action": "Replace the flat proxy with appearance-scenario optimisation or zero-proxy candidate generation.",
        },
        {
            "area": "Blank/double fixture scoring",
            "official_rule": "A Gameweek can contain zero, one or multiple fixtures for a club; match-scoped points and thresholds are awarded separately in each fixture.",
            "bootstrap": "Fixture event, kickoff and provisional-start fields expose the currently assigned official schedule; postponed matches can remain unassigned.",
            "engine": "A content-addressed receipt classifies confirmed, provisional and unassigned fixtures without speculative placement. Component outcomes are scored per match then aggregated, with event-level appearance probability preserved and historical double-gameweek rotation calibrated. Exact chip searches consume those event worlds; a pre-deadline opportunity ledger and correlated rearrangement Monte Carlo shadow are frozen. The rearrangement evidence gate and both retained-chip replay gates currently reject authority.",
            "status": "partial",
            "action": "Accumulate at least 20 independent rearrangement batches across three seasons, improve retained timing and validate jointly/prospectively; keep unresolved schedules as a chip-gate failure.",
        },
        {
            "area": "No AFCON transfer top-up",
            "official_rule": "The special December five-FT top-up from 2025/26 will not occur in 2026/27.",
            "bootstrap": "No scheduled top-up row.",
            "engine": "Normal transfer recurrence only.",
            "status": "captured",
            "action": "Do not import last season's exceptional transition.",
        },
    ]


def audit_2026_27_rules() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rules = pq.read_table(SEASON_DIR / "rules.parquet").to_pylist()[0]
    chips = pq.read_table(SEASON_DIR / "chips.parquet").to_pylist()
    positions = pq.read_table(SEASON_DIR / "positions.parquet").to_pylist()
    events = pq.read_table(SEASON_DIR / "events.parquet").to_pylist()
    scoring = json.loads(rules["scoring_json"])

    chip_names = [str(row["name"]) for row in chips]
    assertions = {
        "eight_chip_rows": len(chips) == 8,
        "four_chip_types": set(chip_names) == {"wildcard", "freehit", "bboost", "3xc"},
        "assistant_manager_absent": not any("manager" in name for name in chip_names),
        "first_half_ends_gw19": all(
            int(row["stop_event"]) == 19 for row in chips if int(row["start_event"]) < 20
        ),
        "second_half_starts_gw20": all(
            int(row["start_event"]) == 20 for row in chips if int(row["stop_event"]) == 38
        ),
        "five_free_transfer_bank": int(rules["max_bankable_free_transfers"]) == 5,
        "defensive_contribution_two_points": scoring["defensive_contribution"]
        == {"DEF": 2, "FWD": 2, "GKP": 0, "MID": 2},
        "legal_position_shape": {
            str(row["singular_name_short"]): (
                int(row["squad_select"]),
                int(row["squad_min_play"]),
                int(row["squad_max_play"]),
            )
            for row in positions
        }
        == {"GKP": (2, 1, 1), "DEF": (5, 3, 5), "MID": (5, 2, 5), "FWD": (3, 1, 3)},
    }
    if not all(assertions.values()):
        raise ValueError(f"Live 2026/27 rule assertions failed: {assertions}")

    matrix = _rule_matrix()
    status_counts: dict[str, int] = {}
    for row in matrix:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "authority_order": [
            "Official 2026/27 Premier League/FPL prose",
            "Live FPL bootstrap and Help data",
            "FPLAgent implementation",
        ],
        "snapshot_at": rules["snapshot_at"],
        "assertions": assertions,
        "sources": SOURCES,
        "bootstrap": {
            "budget": float(rules["budget_tenths"]) / 10.0,
            "squad_size": int(rules["squad_size"]),
            "starting_size": int(rules["starting_size"]),
            "club_limit": int(rules["club_player_limit"]),
            "max_bankable_free_transfers": int(rules["max_bankable_free_transfers"]),
            "chip_rows": [
                {
                    "name": row["name"],
                    "start_event": int(row["start_event"]),
                    "stop_event": int(row["stop_event"]),
                }
                for row in chips
            ],
            "gw1_deadline": next(row["deadline_time"] for row in events if row["id"] == 1),
        },
        "position_changes": POSITION_CHANGES,
        "matrix": matrix,
        "status_counts": status_counts,
        "blocking_before_weekly_agent": [
            "Exercise the authenticated manager-state contract on the first complete post-GW1 response.",
            "Improve the historically rejected Bench Boost and Triple Captain retention policy, then validate it jointly and prospectively.",
            "Improve the historically rejected Wildcard and Free Hit retention policy, then validate it jointly and prospectively.",
            "Prospectively calibrate the ingested price threshold and move-now-versus-wait net-points policy.",
            "Aggregate frozen prospective receipts before allowing any forecast or policy promotion.",
        ],
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# FPL 2026/27 rulebook audit",
        "",
        f"**Audited:** {result['created_at']}",
        f"**Live snapshot:** {result['snapshot_at']}",
        "**Verdict:** the initial-squad legality layer is current, but the engine is not yet a complete weekly decision agent.",
        "",
        "## Confirmed 2026/27 state",
        "",
        "- £100.0m buys 15 players in a 2 GK / 5 DEF / 5 MID / 3 FWD squad, with at most three per club.",
        "- Free transfers roll to five. Additional transfers cost four points.",
        "- There are eight chips: Wildcard, Free Hit, Bench Boost and Triple Captain once in GW1/2–19 and once in GW20–38.",
        "- There is **no Assistant Manager chip** in 2026/27.",
        "- Defensive-contribution points remain: two points at 10 CBIT for defenders or 12 CBIRT for midfielders/forwards, capped once per match.",
        "- The Bonus Points System changed for 2026/27 and needs an updated simulator.",
        "- Eleven players have new position classifications; live player position IDs are authoritative.",
        "- The official Price Change Predictor refreshes every 15 minutes; actual price changes occur at 00:00 UK time after GW1.",
        "- Gameweek scores remain provisional until the new 09:00 UK lock on the morning after the final match.",
        "",
        "## Bootstrap-versus-rulebook matrix",
        "",
        "| Area | Status | Official rule | Bootstrap | Current engine | Required action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["matrix"]:
        lines.append(
            f"| {row['area']} | **{row['status']}** | {row['official_rule']} | "
            f"{row['bootstrap']} | {row['engine']} | {row['action']} |"
        )
    lines.extend(
        [
            "",
            "## Blocking work before weekly automation",
            "",
            *[
                f"{index}. {item}"
                for index, item in enumerate(result["blocking_before_weekly_agent"], 1)
            ],
            "",
            "## Important prose-only constraints",
            "",
            "- Only one chip can be active in a Gameweek.",
            "- Free Hit and Wildcard are unavailable for the opening Gameweek; Bench Boost and Triple Captain are available.",
            "- Free Hits cannot be used in consecutive Gameweeks, including across the GW19/GW20 refresh.",
            "- First-half chips expire after GW19; unused chips do not carry.",
            "- Previously banked transfers survive a Wildcard or Free Hit, but the transfer newly granted for the chip Gameweek is consumed by activation.",
            "- Triple Captain passes to the vice-captain only if the captain plays zero minutes; it is lost if both play zero and is not returned.",
            "- A Free Hit restores the prior squad and bank at the following deadline, with intervening price changes reflected; temporary bank changes are lost.",
            "- The exceptional AFCON transfer top-up used in 2025/26 does not recur in 2026/27.",
            "",
            "## 2026/27 BPS changes the model must reproduce",
            "",
            "- Remove the old -1 BPS penalty each time a player is tackled.",
            "- Award one BPS per three clearances, blocks and interceptions, rather than per two.",
            "- Goalkeepers receive two BPS for any save, plus one for an inside-box save and one for a big-chance save.",
            "- Penalty-save BPS becomes seven; the new big-chance-save addition restores one BPS for that event.",
            "",
            "These changes can move bonus probability from centre-backs toward goalkeepers, full-backs and attackers. That directly affects the current five-defender question.",
            "",
            "## Sources",
            "",
            *[f"- {name}: {url}" for name, url in result["sources"].items()],
            "",
        ]
    )
    return "\n".join(lines)
