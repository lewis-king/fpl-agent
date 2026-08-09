from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import duckdb
import numpy as np
from scipy.stats import spearmanr

from .component_simulator import (
    COMPONENT_BACKTEST_METRICS,
GOAL_METRICS_FILE,
    calibrate_empirical_components,
    predict_current_goal_rates,
    simulate_component_outcomes,
)
from .optimizer import BENCH_AUTOSUB_WEIGHT, POSITION_ORDER, _player_rows, _solve
from .paths import DATA, DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .tournament import (
    DEFAULT_EVENTS,
    _lineup_for_squad,
    _load_rows,
    _policy_candidate,
    _score_candidates,
)

AUDIT_DIR = MODEL_DATA / "bench_audit_v1"
RESULTS_JSON = AUDIT_DIR / "results.json"
REPORT = REPORTS / "bench-and-formation-adversarial-review.md"
DATABASE = DATA / "fpl_history.duckdb"
BPS_METRICS_FILE = MODEL_DATA / "bps_2026_27_v1" / "metrics.json"
RESIDUAL_CANDIDATES = DECISIONS / "2026-27-gw1-candidates.json"
RESIDUAL_RESULTS = MODEL_DATA / "tournament_v1" / "gw1-5-results.json"
COMPONENT_CANDIDATES = DECISIONS / "2026-27-gw1-component-candidates.json"
COMPONENT_RESULTS = MODEL_DATA / "tournament_v2" / "component-gw1-5-results.json"
OFFICIAL_RULES = {
    "2026_27_changes": (
        "https://www.premierleague.com/en/news/4679873/"
        "all-you-need-to-know-about-changes-to-fpl-for-202627"
    ),
    "automatic_substitutions": "https://www.premierleague.com/en/news/2174899/",
    "transfers": "https://www.premierleague.com/en/news/2174907",
    "chips": "https://www.premierleague.com/en/news/4679879/",
}


def _describe(values: list[float]) -> dict[str, float]:
    data = np.asarray(values, dtype=np.float64)
    return {
        "count": int(data.size),
        "mean": float(data.mean()),
        "median": float(np.median(data)),
        "minimum": float(data.min()),
        "maximum": float(data.max()),
        "p10": float(np.quantile(data, 0.10)),
        "p90": float(np.quantile(data, 0.90)),
    }


def _safe_spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 4 or len(set(left)) < 2 or len(set(right)) < 2:
        return None
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def _probability_label(value: float, simulations: int) -> str:
    if value == 0.0:
        return f"0 observed; <{3 / simulations:.3%} 95% upper bound"
    return f"{value:.3%}"


def _historical_evidence() -> dict[str, Any]:
    connection = duckdb.connect(str(DATABASE), read_only=True)
    try:
        initial_rows = connection.execute(
            """
            WITH pick_prices AS (
                SELECT p.team_id, p.player_id, p.position,
                       max(g.value) / 10.0 AS price
                FROM vaastav_top_manager_picks p
                LEFT JOIN vaastav_player_gameweeks g
                  ON p.season = g.season
                 AND p.player_id = g.element
                 AND p.gw = g.GW
                WHERE p.season = '2019-20' AND p.gw = 1
                GROUP BY ALL
            )
            SELECT team_id,
                   sum(price) FILTER (position BETWEEN 12 AND 15) AS bench_spend,
                   sum(price) FILTER (position BETWEEN 12 AND 14) AS outfield_bench_spend
            FROM pick_prices
            GROUP BY team_id
            ORDER BY team_id
            """
        ).fetchall()
        initial_bench = {
            int(row[0]): {"bench_spend": float(row[1]), "outfield_bench_spend": float(row[2])}
            for row in initial_rows
        }
        ranks = {
            int(entry): int(rank)
            for entry, rank in connection.execute(
                """SELECT entry, rank FROM vaastav_top_manager_summary
                   WHERE season = '2019-20'"""
            ).fetchall()
        }
        initial_players = connection.execute(
            """
            SELECT p.team_id, p.player_id, p.second_name, p.position,
                   max(g.value) / 10.0 AS price,
                   max(pl.element_type) AS element_type
            FROM vaastav_top_manager_picks p
            LEFT JOIN vaastav_player_gameweeks g
              ON p.season = g.season AND p.player_id = g.element AND p.gw = g.GW
            LEFT JOIN vaastav_players pl
              ON p.season = pl.season AND p.player_id = pl.id
            WHERE p.season = '2019-20' AND p.gw = 1 AND p.position BETWEEN 12 AND 15
            GROUP BY ALL
            ORDER BY p.team_id, p.position
            """
        ).fetchall()
        later_picks = connection.execute(
            """
            SELECT team_id, player_id, gw, position
            FROM vaastav_top_manager_picks
            WHERE season = '2019-20' AND gw BETWEEN 2 AND 5
            """
        ).fetchall()
        later_by_player: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for team_id, player_id, event, position in later_picks:
            later_by_player[(int(team_id), int(player_id))].append((int(event), int(position)))
        player_usage = []
        for team_id, player_id, name, position, price, element_type in initial_players:
            follow = later_by_player.get((int(team_id), int(player_id)), [])
            starts = [event for event, later_position in follow if later_position <= 11]
            player_usage.append(
                {
                    "manager": int(team_id),
                    "rank": ranks[int(team_id)],
                    "player": str(name),
                    "initial_bench_position": int(position),
                    "role": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(
                        int(element_type), "unknown"
                    ),
                    "price": float(price),
                    "retained_events_2_5": len(follow),
                    "starter_events_2_5": starts,
                }
            )
        manager_bench_points = {
            int(team_id): {int(event): int(points) for event, points in values}
            for team_id, values in _group_pairs(
                connection.execute(
                    """
                    SELECT team_id, gw, bench
                    FROM vaastav_top_manager_gameweeks
                    WHERE season = '2019-20'
                    ORDER BY team_id, gw
                    """
                ).fetchall()
            ).items()
        }
        formation_rows = connection.execute(
            """
            WITH roles AS (
                SELECT p.team_id, p.gw,
                    sum(CASE WHEN p.position <= 11 AND pl.element_type = 2 THEN 1 ELSE 0 END) AS d,
                    sum(CASE WHEN p.position <= 11 AND pl.element_type = 3 THEN 1 ELSE 0 END) AS m,
                    sum(CASE WHEN p.position <= 11 AND pl.element_type = 4 THEN 1 ELSE 0 END) AS f
                FROM vaastav_top_manager_picks p
                JOIN vaastav_players pl
                  ON p.season = pl.season AND p.player_id = pl.id
                WHERE p.season = '2019-20'
                GROUP BY p.team_id, p.gw
            )
            SELECT r.team_id, r.gw, r.d, r.m, r.f, g.points
            FROM roles r
            JOIN vaastav_top_manager_gameweeks g USING (team_id, gw)
            ORDER BY r.team_id, r.gw
            """
        ).fetchall()
        paul_records = [
            json.loads(value)
            for (value,) in connection.execute(
                "SELECT record_json FROM supporting_paul_top50 ORDER BY overall_rank"
            ).fetchall()
        ]
        genius_managers = connection.execute(
            """SELECT manager_id, overall_rank FROM fpl_genius_managers
               WHERE season = '2025-26'"""
        ).fetchall()
        genius_bench_rows = connection.execute(
            """SELECT manager_id, event, realised_json FROM fpl_genius_receipts
               WHERE season = '2025-26' AND decision_type = 'bench'"""
        ).fetchall()
        titan_rows = connection.execute(
            """SELECT manager, gw, pb, "or" FROM supporting_titan_managers
               WHERE season = '2022-23'"""
        ).fetchall()
        soong_rows = connection.execute(
            """SELECT manager_id, event, bench_points, overall_rank
               FROM supporting_soong_manager_gameweeks WHERE season = '2025-26'"""
        ).fetchall()
    finally:
        connection.close()

    initial_spend = [row["bench_spend"] for row in initial_bench.values()]
    initial_outfield = [row["outfield_bench_spend"] for row in initial_bench.values()]
    start_events = sum(len(row["starter_events_2_5"]) for row in player_usage)
    started_players = sum(bool(row["starter_events_2_5"]) for row in player_usage)
    retained_player_events = sum(row["retained_events_2_5"] for row in player_usage)
    early_bench_points = [
        sum(points.get(event, 0) for event in range(1, 6))
        for points in manager_bench_points.values()
    ]
    season_bench_points = [sum(points.values()) for points in manager_bench_points.values()]

    formation_counts = Counter()
    formation_points: dict[str, list[int]] = defaultdict(list)
    first_five_counts = Counter()
    for _, event, defenders, midfielders, forwards, points in formation_rows:
        formation = f"{defenders}-{midfielders}-{forwards}"
        formation_counts[formation] += 1
        formation_points[formation].append(int(points))
        if int(event) <= 5:
            first_five_counts[formation] += 1
    formation_summary = [
        {
            "formation": formation,
            "uses": count,
            "share": count / len(formation_rows),
            "mean_points": float(np.mean(formation_points[formation])),
            "first_five_uses": first_five_counts[formation],
            "first_five_share": first_five_counts[formation] / 50.0,
        }
        for formation, count in formation_counts.most_common()
    ]

    paul_keys = {
        "3-4-3": ("3_4_3", "343_avg"),
        "3-5-2": ("3_5_2", "352_avg"),
        "4-3-3": ("4_3_3", "433_avg"),
        "4-4-2": ("4_4_2", "442_avg"),
        "4-5-1": ("4_5_1", "451_avg"),
        "5-4-1": ("5_4_1", "541_avg"),
        "5-2-3": ("5_2_3", "523_avg"),
        "5-3-2": ("5_3_2", "532_Avg"),
    }
    paul_formations = []
    for formation, (count_key, average_key) in paul_keys.items():
        uses = sum(int(row.get(count_key, 0) or 0) for row in paul_records)
        weighted_points = sum(
            int(row.get(count_key, 0) or 0) * float(row.get(average_key, 0) or 0)
            for row in paul_records
        )
        paul_formations.append(
            {
                "formation": formation,
                "uses": uses,
                "share_of_legal_formation_records": uses
                / max(sum(int(row.get(key, 0) or 0) for row in paul_records for key, _ in paul_keys.values()), 1),
                "weighted_mean_points": weighted_points / uses if uses else None,
            }
        )
    paul_five_defender_share = sum(
        row["uses"] for row in paul_formations if row["formation"].startswith("5-")
    ) / sum(row["uses"] for row in paul_formations)
    paul_rank = [float(row["Overall_Rank"]) for row in paul_records]
    paul_five_share = [
        sum(int(row.get(key, 0) or 0) for key in ("5_4_1", "5_2_3", "5_3_2"))
        / max(
            sum(int(row.get(key, 0) or 0) for key, _ in paul_keys.values()),
            1,
        )
        for row in paul_records
    ]

    genius_points = {int(manager): 0.0 for manager, _ in genius_managers}
    genius_early = {int(manager): 0.0 for manager, _ in genius_managers}
    genius_rank = {int(manager): int(rank) for manager, rank in genius_managers}
    for manager, event, realised in genius_bench_rows:
        points = max(0.0, -float(json.loads(realised).get("edge", 0.0)))
        genius_points[int(manager)] += points
        if int(event) <= 5:
            genius_early[int(manager)] += points

    titan = _manager_bench_summary(titan_rows, manager_index=0, event_index=1, points_index=2, rank_index=3)
    soong = _manager_bench_summary(soong_rows, manager_index=0, event_index=1, points_index=2, rank_index=3)
    return {
        "limitations": [
            "Initial squad prices and subsequent picks are fully reconstructable only for the 2019/20 eventual top ten.",
            "All manager samples are selected after outcomes, so they describe successful routes but do not identify a causal bench-spend optimum.",
            "The 2019/20 formation evidence predates defensive-contribution scoring; the 2025/26 top-100 data contain bench outcomes but not weekly formations or prices.",
            "Bench points mix squad depth, lineup mistakes, autosub outcomes, and Bench Boost use; lower is not automatically better.",
        ],
        "top10_2019_20": {
            "managers": 10,
            "manager_weeks": len(formation_rows),
            "initial_total_bench_spend": _describe(initial_spend),
            "initial_outfield_bench_spend": _describe(initial_outfield),
            "initial_bench_players": len(player_usage),
            "initial_bench_players_started_in_gw2_5": started_players,
            "initial_bench_player_start_events_gw2_5": start_events,
            "initial_bench_player_start_rate_per_possible_event": start_events
            / (len(player_usage) * 4),
            "initial_bench_player_retention_rate_per_possible_event": retained_player_events
            / (len(player_usage) * 4),
            "bench_points_gw1_5": _describe(early_bench_points),
            "bench_points_full_season": _describe(season_bench_points),
            "formations": formation_summary,
            "five_defender_share": sum(
                row["share"] for row in formation_summary if row["formation"].startswith("5-")
            ),
            "five_defender_first_five_share": sum(
                row["first_five_share"]
                for row in formation_summary
                if row["formation"].startswith("5-")
            ),
            "initial_player_usage": player_usage,
        },
        "top50_2019_20": {
            "managers": 50,
            "formations": sorted(paul_formations, key=lambda row: row["uses"], reverse=True),
            "five_defender_share": paul_five_defender_share,
            "five_defender_share_rank_spearman": _safe_spearman(paul_five_share, paul_rank),
            "bench_points_full_season": _describe(
                [float(row["Bench Points"]) for row in paul_records]
            ),
            "excluded_non_legal_5_3_3_records": sum(
                int(row.get("5_3_3", 0) or 0) for row in paul_records
            ),
        },
        "top100_2025_26": {
            "managers": len(genius_managers),
            "bench_points_gw1_5": _describe(list(genius_early.values())),
            "bench_points_full_season": _describe(list(genius_points.values())),
            "bench_points_rank_spearman": _safe_spearman(
                list(genius_points.values()),
                [float(genius_rank[manager]) for manager in genius_points],
            ),
            "receipt_contract": "Missing bench receipts are treated as zero stranded points.",
        },
        "supporting_samples": {
            "titan_2022_23": titan,
            "soong_2025_26": soong,
        },
    }


def _group_pairs(rows: list[tuple]) -> dict[int, list[tuple[int, int]]]:
    output: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for manager, event, value in rows:
        output[int(manager)].append((int(event), int(value)))
    return output


def _manager_bench_summary(
    rows: list[tuple], *, manager_index: int, event_index: int, points_index: int, rank_index: int
) -> dict[str, Any]:
    by_manager: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
    for row in rows:
        by_manager[str(row[manager_index])].append(
            (int(row[event_index]), float(row[points_index]), int(row[rank_index]))
        )
    early = []
    total = []
    ranks = []
    for values in by_manager.values():
        early.append(sum(points for event, points, _ in values if event <= 5))
        total.append(sum(points for _, points, _ in values))
        ranks.append(max(values, key=lambda item: item[0])[2])
    return {
        "managers": len(by_manager),
        "bench_points_gw1_5": _describe(early),
        "bench_points_full_season": _describe(total),
        "bench_points_rank_spearman": _safe_spearman(total, [float(value) for value in ranks]),
    }


def _solution_candidate(
    candidate_id: str,
    archetype: str,
    solution: dict[str, Any],
    events: tuple[int, ...],
) -> dict[str, Any]:
    selected = list(solution["selected"])
    meta = solution["player_meta"]
    first_lineup = solution["lineups"][events[0]]
    bench = [int(value) for value in first_lineup["bench_order"]]
    return {
        "candidate_id": candidate_id,
        "archetype": archetype,
        "selected": selected,
        "planned_squads": {
            str(event): list(solution["planned_squads"][event]) for event in events
        },
        "lineups": {str(event): dict(solution["lineups"][event]) for event in events},
        "budget_spent": float(solution["budget"]) / 10.0,
        "bank": (load_rules().budget - float(solution["budget"])) / 10.0,
        "gw1_bench_spend": sum(float(meta[element]["market_price"]) for element in bench) / 10.0,
        "gw1_outfield_bench_spend": sum(
            float(meta[element]["market_price"])
            for element in bench
            if meta[element]["position"] != "GK"
        )
        / 10.0,
        "objective": float(solution["objective"]),
        "transfer_count_gw2_5": sum(
            plan["used"] for event, plan in solution["transfers"].items() if event <= 5
        ),
        "players": [
            {
                "element": element,
                "name": meta[element]["player_name"],
                "team": meta[element]["team_short_name"],
                "position": meta[element]["position"],
                "price": float(meta[element]["market_price"]) / 10.0,
            }
            for element in sorted(
                selected,
                key=lambda item: (POSITION_ORDER[meta[item]["position"]], -meta[item]["market_price"]),
            )
        ],
    }


def _fixed_candidate(
    candidate_id: str,
    archetype: str,
    selected: list[int],
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    events: tuple[int, ...],
    *,
    lock_gw1_xi: bool,
) -> dict[str, Any]:
    rules = load_rules()
    best_lineups = {
        event: _lineup_for_squad(selected, event, by_player, rules) for event in events
    }
    if lock_gw1_xi:
        locked_starters = list(best_lineups[events[0]]["starters"])
        lineups = {}
        for event in events:
            captain = max(
                locked_starters,
                key=lambda element: (
                    float(by_player[element][event]["expected_points"]),
                    float(by_player[element][event]["p_play"]),
                ),
            )
            vice = max(
                (element for element in locked_starters if element != captain),
                key=lambda element: (
                    float(by_player[element][event]["expected_points"]),
                    float(by_player[element][event]["p_play"]),
                ),
            )
            remaining = [element for element in selected if element not in locked_starters]
            outfield = sorted(
                (element for element in remaining if meta[element]["position"] != "GK"),
                key=lambda element: (
                    float(by_player[element][event]["expected_points"]),
                    float(by_player[element][event]["p_play"]),
                ),
                reverse=True,
            )
            reserve_gk = [element for element in remaining if meta[element]["position"] == "GK"]
            lineups[event] = {
                "starters": list(locked_starters),
                "captain": captain,
                "vice_captain": vice,
                "bench_order": outfield + reserve_gk,
                "formation": best_lineups[events[0]]["formation"],
                "expected_points": sum(
                    float(by_player[element][event]["expected_points"])
                    for element in locked_starters
                )
                + float(by_player[captain][event]["expected_points"]),
            }
    else:
        lineups = best_lineups
    bench = lineups[events[0]]["bench_order"]
    spend = sum(float(meta[element]["market_price"]) for element in selected)
    return {
        "candidate_id": candidate_id,
        "archetype": archetype,
        "selected": list(selected),
        "lineups": {str(event): lineups[event] for event in events},
        "budget_spent": spend / 10.0,
        "bank": (rules.budget - spend) / 10.0,
        "gw1_bench_spend": sum(float(meta[element]["market_price"]) for element in bench) / 10.0,
        "gw1_outfield_bench_spend": sum(
            float(meta[element]["market_price"])
            for element in bench
            if meta[element]["position"] != "GK"
        )
        / 10.0,
        "transfer_count_gw2_5": 0,
        "players": [
            {
                "element": element,
                "name": meta[element]["player_name"],
                "team": meta[element]["team_short_name"],
                "position": meta[element]["position"],
                "price": float(meta[element]["market_price"]) / 10.0,
            }
            for element in selected
        ],
    }


def _score_without_autosubs(
    candidates: list[dict[str, Any]],
    player_ids: list[int],
    events: tuple[int, ...],
    points: np.ndarray,
    played: np.ndarray,
) -> np.ndarray:
    global_index = {element: index for index, element in enumerate(player_ids)}
    scores = np.zeros((points.shape[0], len(candidates), len(events)), dtype=np.int16)
    for candidate_index, candidate in enumerate(candidates):
        for event_offset, event in enumerate(events):
            lineup = candidate["lineups"][str(event)]
            starters = [global_index[int(element)] for element in lineup["starters"]]
            score = np.sum(
                points[:, event_offset, starters]
                * played[:, event_offset, starters],
                axis=1,
            )
            captain = global_index[int(lineup["captain"])]
            vice = global_index[int(lineup["vice_captain"])]
            score += np.where(
                played[:, event_offset, captain],
                points[:, event_offset, captain],
                np.where(
                    played[:, event_offset, vice],
                    points[:, event_offset, vice],
                    0,
                ),
            )
            scores[:, candidate_index, event_offset] = score
    return scores


def _metric_rows(
    candidates: list[dict[str, Any]], scores: np.ndarray, baseline: int = 0
) -> list[dict[str, Any]]:
    total = scores.sum(axis=2).astype(np.float64)
    primary = total[:, baseline]
    output = []
    for index, candidate in enumerate(candidates):
        values = total[:, index]
        delta = values - primary
        se = float(delta.std(ddof=1) / math.sqrt(len(delta)))
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "archetype": candidate["archetype"],
                "mean_points": float(values.mean()),
                "median_points": float(np.median(values)),
                "p10_points": float(np.quantile(values, 0.10)),
                "p90_points": float(np.quantile(values, 0.90)),
                "mean_delta_to_incumbent": float(delta.mean()),
                "delta_95ci_low": float(delta.mean() - 1.96 * se),
                "delta_95ci_high": float(delta.mean() + 1.96 * se),
                "beat_incumbent_probability": float(np.mean(delta > 0)),
                "tie_incumbent_probability": float(np.mean(delta == 0)),
            }
        )
    return output


def _candidate_table(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for candidate in candidates:
        formation = candidate["lineups"]["1"]["formation"]
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "archetype": candidate["archetype"],
                "formation": formation,
                "budget_spent": candidate["budget_spent"],
                "bank": candidate["bank"],
                "gw1_bench_spend": candidate["gw1_bench_spend"],
                "gw1_outfield_bench_spend": candidate["gw1_outfield_bench_spend"],
                "transfer_count_gw2_5": candidate["transfer_count_gw2_5"],
                "squad": [player["name"] for player in candidate["players"]],
                "gw1_starters": [
                    next(
                        player["name"]
                        for player in candidate["players"]
                        if player["element"] == int(element)
                    )
                    for element in candidate["lineups"]["1"]["starters"]
                ],
                "gw1_bench": [
                    next(
                        player["name"]
                        for player in candidate["players"]
                        if player["element"] == int(element)
                    )
                    for element in candidate["lineups"]["1"]["bench_order"]
                ],
            }
        )
    return output


def _render(result: dict[str, Any]) -> str:
    candidates = {row["candidate_id"]: row for row in result["candidates"]}
    evidence = sorted(
        result["simulation"]["evidence_weighted_metrics"],
        key=lambda row: row["mean_points"],
        reverse=True,
    )
    stress = sorted(
        result["simulation"]["clean_sheet_pessimism_raw_metrics"],
        key=lambda row: row["mean_points"],
        reverse=True,
    )
    history = result["history"]
    current = candidates["B00"]
    bench_usage = result["current_bench_usage"]
    simulations = int(result["simulation"]["simulations"])
    lines = [
        "# Bench spend and five-defender adversarial review",
        "",
        f"**Run:** {result['created_at']}  ",
        (
            f"**Simulations:** {result['simulation']['simulations']:,} base + "
            f"{result['simulation']['stress_simulations']:,} clean-sheet-pessimism paths · "
            f"**Horizon:** GW1–5"
        ),
        "",
        "## Verdict",
        "",
        result["verdict"]["headline"],
        "",
        result["verdict"]["bench"],
        "",
        result["verdict"]["formation"],
        "",
        "## What the £22.5m bench actually is",
        "",
        (
            "The GW1 label is misleading: two expensive outfield substitutes are planned rotation "
            "players. The current optimizer starts a player from the GW1 bench in "
            f"**{bench_usage['planned_start_events_gw2_5']} of 16** possible player-events across "
            "GW2–5. Historical top-ten GW1 substitutes started in only "
            f"**{history['top10_2019_20']['initial_bench_player_start_events_gw2_5']} of 160** "
            "possible player-events."
        ),
        "",
        "| GW1 substitute | Price | Planned starts GW2–5 | Natural no-appearance chance, all five GWs |",
        "| --- | ---: | --- | ---: |",
    ]
    for row in bench_usage["players"]:
        events = ", ".join(f"GW{event}" for event in row["planned_starts"]) or "None"
        lines.append(
            f"| {row['name']} | £{row['price']:.1f}m | {events} | "
            f"{_probability_label(row['probability_no_appearance_all_five'], simulations)} |"
        )
    lines.extend(
        [
            "",
            (
                "Across the paired paths, autosubs add "
                f"**{result['decomposition']['autosub_net_points_gw1_5']:.2f} gross points** over "
                "five weeks for the incumbent, but the best £18.5m-capped route also gets "
                f"**{result['decomposition']['best_lean_autosub_net_points_gw1_5']:.2f}**. The "
                f"marginal autosub-cover difference is therefore only "
                f"**{result['decomposition']['deep_minus_best_lean_autosub_points']:+.2f}**. "
                "Planned XI rotation adds "
                f"**{result['decomposition']['rotation_value_points_gw1_5']:+.2f}**, and the "
                "transfer-aware policy adds "
                f"**{result['decomposition']['transfer_policy_value_points_gw1_5']:+.2f}** versus "
                "holding the same 15 and choosing the best XI. These are paired model estimates, "
                "not additive causal guarantees."
            ),
            "",
            (
                "The original mixed-integer objective also paid every benched player a flat "
                f"**{100 * BENCH_AUTOSUB_WEIGHT:.0f}% of xP**. That is only a search proxy: it does "
                "not know which starter misses out or whether formation allows the autosub. The "
                "component tournament itself uses exact simulated appearances and legal autosubs, "
                "and this audit additionally re-solves the problem with that proxy set to zero."
            ),
            "",
            (
                f"The incumbent plans **{current['transfer_count_gw2_5']} transfers in the four "
                "Gameweeks after GW1**. The present route therefore provides no evidence that the "
                "expensive bench is being bought to bank free transfers; its defensible case is "
                "rotation. The separate transfer-policy uplift must not be credited to bench depth."
            ),
            "",
            "## Exact counterfactuals under the same forecasts",
            "",
            "| Rank | ID | Constraint | GW1 | Bench | Transfers GW2–5 | Mean | Δ B00 | 95% CI | Beat B00 |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
    )
    for rank, row in enumerate(evidence, start=1):
        candidate = candidates[row["candidate_id"]]
        lines.append(
            f"| {rank} | {row['candidate_id']} | {candidate['archetype']} | "
            f"{candidate['formation']} | £{candidate['gw1_bench_spend']:.1f}m | "
            f"{candidate['transfer_count_gw2_5']} | {row['mean_points']:.2f} | "
            f"{row['mean_delta_to_incumbent']:+.2f} | "
            f"[{row['delta_95ci_low']:+.2f}, {row['delta_95ci_high']:+.2f}] | "
            f"{row['beat_incumbent_probability']:.1%} |"
        )
    lines.extend(
        [
            "",
            (
                "B00 is the incumbent 8%-proxy, transfer-aware solve. Z removes the proxy; "
                "Z18/Z20/Z22 also cap the full four-player GW1 bench. F3/F4/F5 force the "
                "GW1 defender count with no proxy; the L suffix also caps the bench at "
                "£18.5m. FIX holds the original 15 but rotates the XI; LOCK holds both the "
                "original 15 and the GW1 XI."
            ),
            "",
            "## Five defenders: historical warning and current-scoring test",
            "",
            (
                f"The 2019/20 eventual top ten used five defenders in "
                f"**{history['top10_2019_20']['five_defender_share']:.1%}** of all manager-weeks and "
                f"**{history['top10_2019_20']['five_defender_first_five_share']:.1%}** of GW1–5 "
                "manager-weeks. The independent top-50 workbook records a "
                f"**{history['top50_2019_20']['five_defender_share']:.1%}** legal five-defender "
                "share. That makes 5-3-2 an unusual prior, not an automatic error."
            ),
            "",
            "| Formation | Top-ten uses | Share | First-five uses | Mean points when used* |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in history["top10_2019_20"]["formations"]:
        lines.append(
            f"| {row['formation']} | {row['uses']} | {row['share']:.1%} | "
            f"{row['first_five_uses']} | {row['mean_points']:.1f} |"
        )
    lines.extend(
        [
            "",
            (
                "*Observational and heavily confounded by the available players, fixtures, "
                "captaincy, chips and game state; it is not a causal formation effect."
            ),
            "",
            (
                "The live component model is more relevant to 2026/27 because it includes "
                "defensive-contribution points. For the incumbent GW1 five, its raw expected "
                "component decomposition is:"
            ),
            "",
            "| Defender | Raw total | Clean sheets | Def. contributions | Goals/assists | Bonus |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result["defender_component_decomposition"]:
        lines.append(
            f"| {row['name']} | {row['raw_total_points']:.2f} | "
            f"{row['clean_sheet_points']:.2f} | {row['defensive_contribution_points']:.2f} | "
            f"{row['goal_assist_points']:.2f} | {row['bonus_points']:.2f} |"
        )
    lines.extend(
        [
            "",
            (
                "The 2026/27 BPS correction is now active for outfield players. Its control "
                f"reproduces **{result['model_validation']['bps_2026_27']['control']['fixtures']} / "
                f"{result['model_validation']['bps_2026_27']['control']['fixtures']}** historical "
                "match allocations exactly; CBI changes are exact and the missing tackled event "
                "proxy achieved a forward player-season rank correlation of "
                f"**{result['model_validation']['bps_2026_27']['tackled_proxy_holdout']['player_season']['model_spearman']:.3f}**. "
                "Goalkeeper BPS deltas remain neutral because full save context is unavailable. "
                "The bonus column above therefore includes the promoted outfield propensity shift "
                "but remains a BPS-inspired match simulation rather than a live Opta event feed."
            ),
            "",
            (
                f"The adversarial fixture scenario inflates both teams’ expected goals by "
                f"**{result['simulation']['goal_rate_stress_multiplier'] - 1:.0%}** in every match, "
                f"moving the mean team clean-sheet probability from "
                f"**{result['simulation']['mean_clean_sheet_probability_base']:.1%}** to "
                f"**{result['simulation']['mean_clean_sheet_probability_stress']:.1%}**. It is "
                "intentionally unanchored so that the original xP cannot undo the stress."
            ),
            "",
            "| Stress rank | ID | GW1 | Bench | Raw stress mean | Δ B00 | 95% CI |",
            "| ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for rank, row in enumerate(stress, start=1):
        candidate = candidates[row["candidate_id"]]
        lines.append(
            f"| {rank} | {row['candidate_id']} | {candidate['formation']} | "
            f"£{candidate['gw1_bench_spend']:.1f}m | {row['mean_points']:.2f} | "
            f"{row['mean_delta_to_incumbent']:+.2f} | "
            f"[{row['delta_95ci_low']:+.2f}, {row['delta_95ci_high']:+.2f}] |"
        )
    lines.extend(
        [
            "",
            "## Historical bench evidence",
            "",
            "| Sample | Initial bench price | GW1–5 stranded points | Full-season stranded points | Rank correlation |",
            "| --- | ---: | ---: | ---: | ---: |",
            (
                f"| 2019/20 eventual top 10 | "
                f"£{history['top10_2019_20']['initial_total_bench_spend']['mean']:.2f}m "
                f"(range £{history['top10_2019_20']['initial_total_bench_spend']['minimum']:.1f}–"
                f"£{history['top10_2019_20']['initial_total_bench_spend']['maximum']:.1f}m) | "
                f"{history['top10_2019_20']['bench_points_gw1_5']['mean']:.1f} | "
                f"{history['top10_2019_20']['bench_points_full_season']['mean']:.1f} | — |"
            ),
            (
                f"| 2019/20 eventual top 50 | unavailable | unavailable | "
                f"{history['top50_2019_20']['bench_points_full_season']['mean']:.1f} | — |"
            ),
            (
                f"| 2025/26 final top 100 | unavailable | "
                f"{history['top100_2025_26']['bench_points_gw1_5']['mean']:.1f} | "
                f"{history['top100_2025_26']['bench_points_full_season']['mean']:.1f} | "
                f"{history['top100_2025_26']['bench_points_rank_spearman']:+.2f} |"
            ),
            "",
            (
                "The old elite opening-price benchmark is £18.45m, materially below the current "
                "£22.5m. Yet only 13 of those 40 historical GW1 substitutes ever started in GW2–5; "
                "our current bench is deliberately built to rotate far more. This makes it a "
                "different strategy—not historical validation of overspending."
            ),
            "",
            "## Extreme failure test",
            "",
            (
                "The natural simulated probability that all four current GW1 substitutes make no "
                "appearance across all five weeks was "
                f"**{_probability_label(bench_usage['probability_all_four_no_appearance_all_five'], simulations)}**. "
                "I also force "
                "all four to zero minutes in every week anyway. Under that deliberately brutal "
                f"counterfactual, the incumbent changes by "
                f"**{result['decomposition']['forced_bench_failure_incumbent_delta']:+.2f} points** "
                "and its advantage over the best lean route changes as shown in the machine-readable "
                "results."
            ),
            "",
            "## Decision rule",
            "",
            result["verdict"]["decision_rule"],
            "",
            (
                "This is a pre-deadline decision receipt, not a promise of realised points. "
                "Re-run it after material transfers, injuries, predicted lineups or price changes."
            ),
            "",
            "## Sources and limitations",
            "",
            "- Official 2026/27 changes: " + OFFICIAL_RULES["2026_27_changes"],
            "- Official autosub rules: " + OFFICIAL_RULES["automatic_substitutions"],
            "- Official transfer rules: " + OFFICIAL_RULES["transfers"],
            "- Official 2026/27 chip rules: " + OFFICIAL_RULES["chips"],
            "- Historical manager picks: local normalized Vaastav, Paul, FPL Genius, Titan and Soong datasets documented in `data/README.md`.",
            "- " + "\n- ".join(history["limitations"]),
            "- The clean-sheet stress is a sensitivity analysis, not a calibrated alternative forecast.",
            "- The same forecast family selects and evaluates players; paired simulations reduce Monte Carlo noise but cannot remove shared model bias.",
            "",
        ]
    )
    return "\n".join(lines)


def run_bench_audit(*, simulations: int = 25_000, seed: int = 20260803) -> dict[str, Any]:
    if simulations < 5_000:
        raise ValueError("Bench audit requires at least 5,000 simulations")
    ensure_engine_layout()
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    historical = _historical_evidence()
    rows, events_list = _player_rows()
    events = tuple(event for event in DEFAULT_EVENTS if event in events_list)
    if events != DEFAULT_EVENTS:
        raise ValueError(f"Expected forecasts for {DEFAULT_EVENTS}, got {events}")

    specifications = [
        ("B00", "incumbent-8pct-proxy", {}),
        ("Z00", "zero-bench-proxy", {"bench_autosub_weight": 0.0}),
        (
            "Z18",
            "zero-proxy-bench<=18.5",
            {"bench_autosub_weight": 0.0, "gw1_bench_spend": (None, 185.0)},
        ),
        (
            "Z20",
            "zero-proxy-bench<=20.0",
            {"bench_autosub_weight": 0.0, "gw1_bench_spend": (None, 200.0)},
        ),
        (
            "Z22",
            "zero-proxy-bench<=22.0",
            {"bench_autosub_weight": 0.0, "gw1_bench_spend": (None, 220.0)},
        ),
        ("F3", "zero-proxy-force-3DEF", {"bench_autosub_weight": 0.0, "gw1_defenders": 3}),
        ("F4", "zero-proxy-force-4DEF", {"bench_autosub_weight": 0.0, "gw1_defenders": 4}),
        ("F5", "zero-proxy-force-5DEF", {"bench_autosub_weight": 0.0, "gw1_defenders": 5}),
        (
            "F3L",
            "zero-proxy-force-3DEF-bench<=18.5",
            {
                "bench_autosub_weight": 0.0,
                "gw1_defenders": 3,
                "gw1_bench_spend": (None, 185.0),
            },
        ),
        (
            "F4L",
            "zero-proxy-force-4DEF-bench<=18.5",
            {
                "bench_autosub_weight": 0.0,
                "gw1_defenders": 4,
                "gw1_bench_spend": (None, 185.0),
            },
        ),
        (
            "F5L",
            "zero-proxy-force-5DEF-bench<=18.5",
            {
                "bench_autosub_weight": 0.0,
                "gw1_defenders": 5,
                "gw1_bench_spend": (None, 185.0),
            },
        ),
    ]
    exact_candidates = []
    solutions = {}
    for candidate_id, archetype, kwargs in specifications:
        print(f"Solving {candidate_id}: {archetype}", flush=True)
        solution = _solve(rows, list(events), **kwargs)
        solutions[candidate_id] = solution
        exact_candidates.append(
            _solution_candidate(candidate_id, archetype, solution, events)
        )

    _, loaded = _load_rows(events)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    selected = list(solutions["B00"]["selected"])
    fixed = _fixed_candidate(
        "FIX", "incumbent-fixed-squad-rotating-XI", selected, by_player, meta, events,
        lock_gw1_xi=False,
    )
    locked = _fixed_candidate(
        "LOCK", "incumbent-fixed-GW1-XI", selected, by_player, meta, events,
        lock_gw1_xi=True,
    )
    candidates = [*exact_candidates, fixed, locked]

    # Re-score the two current global-search recommendations under the same
    # clean-sheet shock as the forced-formation candidates. This prevents the
    # structural audit from testing only locally constrained solves.
    if RESIDUAL_CANDIDATES.exists() and RESIDUAL_RESULTS.exists():
        residual_result = json.loads(RESIDUAL_RESULTS.read_text(encoding="utf-8"))
        residual_id = str(residual_result["recommendation"]["candidate_id"])
        residual_payload = json.loads(RESIDUAL_CANDIDATES.read_text(encoding="utf-8"))
        residual = next(
            candidate
            for candidate in residual_payload["candidates"]
            if candidate["candidate_id"] == residual_id
        )
        residual_policy = _policy_candidate(residual, rows, events)
        residual_policy["archetype"] = f"residual-recommendation:{residual['archetype']}"
        residual_policy["transfer_count_gw2_5"] = sum(
            int(plan["used"]) for plan in residual_policy["transfer_policy"].values()
        )
        candidates.append(residual_policy)
    if COMPONENT_CANDIDATES.exists() and COMPONENT_RESULTS.exists():
        component_result = json.loads(COMPONENT_RESULTS.read_text(encoding="utf-8"))
        component_id = str(component_result["leaders"]["evidence_weighted"])
        if component_id.startswith("C"):
            component_payload = json.loads(COMPONENT_CANDIDATES.read_text(encoding="utf-8"))
            component = dict(
                next(
                    candidate
                    for candidate in component_payload["candidates"]
                    if candidate["candidate_id"] == component_id
                )
            )
            component["archetype"] = f"component-evidence:{component['archetype']}"
            component["transfer_count_gw2_5"] = sum(
                int(plan["used"]) for plan in component["transfer_policy"].values()
            )
            candidates.append(component)

    component_backtest = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    if not BPS_METRICS_FILE.exists():
        raise FileNotFoundError("Run fplagent reconstruct-bps before the bench audit")
    bps_metrics = json.loads(BPS_METRICS_FILE.read_text(encoding="utf-8"))
    raw_weight = float(component_backtest["blend_selection"]["selected_raw_weight"])
    goal_rates, goal_diagnostics = predict_current_goal_rates(by_player, events)
    empirical = calibrate_empirical_components()
    print(f"Simulating {simulations:,} paired base paths", flush=True)
    player_ids, raw_points, anchored_points, played, component_means, diagnostics = (
        simulate_component_outcomes(
            by_player,
            events,
            goal_rates,
            empirical,
            simulations,
            seed + 301,
        )
    )
    raw_scores = _score_candidates(candidates, player_ids, events, raw_points, played, meta)
    anchored_scores = _score_candidates(
        candidates, player_ids, events, anchored_points, played, meta
    )
    evidence_scores = anchored_scores + raw_weight * (raw_scores - anchored_scores)
    raw_no_autosub_scores = _score_without_autosubs(
        candidates, player_ids, events, raw_points, played
    )
    anchored_no_autosub_scores = _score_without_autosubs(
        candidates, player_ids, events, anchored_points, played
    )
    evidence_no_autosub_scores = anchored_no_autosub_scores + raw_weight * (
        raw_no_autosub_scores - anchored_no_autosub_scores
    )

    global_index = {element: index for index, element in enumerate(player_ids)}
    incumbent_lineup = candidates[0]["lineups"]["1"]
    initial_bench_ids = [int(element) for element in incumbent_lineup["bench_order"]]
    initial_bench_indices = [global_index[element] for element in initial_bench_ids]
    player_usage = []
    for element in initial_bench_ids:
        index = global_index[element]
        planned_starts = [
            event
            for event in events[1:]
            if element in set(candidates[0]["lineups"][str(event)]["starters"])
        ]
        player_usage.append(
            {
                "element": element,
                "name": meta[element]["player_name"],
                "position": meta[element]["position"],
                "price": float(meta[element]["market_price"]) / 10.0,
                "planned_starts": planned_starts,
                "probability_no_appearance_all_five": float(
                    np.mean(~played[:, :, index].any(axis=1))
                ),
                "mean_appearances": float(played[:, :, index].sum(axis=1).mean()),
            }
        )
    all_four_absent = float(
        np.mean(~played[:, :, initial_bench_indices].any(axis=(1, 2)))
    )

    failure_raw = raw_points.copy()
    failure_anchored = anchored_points.copy()
    failure_played = played.copy()
    failure_raw[:, :, initial_bench_indices] = 0
    failure_anchored[:, :, initial_bench_indices] = 0
    failure_played[:, :, initial_bench_indices] = False
    failure_raw_scores = _score_candidates(
        candidates, player_ids, events, failure_raw, failure_played, meta
    )
    failure_anchored_scores = _score_candidates(
        candidates, player_ids, events, failure_anchored, failure_played, meta
    )
    failure_evidence_scores = failure_anchored_scores + raw_weight * (
        failure_raw_scores - failure_anchored_scores
    )
    del failure_raw, failure_anchored, failure_played

    stress_multiplier = 1.15
    stressed_goal_rates = {
        key: (home * stress_multiplier, away * stress_multiplier)
        for key, (home, away) in goal_rates.items()
    }
    print(f"Simulating {simulations:,} clean-sheet-pessimism paths", flush=True)
    stress_player_ids, stress_raw, _, stress_played, _, stress_diagnostics = (
        simulate_component_outcomes(
            by_player,
            events,
            stressed_goal_rates,
            empirical,
            simulations,
            seed + 1301,
        )
    )
    if stress_player_ids != player_ids:
        raise RuntimeError("Stress simulation player order changed")
    stress_scores = _score_candidates(
        candidates, player_ids, events, stress_raw, stress_played, meta
    )

    b00 = 0
    fix_index = next(i for i, candidate in enumerate(candidates) if candidate["candidate_id"] == "FIX")
    lock_index = next(
        i for i, candidate in enumerate(candidates) if candidate["candidate_id"] == "LOCK"
    )
    evidence_total = evidence_scores.sum(axis=2)
    no_autosub_total = evidence_no_autosub_scores.sum(axis=2)
    failure_total = failure_evidence_scores.sum(axis=2)
    autosub_by_candidate = {
        candidate["candidate_id"]: float(
            (evidence_total[:, index] - no_autosub_total[:, index]).mean()
        )
        for index, candidate in enumerate(candidates)
    }
    autosub_value = autosub_by_candidate["B00"]
    rotation_value = float((evidence_total[:, fix_index] - evidence_total[:, lock_index]).mean())
    transfer_value = float((evidence_total[:, b00] - evidence_total[:, fix_index]).mean())
    failure_delta = float((failure_total[:, b00] - evidence_total[:, b00]).mean())

    incumbent_defenders = [
        int(element)
        for element in incumbent_lineup["starters"]
        if meta[int(element)]["position"] == "DEF"
    ]
    defender_components = []
    for element in incumbent_defenders:
        index = global_index[element]
        defender_components.append(
            {
                "element": element,
                "name": meta[element]["player_name"],
                "raw_total_points": float(component_means["raw_total_points"][0, index]),
                "clean_sheet_points": float(component_means["clean_sheet_points"][0, index]),
                "defensive_contribution_points": float(
                    component_means["defensive_contribution_points"][0, index]
                ),
                "goal_assist_points": float(
                    component_means["goal_points"][0, index]
                    + component_means["assist_points"][0, index]
                ),
                "bonus_points": float(component_means["bonus_points"][0, index]),
            }
        )

    base_cs = [math.exp(-rate) for rates in goal_rates.values() for rate in rates]
    stress_cs = [math.exp(-rate) for rates in stressed_goal_rates.values() for rate in rates]
    evidence_metrics = _metric_rows(candidates, evidence_scores)
    stress_metrics = _metric_rows(candidates, stress_scores)
    failure_metrics = _metric_rows(candidates, failure_evidence_scores)
    best_evidence = max(evidence_metrics, key=lambda row: row["mean_points"])
    lean_ids = {"Z18", "F3L", "F4L", "F5L"}
    best_lean = max(
        (row for row in evidence_metrics if row["candidate_id"] in lean_ids),
        key=lambda row: row["mean_points"],
    )
    best_lean_autosub = autosub_by_candidate[best_lean["candidate_id"]]
    best_five_stress = max(
        (
            row
            for row in stress_metrics
            if candidates[
                next(
                    index
                    for index, candidate in enumerate(candidates)
                    if candidate["candidate_id"] == row["candidate_id"]
                )
            ]["lineups"]["1"]["formation"].startswith("5-")
        ),
        key=lambda row: row["mean_points"],
    )
    best_nonfive_stress = max(
        (
            row
            for row in stress_metrics
            if candidates[next(i for i, c in enumerate(candidates) if c["candidate_id"] == row["candidate_id"])]
            ["lineups"]["1"]["formation"]
            not in {"5-4-1", "5-3-2", "5-2-3"}
        ),
        key=lambda row: row["mean_points"],
    )

    bench_gap = best_lean["mean_delta_to_incumbent"]
    formation_stress_gap = best_nonfive_stress["mean_points"] - best_five_stress["mean_points"]
    if best_evidence["candidate_id"] == "B00" and bench_gap <= -1.0:
        bench_verdict = (
            f"The deep bench survives the red-team test: the best £18.5m-capped exact route "
            f"({best_lean['candidate_id']}) is {bench_gap:+.2f} points behind over GW1–5. "
            "It is justified mainly by planned rotation, not autosub insurance or transfer banking."
        )
    else:
        bench_verdict = (
            f"The £22.5m bench is not robust enough to retain automatically: the best lean exact "
            f"route ({best_lean['candidate_id']}) is {bench_gap:+.2f} points from the incumbent, "
            f"and the overall paired leader is {best_evidence['candidate_id']}."
        )
    if formation_stress_gap > 0.5:
        formation_verdict = (
            f"Five defenders fail the clean-sheet-pessimism test: the best non-five route beats "
            f"the best five-defender route by {formation_stress_gap:.2f} raw points. Treat 5-3-2 "
            "as model-fragile until deadline forecasts independently reconfirm it."
        )
    else:
        formation_verdict = (
            f"Five defenders remain competitive when goal rates are inflated: the best non-five "
            f"route is {formation_stress_gap:+.2f} raw points relative to the best five-defender "
            "route. The choice is unusual historically but is not merely a clean-sheet artefact."
        )

    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "official_rules": OFFICIAL_RULES,
        "history": historical,
        "candidates": _candidate_table(candidates),
        "current_bench_usage": {
            "players": player_usage,
            "planned_start_events_gw2_5": sum(len(row["planned_starts"]) for row in player_usage),
            "probability_all_four_no_appearance_all_five": all_four_absent,
        },
        "decomposition": {
            "autosub_net_points_gw1_5": autosub_value,
            "autosub_net_points_by_candidate": autosub_by_candidate,
            "best_lean_candidate": best_lean["candidate_id"],
            "best_lean_autosub_net_points_gw1_5": best_lean_autosub,
            "deep_minus_best_lean_autosub_points": autosub_value - best_lean_autosub,
            "rotation_value_points_gw1_5": rotation_value,
            "transfer_policy_value_points_gw1_5": transfer_value,
            "forced_bench_failure_incumbent_delta": failure_delta,
        },
        "defender_component_decomposition": defender_components,
        "simulation": {
            "simulations": simulations,
            "stress_simulations": simulations,
            "evidence_raw_weight": raw_weight,
            "goal_rate_stress_multiplier": stress_multiplier,
            "mean_clean_sheet_probability_base": float(np.mean(base_cs)),
            "mean_clean_sheet_probability_stress": float(np.mean(stress_cs)),
            "raw_metrics": _metric_rows(candidates, raw_scores),
            "anchored_metrics": _metric_rows(candidates, anchored_scores),
            "evidence_weighted_metrics": evidence_metrics,
            "clean_sheet_pessimism_raw_metrics": stress_metrics,
            "forced_current_bench_dnp_metrics": failure_metrics,
            "base_diagnostics": diagnostics,
            "stress_diagnostics": stress_diagnostics,
            "goal_rate_diagnostics": goal_diagnostics,
        },
        "model_validation": {
            "goal_model": json.loads(GOAL_METRICS_FILE.read_text(encoding="utf-8")),
            "component_backtest": component_backtest,
            "bps_2026_27": bps_metrics,
        },
        "verdict": {
            "headline": bench_verdict + " " + formation_verdict,
            "bench": bench_verdict,
            "formation": formation_verdict,
            "decision_rule": (
                "Do not lock the squad from price structure alone. Keep the incumbent only if it "
                "leads the zero-proxy exact alternatives in the paired evidence blend, remains "
                "competitive under inflated goal rates, and all three intended rotation players "
                "retain strong predicted minutes at the final deadline run. Otherwise promote the "
                "highest-scoring lean/non-five counterfactual and spend the released money in the XI."
            ),
        },
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
