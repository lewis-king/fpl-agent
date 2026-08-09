from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

import duckdb
import highspy
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.special import ndtr
from sklearn.isotonic import IsotonicRegression

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .models import BACKTEST_FORECAST, CURRENT_FORECAST, MODEL_FILE
from .optimizer import DECISION_JSON, DEFAULT_HORIZON_DECAY, POSITION_ORDER, _solve, _weights
from .paths import DECISIONS, MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import SquadRules, load_rules, validate_lineup, validate_squad

TOURNAMENT_DIR = MODEL_DATA / "tournament_v1"
CANDIDATES_JSON = DECISIONS / "2026-27-gw1-candidates.json"
RESULTS_JSON = TOURNAMENT_DIR / "gw1-5-results.json"
RESULTS_PARQUET = TOURNAMENT_DIR / "gw1-5-candidate-metrics.parquet"
REPORT = REPORTS / "gw1-squad-tournament.md"
TRAINING_FEATURES = MODEL_DATA / "features" / "player_deadlines.parquet"
HISTORICAL_FIXTURES = PROCESSED / "vaastav" / "fixtures.parquet"
CURRENT_FIXTURES = PROCESSED / "fpl" / "2026-27" / "preseason" / "fixtures.parquet"
TOP_MANAGER_PICKS = PROCESSED / "vaastav" / "top_manager_picks.parquet"
TOP_MANAGER_SUMMARY = PROCESSED / "vaastav" / "top_manager_summary.parquet"
PLAYER_GAMEWEEKS = PROCESSED / "vaastav" / "player_gameweeks.parquet"

TOURNAMENT_VERSION = "correlated_residual_v1"
RESIDUAL_SCALE_BY_POSITION = {"GK": 0.65, "DEF": 0.40, "MID": 0.40, "FWD": 0.45}
POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_INDEX = {position: index for index, position in enumerate(POSITIONS)}
DEFAULT_EVENTS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class ResidualCalibration:
    global_shocks: np.ndarray
    fixture_shocks: np.ndarray
    residual_pools: dict[tuple[str, int], np.ndarray]
    bin_edges: dict[str, np.ndarray]
    residual_sd: dict[tuple[str, int], float]
    play_rho: float
    points_rho: float
    rows: int
    played_rows: int
    fixtures: int
    global_sd: float
    fixture_sd: float
    idiosyncratic_sd: float


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _load_rows(events: tuple[int, ...] = DEFAULT_EVENTS) -> tuple[list[dict], dict]:
    rows = [
        row
        for row in pq.read_table(CURRENT_FORECAST).to_pylist()
        if int(row["event_number"]) in events
    ]
    by_player: dict[int, dict[int, dict]] = defaultdict(dict)
    meta: dict[int, dict] = {}
    for row in rows:
        element = int(row["element"])
        event = int(row["event_number"])
        if event in by_player[element]:
            raise ValueError(f"Duplicate forecast for element={element}, event={event}")
        by_player[element][event] = row
        meta[element] = row
    missing = {
        element: sorted(set(events) - set(player_rows))
        for element, player_rows in by_player.items()
        if set(player_rows) != set(events)
    }
    if missing:
        raise ValueError(f"Incomplete current forecast horizon: {missing}")
    return rows, {"by_player": by_player, "meta": meta}


def _lineup_for_squad(
    selected: list[int],
    event: int,
    by_player: dict[int, dict[int, dict]],
    rules: SquadRules,
    required_starters: set[int] | None = None,
) -> dict[str, Any]:
    required_starters = required_starters or set()
    if not required_starters <= set(selected):
        raise ValueError("A required starter is not in the squad")
    by_position: dict[str, list[int]] = defaultdict(list)
    for element in selected:
        by_position[by_player[element][event]["position"]].append(element)
    for values in by_position.values():
        values.sort(
            key=lambda element: (
                float(by_player[element][event]["expected_points"]),
                float(by_player[element][event]["p_play"]),
                -float(by_player[element][event]["market_price"]),
            ),
            reverse=True,
        )

    def take(position: str, count: int) -> list[int] | None:
        required = [element for element in by_position[position] if element in required_starters]
        if len(required) > count:
            return None
        return (
            required
            + [element for element in by_position[position] if element not in required_starters][
                : count - len(required)
            ]
        )

    options: list[tuple[float, list[int]]] = []
    for defenders in range(rules.minimum_starters["DEF"], rules.maximum_starters["DEF"] + 1):
        for midfielders in range(rules.minimum_starters["MID"], rules.maximum_starters["MID"] + 1):
            forwards = 10 - defenders - midfielders
            if not rules.minimum_starters["FWD"] <= forwards <= rules.maximum_starters["FWD"]:
                continue
            groups = (
                take("GK", 1),
                take("DEF", defenders),
                take("MID", midfielders),
                take("FWD", forwards),
            )
            if any(group is None for group in groups):
                continue
            starters = [element for group in groups if group is not None for element in group]
            points = sum(
                float(by_player[element][event]["expected_points"]) for element in starters
            )
            options.append((points, starters))
    if not options:
        raise ValueError("No legal formation for squad")
    _, starters = max(options, key=lambda item: item[0])
    captain = max(
        starters,
        key=lambda element: (
            float(by_player[element][event]["expected_points"]),
            float(by_player[element][event]["p_play"]),
        ),
    )
    vice = max(
        (element for element in starters if element != captain),
        key=lambda element: (
            float(by_player[element][event]["expected_points"]),
            float(by_player[element][event]["p_play"]),
        ),
    )
    bench = [element for element in selected if element not in starters]
    outfield = sorted(
        (element for element in bench if by_player[element][event]["position"] != "GK"),
        key=lambda element: (
            float(by_player[element][event]["expected_points"]),
            float(by_player[element][event]["p_play"]),
        ),
        reverse=True,
    )
    reserve_gk = [element for element in bench if by_player[element][event]["position"] == "GK"]
    expected = sum(
        float(by_player[element][event]["expected_points"]) for element in starters
    ) + float(by_player[captain][event]["expected_points"])
    return {
        "starters": starters,
        "captain": captain,
        "vice_captain": vice,
        "bench_order": outfield + reserve_gk,
        "expected_points": expected,
        "formation": "-".join(
            str(sum(by_player[element][event]["position"] == position for element in starters))
            for position in ("DEF", "MID", "FWD")
        ),
    }


def _base_objective(
    selected: list[int],
    lineups: dict[int, dict[str, Any]],
    by_player: dict[int, dict[int, dict]],
    events: tuple[int, ...],
    decay: float = DEFAULT_HORIZON_DECAY,
) -> float:
    weights = _weights(list(events), decay)
    return float(sum(weights[event] * float(lineups[event]["expected_points"]) for event in events))


def _solve_static(
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    events: tuple[int, ...],
    rules: SquadRules,
    *,
    score_by_player_event: dict[tuple[int, int], float] | None = None,
    excluded_squads: list[set[int]] | None = None,
    force_include: set[int] | None = None,
    force_start_gw1: set[int] | None = None,
    bench_spend: tuple[float | None, float | None] | None = None,
    horizon_decay: float = DEFAULT_HORIZON_DECAY,
    bench_weight: float = 0.0,
) -> dict[str, Any]:
    players = sorted(
        element
        for element, row in meta.items()
        if bool(row.get("can_select", True)) and not bool(row.get("removed", False))
    )
    player_index = {element: index for index, element in enumerate(players)}
    event_index = {event: index for index, event in enumerate(events)}
    n_players = len(players)
    n_events = len(events)
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("random_seed", 2026)
    highs.setOptionValue("mip_rel_gap", 1e-8)
    highs.setOptionValue("time_limit", 45.0)
    integer = highspy.HighsVarType.kInteger
    squad = highs.addVariables(n_players, lb=0, ub=1, type=integer, out_array=True)
    start = highs.addVariables(n_players * n_events, lb=0, ub=1, type=integer, out_array=True)
    captain = highs.addVariables(n_players * n_events, lb=0, ub=1, type=integer, out_array=True)

    def squad_var(element: int):
        return squad[player_index[element]]

    def start_var(element: int, event: int):
        return start[player_index[element] * n_events + event_index[event]]

    def captain_var(element: int, event: int):
        return captain[player_index[element] * n_events + event_index[event]]

    highs.addConstr(sum(squad_var(element) for element in players) == rules.squad_size)
    for position, count in rules.squad_positions.items():
        highs.addConstr(
            sum(squad_var(element) for element in players if meta[element]["position"] == position)
            == count
        )
    for team_id in sorted({int(meta[element]["team_id"]) for element in players}):
        highs.addConstr(
            sum(
                squad_var(element)
                for element in players
                if int(meta[element]["team_id"]) == team_id
            )
            <= rules.club_limit
        )
    highs.addConstr(
        sum(float(meta[element]["market_price"]) * squad_var(element) for element in players)
        <= rules.budget
    )
    for element in force_include or set():
        if element not in player_index:
            raise ValueError(f"Forced player {element} is not selectable")
        highs.addConstr(squad_var(element) == 1)
    for element in force_start_gw1 or set():
        if element not in player_index:
            raise ValueError(f"Forced starter {element} is not selectable")
        highs.addConstr(squad_var(element) == 1)
        highs.addConstr(start_var(element, events[0]) == 1)
    for old_squad in excluded_squads or []:
        highs.addConstr(
            sum(squad_var(element) for element in old_squad if element in player_index)
            <= rules.squad_size - 1
        )

    for event in events:
        highs.addConstr(sum(start_var(element, event) for element in players) == 11)
        highs.addConstr(sum(captain_var(element, event) for element in players) == 1)
        for element in players:
            highs.addConstr(start_var(element, event) <= squad_var(element))
            highs.addConstr(captain_var(element, event) <= start_var(element, event))
        for position in POSITIONS:
            count = sum(
                start_var(element, event)
                for element in players
                if meta[element]["position"] == position
            )
            highs.addConstr(count >= rules.minimum_starters[position])
            highs.addConstr(count <= rules.maximum_starters[position])

    if bench_spend is not None:
        first_event = events[0]
        bench_cost = sum(
            float(meta[element]["market_price"])
            * (squad_var(element) - start_var(element, first_event))
            for element in players
        )
        minimum, maximum = bench_spend
        if minimum is not None:
            highs.addConstr(bench_cost >= minimum)
        if maximum is not None:
            highs.addConstr(bench_cost <= maximum)

    weights = _weights(list(events), horizon_decay)
    objective = 0
    for element in players:
        for event in events:
            points = float(by_player[element][event]["expected_points"])
            weighted = weights[event] * points
            objective += weighted * start_var(element, event)
            objective += weighted * captain_var(element, event)
            if bench_weight:
                objective += (
                    bench_weight * weighted * (squad_var(element) - start_var(element, event))
                )
            if score_by_player_event is not None:
                # Perturb membership without corrupting the forecast-best XI or the
                # meaning of a bench-spend constraint.
                scenario_delta = score_by_player_event[(element, event)] - points
                objective += 0.35 * weights[event] * scenario_delta * squad_var(element)
    highs.maximize(objective)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Static candidate solve failed: {highs.getModelStatus()}")

    selected = [element for element in players if highs.val(squad_var(element)) > 0.5]
    lineups = {}
    for event in events:
        starters = [element for element in players if highs.val(start_var(element, event)) > 0.5]
        captain_id = next(
            element for element in players if highs.val(captain_var(element, event)) > 0.5
        )
        vice_id = max(
            (element for element in starters if element != captain_id),
            key=lambda element: (
                float(by_player[element][event]["expected_points"]),
                float(by_player[element][event]["p_play"]),
            ),
        )
        bench = [element for element in selected if element not in starters]
        outfield_bench = sorted(
            (element for element in bench if meta[element]["position"] != "GK"),
            key=lambda element: (
                float(by_player[element][event]["expected_points"]),
                float(by_player[element][event]["p_play"]),
            ),
            reverse=True,
        )
        reserve_goalkeeper = [element for element in bench if meta[element]["position"] == "GK"]
        expected = sum(
            float(by_player[element][event]["expected_points"]) for element in starters
        ) + float(by_player[captain_id][event]["expected_points"])
        lineups[event] = {
            "starters": starters,
            "captain": captain_id,
            "vice_captain": vice_id,
            "bench_order": outfield_bench + reserve_goalkeeper,
            "expected_points": expected,
            "formation": "-".join(
                str(sum(meta[element]["position"] == position for element in starters))
                for position in ("DEF", "MID", "FWD")
            ),
        }
    return {
        "selected": selected,
        "lineups": lineups,
        "base_objective": _base_objective(selected, lineups, by_player, events),
        "solver_objective": float(highs.getObjectiveValue()),
    }


def _premium_players(
    meta: dict[int, dict], by_player: dict[int, dict[int, dict]], events: tuple[int, ...]
) -> list[int]:
    weights = _weights(list(events), DEFAULT_HORIZON_DECAY)
    eligible = [
        element
        for element, row in meta.items()
        if row["position"] in {"MID", "FWD"}
        and float(row["market_price"]) >= 90
        and bool(row.get("can_select", True))
        and not bool(row.get("removed", False))
    ]
    return sorted(
        eligible,
        key=lambda element: sum(
            weights[event] * float(by_player[element][event]["expected_points"]) for event in events
        ),
        reverse=True,
    )


def _candidate_record(
    index: int,
    solution: dict[str, Any],
    archetype: str,
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    events: tuple[int, ...],
) -> dict[str, Any]:
    selected = list(solution["selected"])
    gw1 = solution["lineups"][events[0]]
    bench = set(gw1["bench_order"])
    premium = [
        element
        for element in selected
        if meta[element]["position"] in {"MID", "FWD"}
        and float(meta[element]["market_price"]) >= 90
    ]
    return {
        "candidate_id": f"S{index:03d}",
        "archetype": archetype,
        "selected": selected,
        "base_objective": float(solution["base_objective"]),
        "budget_spent": sum(float(meta[element]["market_price"]) for element in selected) / 10.0,
        "bank": (
            load_rules().budget - sum(float(meta[element]["market_price"]) for element in selected)
        )
        / 10.0,
        "gw1_bench_spend": sum(float(meta[element]["market_price"]) for element in bench) / 10.0,
        "gw1_outfield_bench_spend": sum(
            float(meta[element]["market_price"])
            for element in bench
            if meta[element]["position"] != "GK"
        )
        / 10.0,
        "premium_players": premium,
        "lineups": {str(event): solution["lineups"][event] for event in events},
        "players": [
            {
                "element": element,
                "name": meta[element]["player_name"],
                "position": meta[element]["position"],
                "team": meta[element]["team_short_name"],
                "price": float(meta[element]["market_price"]) / 10.0,
            }
            for element in sorted(
                selected,
                key=lambda item: (
                    POSITION_ORDER[meta[item]["position"]],
                    -float(meta[item]["market_price"]),
                ),
            )
        ],
    }


def generate_candidates(
    count: int = 128, events: tuple[int, ...] = DEFAULT_EVENTS, seed: int = 20260802
) -> dict[str, Any]:
    if count < 10:
        raise ValueError("At least ten candidates are required for a useful tournament")
    ensure_engine_layout()
    TOURNAMENT_DIR.mkdir(parents=True, exist_ok=True)
    _, loaded = _load_rows(events)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    rules = load_rules()
    receipt = json.loads(DECISION_JSON.read_text(encoding="utf-8"))
    anchor_selected = [int(item["element"]) for item in receipt["squad"]]
    anchor_lineups = {
        event: _lineup_for_squad(anchor_selected, event, by_player, rules) for event in events
    }
    anchor = {
        "selected": anchor_selected,
        "lineups": anchor_lineups,
        "base_objective": _base_objective(anchor_selected, anchor_lineups, by_player, events),
    }
    solutions: list[tuple[dict[str, Any], str]] = [(anchor, "current-transfer-aware")]
    seen = {frozenset(anchor_selected)}

    def add(solution: dict[str, Any], archetype: str) -> bool:
        key = frozenset(solution["selected"])
        if key in seen:
            return False
        seen.add(key)
        solutions.append((solution, archetype))
        return True

    excluded = [set(anchor_selected)]
    nominal = _solve_static(
        by_player,
        meta,
        events,
        rules,
        excluded_squads=excluded,
        bench_weight=0.0,
    )
    add(nominal, "static-xp")
    premiums = _premium_players(meta, by_player, events)
    premium_forces = [{element} for element in premiums]
    premium_forces.extend(set(pair) for pair in combinations(premiums[:4], 2))
    for forced in premium_forces:
        if len(solutions) >= count:
            break
        try:
            solution = _solve_static(
                by_player,
                meta,
                events,
                rules,
                excluded_squads=[set(item[0]["selected"]) for item in solutions],
                force_include=forced,
                force_start_gw1=forced,
                bench_weight=0.0,
            )
        except RuntimeError:
            continue
        names = "+".join(meta[element]["player_name"] for element in sorted(forced))
        add(solution, f"premium:{names}")

    # These bands deliberately surround the 2019/20 top-ten GW1 mean (£18.45m)
    # and the current candidate's unusually deep £23m bench.
    bench_bands = [
        (None, 185.0, "lean-bench"),
        (186.0, 200.0, "historical-bench-band"),
        (201.0, 220.0, "medium-bench"),
        (221.0, None, "deep-bench"),
    ]
    for minimum, maximum, name in bench_bands:
        for forced in [set(), *[{element} for element in premiums[:4]]]:
            if len(solutions) >= count:
                break
            try:
                solution = _solve_static(
                    by_player,
                    meta,
                    events,
                    rules,
                    excluded_squads=[set(item[0]["selected"]) for item in solutions],
                    force_include=forced,
                    force_start_gw1=forced,
                    bench_spend=(minimum, maximum),
                    bench_weight=0.0,
                )
            except RuntimeError:
                continue
            suffix = "" if not forced else ":" + meta[next(iter(forced))]["player_name"]
            add(solution, name + suffix)

    noise_cycle = (0.12, 0.20, 0.32, 0.48, 0.70)
    decay_cycle = (0.80, 0.88, 0.95)
    rng = np.random.default_rng(seed)

    def perturbed_scores(scale: float) -> dict[tuple[int, int], float]:
        player_shift = {element: rng.normal(0.0, scale) for element in meta}
        return {
            (element, event): max(
                0.0,
                float(row["expected_points"])
                + player_shift[element]
                + rng.normal(0.0, scale * 0.35),
            )
            for element, event_rows in by_player.items()
            for event, row in event_rows.items()
        }

    # Give the bench question enough statistical representation. Five hand-built
    # examples per band are supplemented to 20 before unconstrained candidates.
    for minimum, maximum, name in bench_bands:
        added = 0
        band_attempts = 0
        while added < 15 and len(solutions) < count and band_attempts < 80:
            scale = noise_cycle[band_attempts % len(noise_cycle)]
            decay = decay_cycle[(band_attempts // len(noise_cycle)) % len(decay_cycle)]
            solution = _solve_static(
                by_player,
                meta,
                events,
                rules,
                score_by_player_event=perturbed_scores(scale),
                excluded_squads=[set(item[0]["selected"]) for item in solutions],
                bench_spend=(minimum, maximum),
                horizon_decay=decay,
                bench_weight=0.0,
            )
            if add(solution, f"{name}:perturbed:{scale:.2f}:d{decay:.2f}"):
                added += 1
            band_attempts += 1

    attempts = 0
    band_cycle = [None, *[(lo, hi) for lo, hi, _ in bench_bands]]
    while len(solutions) < count and attempts < count * 12:
        scale = noise_cycle[attempts % len(noise_cycle)]
        decay = decay_cycle[(attempts // len(noise_cycle)) % len(decay_cycle)]
        band = band_cycle[(attempts // (len(noise_cycle) * len(decay_cycle))) % len(band_cycle)]
        scores = perturbed_scores(scale)
        forced: set[int] = set()
        if attempts % 7 == 0:
            forced = {premiums[(attempts // 7) % len(premiums)]}
        try:
            solution = _solve_static(
                by_player,
                meta,
                events,
                rules,
                score_by_player_event=scores,
                excluded_squads=[set(item[0]["selected"]) for item in solutions],
                force_include=forced,
                force_start_gw1=forced,
                bench_spend=band,
                horizon_decay=decay,
                bench_weight=0.0,
            )
        except RuntimeError:
            attempts += 1
            continue
        add(solution, f"perturbed:{scale:.2f}:d{decay:.2f}")
        attempts += 1
    if len(solutions) < count:
        raise RuntimeError(f"Only generated {len(solutions)} distinct candidates")

    candidates = [
        _candidate_record(index + 1, solution, archetype, by_player, meta, events)
        for index, (solution, archetype) in enumerate(solutions[:count])
    ]
    payload = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "events": list(events),
        "seed": seed,
        "candidate_count": len(candidates),
        "forecast_sha256": sha256_file(CURRENT_FORECAST),
        "model_sha256": sha256_file(MODEL_FILE),
        "candidates": candidates,
    }
    CANDIDATES_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def _load_residual_rows() -> list[dict]:
    connection = duckdb.connect()
    try:
        return (
            connection.execute(
                f"""
            SELECT
                o.season, o.event_number, o.element, o.position, o.team_id,
                o.target_points, o.expected_points, o.p_play,
                f.target_minutes, f.fixture_count
            FROM read_parquet('{_sql_path(BACKTEST_FORECAST)}') o
            JOIN read_parquet('{_sql_path(TRAINING_FEATURES)}') f
              ON o.season = f.season
             AND o.event_number = f.event_number
             AND o.element = f.element
            WHERE isfinite(o.target_points)
              AND isfinite(o.expected_points)
              AND isfinite(o.p_play)
            ORDER BY o.season, o.event_number, o.element
            """
            )
            .fetch_arrow_table()
            .to_pylist()
        )
    finally:
        connection.close()


def _lag_correlation(rows: list[dict], value_key: str) -> float:
    by_player: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if math.isfinite(float(row[value_key])):
            by_player[(row["season"], int(row["element"]))].append(row)
    left: list[float] = []
    right: list[float] = []
    for player_rows in by_player.values():
        player_rows.sort(key=lambda row: int(row["event_number"]))
        for previous, current in pairwise(player_rows):
            if int(current["event_number"]) != int(previous["event_number"]) + 1:
                continue
            left.append(float(previous[value_key]))
            right.append(float(current[value_key]))
    if len(left) < 3 or np.std(left) < 1e-9 or np.std(right) < 1e-9:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def calibrate_residuals() -> ResidualCalibration:
    rows = _load_residual_rows()
    for row in rows:
        p_play = float(np.clip(row["p_play"], 0.02, 0.995))
        played = float(row["target_minutes"] > 0)
        row["play_residual"] = (played - p_play) / math.sqrt(p_play * (1.0 - p_play))
        conditional = float(row["expected_points"]) / p_play
        row["conditional_prediction"] = conditional
        row["conditional_residual"] = (
            float(row["target_points"]) - conditional if played else float("nan")
        )
    played_rows = [
        row
        for row in rows
        if row["target_minutes"] > 0
        and float(row["p_play"]) >= 0.05
        and float(row["fixture_count"]) == 1.0
        and math.isfinite(float(row["conditional_residual"]))
    ]

    global_group: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    team_group: dict[tuple[str, int, int, str], list[float]] = defaultdict(list)
    for row in played_rows:
        global_group[(row["season"], int(row["event_number"]), row["position"])].append(
            float(row["conditional_residual"])
        )
        team_group[
            (row["season"], int(row["event_number"]), int(row["team_id"]), row["position"])
        ].append(float(row["conditional_residual"]))
    global_mean = {key: float(np.mean(values)) for key, values in global_group.items()}
    team_shock = {}
    for key, values in team_group.items():
        season, event, _, position = key
        raw = float(np.mean(values)) - global_mean[(season, event, position)]
        shrinkage = len(values) / (len(values) + 2.0)
        team_shock[key] = shrinkage * raw
    for row in played_rows:
        global_value = global_mean[(row["season"], int(row["event_number"]), row["position"])]
        team_value = team_shock[
            (row["season"], int(row["event_number"]), int(row["team_id"]), row["position"])
        ]
        row["idiosyncratic_residual"] = (
            float(row["conditional_residual"]) - global_value - team_value
        )

    event_keys = sorted({(row["season"], int(row["event_number"])) for row in played_rows})
    global_shocks = np.zeros((len(event_keys), len(POSITIONS)), dtype=np.float32)
    for index, (season, event) in enumerate(event_keys):
        for position, position_index in POSITION_INDEX.items():
            global_shocks[index, position_index] = global_mean.get((season, event, position), 0.0)
    global_shocks -= global_shocks.mean(axis=0, keepdims=True)

    fixtures = [
        row
        for row in pq.read_table(HISTORICAL_FIXTURES).to_pylist()
        if row["season"] in {item[0] for item in event_keys}
        and row["event"] is not None
        and (row["season"], int(row["event"])) in set(event_keys)
    ]
    fixture_shocks = np.zeros((len(fixtures), 2, len(POSITIONS)), dtype=np.float32)
    for fixture_index, fixture in enumerate(fixtures):
        season = fixture["season"]
        event = int(fixture["event"])
        for side_index, team_id in enumerate((int(fixture["team_h"]), int(fixture["team_a"]))):
            for position, position_index in POSITION_INDEX.items():
                fixture_shocks[fixture_index, side_index, position_index] = team_shock.get(
                    (season, event, team_id, position), 0.0
                )
    fixture_shocks -= fixture_shocks.mean(axis=0, keepdims=True)

    bin_edges: dict[str, np.ndarray] = {}
    residual_pools: dict[tuple[str, int], np.ndarray] = {}
    residual_sd: dict[tuple[str, int], float] = {}
    for position in POSITIONS:
        position_rows = [row for row in played_rows if row["position"] == position]
        predictions = np.asarray(
            [float(row["conditional_prediction"]) for row in position_rows], dtype=np.float64
        )
        edges = np.unique(np.quantile(predictions, [0.2, 0.4, 0.6, 0.8]))
        if len(edges) != 4:
            edges = np.asarray([2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        bin_edges[position] = edges
        for bin_index in range(5):
            values = np.asarray(
                [
                    float(row["idiosyncratic_residual"])
                    for row in position_rows
                    if int(np.digitize(row["conditional_prediction"], edges)) == bin_index
                ],
                dtype=np.float32,
            )
            if len(values) < 100:
                values = np.asarray(
                    [float(row["idiosyncratic_residual"]) for row in position_rows],
                    dtype=np.float32,
                )
            values -= values.mean()
            residual_pools[(position, bin_index)] = values
            residual_sd[(position, bin_index)] = float(values.std())

    play_rho = float(np.clip(_lag_correlation(rows, "play_residual"), 0.0, 0.60))
    points_rho = float(np.clip(_lag_correlation(played_rows, "idiosyncratic_residual"), 0.0, 0.45))
    all_idio = np.asarray([float(row["idiosyncratic_residual"]) for row in played_rows])
    return ResidualCalibration(
        global_shocks=global_shocks,
        fixture_shocks=fixture_shocks,
        residual_pools=residual_pools,
        bin_edges=bin_edges,
        residual_sd=residual_sd,
        play_rho=play_rho,
        points_rho=points_rho,
        rows=len(rows),
        played_rows=len(played_rows),
        fixtures=len(fixtures),
        global_sd=float(global_shocks.std()),
        fixture_sd=float(fixture_shocks.std()),
        idiosyncratic_sd=float(all_idio.std()),
    )


def backtest_marginal_distribution(seed: int = 20260802, draws: int = 400) -> dict[str, Any]:
    if draws < 100:
        raise ValueError("Distribution backtest requires at least 100 draws")
    rows = _load_residual_rows()
    rng = np.random.default_rng(seed)
    evaluations = []
    for test_season in ("2024-25", "2025-26"):
        for position in POSITIONS:
            training = [
                row
                for row in rows
                if row["season"] < test_season
                and row["position"] == position
                and row["target_minutes"] > 0
                and float(row["p_play"]) >= 0.05
            ]
            testing = [
                row
                for row in rows
                if row["season"] == test_season
                and row["position"] == position
                and float(row["p_play"]) >= 0.05
            ]
            training_conditional = np.asarray(
                [
                    float(row["expected_points"]) / max(float(row["p_play"]), 0.05)
                    for row in training
                ]
            )
            edges = np.unique(np.quantile(training_conditional, [0.2, 0.4, 0.6, 0.8]))
            if len(edges) != 4:
                edges = np.asarray([2.0, 3.0, 4.0, 5.0])
            pools = {}
            for bin_index in range(5):
                pool = np.asarray(
                    [
                        float(row["target_points"])
                        - float(row["expected_points"]) / max(float(row["p_play"]), 0.05)
                        for row in training
                        if int(
                            np.digitize(
                                float(row["expected_points"]) / max(float(row["p_play"]), 0.05),
                                edges,
                            )
                        )
                        == bin_index
                    ],
                    dtype=np.float32,
                )
                pool -= pool.mean()
                pools[bin_index] = pool
            actual_values = []
            predicted_means = []
            lower_values = []
            upper_values = []
            play_actual = []
            play_probability = []
            for row in testing:
                probability = float(np.clip(row["p_play"], 0.001, 0.999))
                conditional = float(row["expected_points"]) / max(probability, 0.05)
                bin_index = int(np.digitize(conditional, edges))
                pool = pools[bin_index]
                plays = rng.random(draws) < probability
                outcomes = np.where(
                    plays,
                    np.rint(
                        np.clip(
                            conditional
                            + RESIDUAL_SCALE_BY_POSITION[position]
                            * pool[rng.integers(0, len(pool), draws)],
                            -3.0,
                            24.0,
                        )
                    ),
                    0.0,
                )
                actual_values.append(float(row["target_points"]))
                predicted_means.append(float(outcomes.mean()))
                lower_values.append(float(np.quantile(outcomes, 0.10)))
                upper_values.append(float(np.quantile(outcomes, 0.90)))
                play_actual.append(float(row["target_minutes"] > 0))
                play_probability.append(probability)
            actual = np.asarray(actual_values)
            predicted = np.asarray(predicted_means)
            lower = np.asarray(lower_values)
            upper = np.asarray(upper_values)
            played = np.asarray(play_actual)
            probability = np.asarray(play_probability)
            high = probability >= 0.80
            evaluations.append(
                {
                    "season": test_season,
                    "position": position,
                    "rows": len(testing),
                    "mean_bias": float(np.mean(predicted - actual)),
                    "mae": float(np.mean(np.abs(predicted - actual))),
                    "p10_p90_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
                    "mean_interval_width": float(np.mean(upper - lower)),
                    "play_brier": float(np.mean(np.square(probability - played))),
                    "high_play_rows": int(high.sum()),
                    "high_play_predicted": float(probability[high].mean()),
                    "high_play_observed": float(played[high].mean()),
                }
            )
    total_rows = sum(row["rows"] for row in evaluations)
    return {
        "method": "season-forward marginal residual bootstrap",
        "draws_per_player_gameweek": draws,
        "residual_scale_by_position": RESIDUAL_SCALE_BY_POSITION,
        "scale_selection": ("Selected on 2024-25 interval coverage; 2025-26 is the forward check"),
        "evaluations": evaluations,
        "weighted_mean_bias": float(
            sum(row["rows"] * row["mean_bias"] for row in evaluations) / total_rows
        ),
        "weighted_p10_p90_coverage": float(
            sum(row["rows"] * row["p10_p90_coverage"] for row in evaluations) / total_rows
        ),
        "rows": total_rows,
    }


def _current_fixture_map(events: tuple[int, ...]) -> dict[int, list[tuple[int, int]]]:
    mapped: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in pq.read_table(CURRENT_FIXTURES).to_pylist():
        if row["event"] is not None and int(row["event"]) in events:
            mapped[int(row["event"])].append((int(row["team_h"]), int(row["team_a"])))
    for event in events:
        teams = [team for match in mapped[event] for team in match]
        if len(mapped[event]) != 10 or len(set(teams)) != 20:
            raise ValueError(f"GW{event} is not a complete ten-match fixture round")
    return mapped


def _premium_recovery_rows(rows: list[dict]) -> list[dict]:
    output = []
    for original in rows:
        row = dict(original)
        qualifies = (
            row["position"] in {"MID", "FWD"}
            and float(row["market_price"]) >= 90
            and float(row["ownership_percentile"]) >= 0.90
            and row["status"] == "a"
            and float(row["last_minutes"]) == 0.0
            and float(row["player_days_since_last_event"]) >= 60.0
        )
        if qualifies:
            row["p_play"] = max(float(row["p_play"]), 0.86)
            row["expected_points"] = float(row["conditional_points_if_playing"]) * float(
                row["p_play"]
            )
        output.append(row)
    return output


def _appearance_calibrated_rows(rows: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    historical = _load_residual_rows()
    calibrators = {}
    reliability = {}
    for position in POSITIONS:
        position_rows = [row for row in historical if row["position"] == position]
        predicted = np.asarray([float(row["p_play"]) for row in position_rows])
        played = np.asarray([float(row["target_minutes"] > 0) for row in position_rows])
        calibrator = IsotonicRegression(y_min=0.005, y_max=0.995, out_of_bounds="clip").fit(
            predicted, played
        )
        calibrators[position] = calibrator
        high = predicted >= 0.80
        reliability[position] = {
            "high_probability_rows": int(high.sum()),
            "high_probability_predicted": float(predicted[high].mean()),
            "high_probability_observed": float(played[high].mean()),
        }
    output = []
    changes = []
    for original in rows:
        row = dict(original)
        old_probability = float(row["p_play"])
        new_probability = float(calibrators[row["position"]].predict([old_probability])[0])
        expected = float(row["expected_points"])
        row["p_play"] = new_probability
        row["conditional_points_if_playing"] = expected / max(new_probability, 0.005)
        changes.append(new_probability - old_probability)
        output.append(row)
    return output, {
        "method": "position-specific isotonic calibration on rolling out-of-fold forecasts",
        "mean_probability_change": float(np.mean(changes)),
        "mean_absolute_probability_change": float(np.mean(np.abs(changes))),
        "expected_points_preserved": True,
        "high_probability_reliability": reliability,
    }


def _simulate_player_outcomes(
    player_ids: list[int],
    events: tuple[int, ...],
    by_player: dict[int, dict[int, dict]],
    calibration: ResidualCalibration,
    simulations: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n_players = len(player_ids)
    n_events = len(events)
    points = np.zeros((simulations, n_events, n_players), dtype=np.int8)
    played = np.zeros((simulations, n_events, n_players), dtype=bool)
    player_latent = rng.standard_normal((simulations, n_players), dtype=np.float32)
    performance_latent = rng.standard_normal((simulations, n_players), dtype=np.float32)
    fixture_map = _current_fixture_map(events)
    fixture_team_ids = {
        team_id
        for fixtures in fixture_map.values()
        for fixture in fixtures
        for team_id in fixture
    }
    player_team_ids = {
        int(by_player[element][event]["team_id"])
        for element in player_ids
        for event in events
    }
    team_ids = sorted(fixture_team_ids | player_team_ids)
    team_index = {team_id: index for index, team_id in enumerate(team_ids)}
    player_coefficient = math.sqrt(calibration.play_rho)
    event_coefficient = math.sqrt(max(0.0, 1.0 - calibration.play_rho))

    for event_offset, event in enumerate(events):
        global_indices = rng.integers(0, len(calibration.global_shocks), simulations)
        global_draw = calibration.global_shocks[global_indices]
        team_shock = np.zeros((simulations, len(team_ids), len(POSITIONS)), dtype=np.float32)
        position_scales = np.asarray(
            [RESIDUAL_SCALE_BY_POSITION[position] for position in POSITIONS],
            dtype=np.float32,
        )
        for home, away in fixture_map[event]:
            fixture_indices = rng.integers(0, len(calibration.fixture_shocks), simulations)
            draws = calibration.fixture_shocks[fixture_indices]
            team_shock[:, team_index[home], :] = position_scales * (
                global_draw + draws[:, 0, :]
            )
            team_shock[:, team_index[away], :] = position_scales * (
                global_draw + draws[:, 1, :]
            )

        independent_play = rng.standard_normal((simulations, n_players), dtype=np.float32)
        latent_play = player_coefficient * player_latent + event_coefficient * independent_play
        for player_offset, element in enumerate(player_ids):
            row = by_player[element][event]
            p_play = float(np.clip(row["p_play"], 0.001, 0.999))
            plays = ndtr(latent_play[:, player_offset]) < p_play
            played[:, event_offset, player_offset] = plays
            position = row["position"]
            position_index = POSITION_INDEX[position]
            conditional = float(row["conditional_points_if_playing"])
            bin_index = int(np.digitize(conditional, calibration.bin_edges[position]))
            pool = calibration.residual_pools[(position, bin_index)]
            idio = pool[rng.integers(0, len(pool), simulations)]
            if calibration.points_rho > 0:
                idio = (
                    math.sqrt(1.0 - calibration.points_rho) * idio
                    + math.sqrt(calibration.points_rho)
                    * calibration.residual_sd[(position, bin_index)]
                    * performance_latent[:, player_offset]
                )
            idio *= RESIDUAL_SCALE_BY_POSITION[position]
            team_id = int(row["team_id"])
            outcome = conditional + team_shock[:, team_index[team_id], position_index] + idio
            outcome = np.rint(np.clip(outcome, -3.0, 24.0)).astype(np.int8)
            points[:, event_offset, player_offset] = np.where(plays, outcome, 0)
    return points, played


def _autosub_weights(
    candidate: dict[str, Any],
    event: int,
    play_pattern: int,
    meta: dict[int, dict],
) -> np.ndarray:
    squad = [
        int(element)
        for element in candidate.get("planned_squads", {}).get(str(event), candidate["selected"])
    ]
    squad_index = {element: index for index, element in enumerate(squad)}
    plays = {element: bool(play_pattern & (1 << squad_index[element])) for element in squad}
    lineup = candidate["lineups"][str(event)]
    starters = [int(element) for element in lineup["starters"]]
    weights = np.zeros(len(squad), dtype=np.int8)
    for element in starters:
        if plays[element]:
            weights[squad_index[element]] = 1

    starter_gk = next(element for element in starters if meta[element]["position"] == "GK")
    reserve_gk = next(
        element for element in lineup["bench_order"] if meta[int(element)]["position"] == "GK"
    )
    reserve_gk = int(reserve_gk)
    if not plays[starter_gk] and plays[reserve_gk]:
        weights[squad_index[reserve_gk]] = 1

    missing_slots = [
        element for element in starters if meta[element]["position"] != "GK" and not plays[element]
    ]
    nominal_counts = {
        position: sum(meta[element]["position"] == position for element in starters)
        for position in ("DEF", "MID", "FWD")
    }
    outfield_bench = [
        int(element) for element in lineup["bench_order"] if meta[int(element)]["position"] != "GK"
    ]
    for substitute in outfield_bench:
        if not plays[substitute] or not missing_slots:
            continue
        new_position = meta[substitute]["position"]
        chosen_slot = None
        for old_slot in missing_slots:
            old_position = meta[old_slot]["position"]
            updated = dict(nominal_counts)
            updated[old_position] -= 1
            updated[new_position] += 1
            if updated["DEF"] >= 3 and updated["MID"] >= 2 and updated["FWD"] >= 1:
                chosen_slot = old_slot
                nominal_counts = updated
                break
        if chosen_slot is not None:
            missing_slots.remove(chosen_slot)
            weights[squad_index[substitute]] = 1

    captain = int(lineup["captain"])
    vice = int(lineup["vice_captain"])
    if plays[captain]:
        weights[squad_index[captain]] += 1
    elif plays[vice]:
        weights[squad_index[vice]] += 1
    return weights


def _score_candidates(
    candidates: list[dict[str, Any]],
    player_ids: list[int],
    events: tuple[int, ...],
    points: np.ndarray,
    played: np.ndarray,
    meta: dict[int, dict],
) -> np.ndarray:
    global_index = {element: index for index, element in enumerate(player_ids)}
    simulations = points.shape[0]
    scores = np.zeros((simulations, len(candidates), len(events)), dtype=np.int16)
    powers = (1 << np.arange(15, dtype=np.uint16)).astype(np.uint16)
    for candidate_index, candidate in enumerate(candidates):
        for event_offset, event in enumerate(events):
            squad = [
                int(element)
                for element in candidate.get("planned_squads", {}).get(
                    str(event), candidate["selected"]
                )
            ]
            squad_global = np.asarray([global_index[element] for element in squad], dtype=np.int64)
            patterns = (played[:, event_offset, squad_global].astype(np.uint16) @ powers).astype(
                np.uint16
            )
            unique, inverse = np.unique(patterns, return_inverse=True)
            weight_table = np.vstack(
                [_autosub_weights(candidate, event, int(pattern), meta) for pattern in unique]
            )
            weights = weight_table[inverse]
            scores[:, candidate_index, event_offset] = np.sum(
                points[:, event_offset, squad_global] * weights, axis=1
            )
    return scores


def _knockout(scores: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    simulations, candidates, events = scores.shape
    if candidates != 128 or events != 5:
        raise ValueError("The survival bracket requires 128 candidates and five rounds")
    rng = np.random.default_rng(seed)
    alive = np.ones((simulations, candidates), dtype=bool)
    survival = np.zeros((simulations, candidates, events), dtype=bool)
    cumulative = np.cumsum(scores, axis=2)
    for event_offset in range(events):
        keep = candidates // (2 ** (event_offset + 1))
        tie_break = rng.random((simulations, candidates), dtype=np.float32) * 1e-4
        ranking_score = np.where(alive, cumulative[:, :, event_offset] + tie_break, -1e9)
        chosen = np.argpartition(ranking_score, -keep, axis=1)[:, -keep:]
        alive = np.zeros_like(alive)
        alive[np.arange(simulations)[:, None], chosen] = True
        survival[:, :, event_offset] = alive
    final_score = np.where(
        alive,
        cumulative[:, :, -1] + rng.random((simulations, candidates), dtype=np.float32) * 1e-4,
        -1e9,
    )
    champions = np.argmax(final_score, axis=1)
    return survival, champions


def _metrics(
    scores: np.ndarray,
    candidates: list[dict[str, Any]],
    primary_index: int,
    knockout_seed: int,
) -> list[dict[str, Any]]:
    total = scores.sum(axis=2)
    rng = np.random.default_rng(knockout_seed + 1)
    ranking_total = total + rng.random(total.shape, dtype=np.float32) * 1e-4
    order = np.argsort(-ranking_total, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(len(total))[:, None], order] = np.arange(1, len(candidates) + 1)
    has_knockout = len(candidates) == 128 and scores.shape[2] == 5
    if has_knockout:
        survival, champions = _knockout(scores, knockout_seed)
    else:
        survival = None
        champions = None
    primary = total[:, primary_index]
    output = []
    for index, candidate in enumerate(candidates):
        values = total[:, index]
        delta = values - primary
        standard_error = float(delta.std(ddof=1) / math.sqrt(len(delta)))
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "mean_points": float(values.mean()),
                "median_points": float(np.median(values)),
                "p10_points": float(np.quantile(values, 0.10)),
                "p90_points": float(np.quantile(values, 0.90)),
                "downside_cvar10": float(values[values <= np.quantile(values, 0.10)].mean()),
                "mean_rank": float(ranks[:, index].mean()),
                "top_1_probability": float(np.mean(ranks[:, index] == 1)),
                "top_3_probability": float(np.mean(ranks[:, index] <= 3)),
                "top_10_probability": float(np.mean(ranks[:, index] <= 10)),
                "beat_primary_probability": float(np.mean(delta > 0)),
                "tie_primary_probability": float(np.mean(delta == 0)),
                "mean_delta_to_primary": float(delta.mean()),
                "delta_95ci_low": float(delta.mean() - 1.96 * standard_error),
                "delta_95ci_high": float(delta.mean() + 1.96 * standard_error),
                "survive_gw1_probability": (
                    float(survival[:, index, 0].mean()) if survival is not None else None
                ),
                "survive_gw2_probability": (
                    float(survival[:, index, 1].mean()) if survival is not None else None
                ),
                "survive_gw3_probability": (
                    float(survival[:, index, 2].mean()) if survival is not None else None
                ),
                "survive_gw4_probability": (
                    float(survival[:, index, 3].mean()) if survival is not None else None
                ),
                "final_four_probability": (
                    float(survival[:, index, 4].mean()) if survival is not None else None
                ),
                "champion_probability": (
                    float(np.mean(champions == index)) if champions is not None else None
                ),
            }
        )
    return output


def _historical_bench_evidence() -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            WITH pick_values AS (
                SELECT p.team_id, p.gw, p.position, max(g.value) / 10.0 AS price
                FROM read_parquet('{_sql_path(TOP_MANAGER_PICKS)}') p
                LEFT JOIN read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}') g
                  ON p.season = g.season
                 AND p.player_id = g.element
                 AND p.gw = g.GW
                GROUP BY ALL
            ), manager_weeks AS (
                SELECT team_id, gw,
                    sum(price) FILTER (position BETWEEN 12 AND 15) AS bench_spend,
                    sum(price) FILTER (position BETWEEN 12 AND 14) AS outfield_bench_spend
                FROM pick_values
                GROUP BY team_id, gw
            )
            SELECT gw, avg(bench_spend), min(bench_spend), max(bench_spend),
                   avg(outfield_bench_spend)
            FROM manager_weeks
            WHERE gw <= 5
            GROUP BY gw
            ORDER BY gw
            """
        ).fetchall()
        winner = connection.execute(
            f"""
            WITH pick_values AS (
                SELECT p.team_id, p.gw, p.position, max(g.value) / 10.0 AS price
                FROM read_parquet('{_sql_path(TOP_MANAGER_PICKS)}') p
                LEFT JOIN read_parquet('{_sql_path(PLAYER_GAMEWEEKS)}') g
                  ON p.season = g.season
                 AND p.player_id = g.element
                 AND p.gw = g.GW
                GROUP BY ALL
            )
            SELECT avg(price) FILTER (position BETWEEN 12 AND 15),
                   avg(price) FILTER (position BETWEEN 12 AND 14)
            FROM pick_values p
            JOIN read_parquet('{_sql_path(TOP_MANAGER_SUMMARY)}') s
              ON p.team_id = s.entry
            WHERE s.rank = 1 AND p.gw <= 5
            """
        ).fetchone()
    finally:
        connection.close()
    return {
        "source": "2019-20 eventual top ten (descriptive, survivorship-selected)",
        "gameweeks": [
            {
                "event": int(row[0]),
                "mean_bench_spend": float(row[1]),
                "minimum_bench_spend": float(row[2]),
                "maximum_bench_spend": float(row[3]),
                "mean_outfield_bench_spend": float(row[4]),
            }
            for row in rows
        ],
        "winner_early_mean_bench_spend": float(winner[0]) * 4.0,
        "winner_early_mean_outfield_bench_spend": float(winner[1]) * 3.0,
    }


def _run_scenario(
    candidates: list[dict[str, Any]],
    events: tuple[int, ...],
    by_player: dict[int, dict[int, dict]],
    meta: dict[int, dict],
    calibration: ResidualCalibration,
    simulations: int,
    seed: int,
) -> tuple[list[dict[str, Any]], np.ndarray, dict[str, float]]:
    player_ids = sorted(
        {
            int(element)
            for candidate in candidates
            for squad in [
                candidate["selected"],
                *candidate.get("planned_squads", {}).values(),
            ]
            for element in squad
        }
    )
    points, played = _simulate_player_outcomes(
        player_ids, events, by_player, calibration, simulations, seed
    )
    expected = np.asarray(
        [
            [float(by_player[element][event]["expected_points"]) for element in player_ids]
            for event in events
        ],
        dtype=np.float64,
    )
    p_play = np.asarray(
        [
            [float(by_player[element][event]["p_play"]) for element in player_ids]
            for event in events
        ],
        dtype=np.float64,
    )
    simulated_means = points.mean(axis=0)
    simulated_play = played.mean(axis=0)
    first_event_points = points[:, 0, :].astype(np.float64)
    correlation = np.corrcoef(first_event_points, rowvar=False)
    same_team: list[float] = []
    other_team: list[float] = []
    for left, right in combinations(range(len(player_ids)), 2):
        value = float(correlation[left, right])
        if not math.isfinite(value):
            continue
        left_team = int(by_player[player_ids[left]][events[0]]["team_id"])
        right_team = int(by_player[player_ids[right]][events[0]]["team_id"])
        (same_team if left_team == right_team else other_team).append(value)
    diagnostics = {
        "player_mean_bias": float(np.mean(simulated_means - expected)),
        "player_mean_absolute_calibration_error": float(
            np.mean(np.abs(simulated_means - expected))
        ),
        "appearance_mean_bias": float(np.mean(simulated_play - p_play)),
        "same_team_gw1_points_correlation": float(np.mean(same_team)),
        "other_team_gw1_points_correlation": float(np.mean(other_team)),
        "simulated_players": len(player_ids),
    }
    scores = _score_candidates(candidates, player_ids, events, points, played, meta)
    primary_index = next(
        index
        for index, candidate in enumerate(candidates)
        if candidate["archetype"] == "current-transfer-aware"
    )
    return _metrics(scores, candidates, primary_index, seed + 9001), scores, diagnostics


def _merge_candidate_metrics(
    candidates: list[dict[str, Any]],
    base: list[dict[str, Any]],
    recovery: list[dict[str, Any]],
    appearance: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_by_id = {row["candidate_id"]: row for row in base}
    recovery_by_id = {row["candidate_id"]: row for row in recovery}
    appearance_by_id = {row["candidate_id"]: row for row in appearance}
    output = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        output.append(
            {
                "candidate_id": candidate_id,
                "archetype": candidate["archetype"],
                "budget_spent": candidate["budget_spent"],
                "bank": candidate["bank"],
                "gw1_bench_spend": candidate["gw1_bench_spend"],
                "gw1_outfield_bench_spend": candidate["gw1_outfield_bench_spend"],
                "premium_names": ", ".join(
                    player["name"]
                    for player in candidate["players"]
                    if player["element"] in set(candidate["premium_players"])
                ),
                **{
                    f"base_{key}": value
                    for key, value in base_by_id[candidate_id].items()
                    if key != "candidate_id"
                },
                **{
                    f"recovery_{key}": value
                    for key, value in recovery_by_id[candidate_id].items()
                    if key != "candidate_id"
                },
                **{
                    f"appearance_{key}": value
                    for key, value in appearance_by_id[candidate_id].items()
                    if key != "candidate_id"
                },
            }
        )
    return output


def _policy_candidate(
    candidate: dict[str, Any],
    rows: list[dict],
    events: tuple[int, ...],
) -> dict[str, Any]:
    solution = _solve(
        rows,
        list(events),
        initial_squad={int(element) for element in candidate["selected"]},
    )
    output = dict(candidate)
    output["planned_squads"] = {
        str(event): list(solution["planned_squads"][event]) for event in events
    }
    output["lineups"] = {str(event): dict(solution["lineups"][event]) for event in events}
    output["transfer_policy"] = {
        str(event): {
            "available": plan["available"],
            "used": plan["used"],
            "in": [
                {
                    "element": element,
                    "name": solution["player_meta"][element]["player_name"],
                }
                for element in plan["in"]
            ],
            "out": [
                {
                    "element": element,
                    "name": solution["player_meta"][element]["player_name"],
                }
                for element in plan["out"]
            ],
        }
        for event, plan in solution["transfers"].items()
    }
    output["policy_objective"] = float(solution["objective"])
    return output


def _finalist_candidates(
    candidates: list[dict[str, Any]], selection_metrics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    metric_by_id = {row["candidate_id"]: row for row in selection_metrics}
    ranked = sorted(selection_metrics, key=lambda row: row["mean_points"], reverse=True)
    selected_ids = [row["candidate_id"] for row in ranked[:10]]
    if "S001" not in selected_ids:
        selected_ids.append("S001")
    for premium in ("Haaland", "Saka", "Palmer", "Isak"):
        eligible = [
            candidate
            for candidate in candidates
            if any(
                player["name"] == premium and player["element"] in set(candidate["premium_players"])
                for player in candidate["players"]
            )
        ]
        if eligible:
            best = max(
                eligible,
                key=lambda candidate: metric_by_id[candidate["candidate_id"]]["mean_points"],
            )
            selected_ids.append(best["candidate_id"])
    bench_bands = (
        lambda value: value <= 18.5,
        lambda value: 18.5 < value <= 20.0,
        lambda value: 20.0 < value <= 22.0,
        lambda value: value > 22.0,
    )
    for in_band in bench_bands:
        eligible = [
            candidate for candidate in candidates if in_band(float(candidate["gw1_bench_spend"]))
        ]
        if eligible:
            best = max(
                eligible,
                key=lambda candidate: metric_by_id[candidate["candidate_id"]]["mean_points"],
            )
            selected_ids.append(best["candidate_id"])
    deduplicated = list(dict.fromkeys(selected_ids))
    return [by_id[candidate_id] for candidate_id in deduplicated]


def _policy_recovery_delta_cell(
    policy_result_by_id: dict[str, dict[str, Any]], candidate_id: str
) -> str:
    """Render policy evidence without pretending every diagnostic squad was a finalist."""
    policy = policy_result_by_id.get(candidate_id)
    if policy is None:
        return "—"
    return f"{float(policy['recovery_mean_delta_to_primary']):+.2f}"


def _render_report(result: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    metrics = result["holdout_metrics"]
    ranked = sorted(metrics, key=lambda row: row["base_mean_points"], reverse=True)
    policy_result_by_id = {row["candidate_id"]: row for row in result["policy_finalist_metrics"]}
    current = next(row for row in metrics if row["archetype"] == "current-transfer-aware")
    best = ranked[0]
    policy_leader = max(result["policy_finalist_metrics"], key=lambda row: row["base_mean_points"])
    policy_label = (
        "the current squad"
        if policy_leader["candidate_id"] == current["candidate_id"]
        else policy_leader["archetype"]
    )
    bench_groups: dict[str, list[dict]] = defaultdict(list)
    for row in metrics:
        spend = float(row["gw1_bench_spend"])
        label = (
            "≤£18.5m"
            if spend <= 18.5
            else "£18.6–20.0m"
            if spend <= 20
            else "£20.1–22.0m"
            if spend <= 22
            else ">£22.0m"
        )
        bench_groups[label].append(row)
    lines = [
        "# GW1–5 squad survival tournament",
        "",
        f"**Run:** {result['created_at']}  ",
        (
            f"**Engine:** `{TOURNAMENT_VERSION}` · **Candidates:** {len(candidates)} · "
            f"**Selection simulations:** {result['selection_simulations']:,} · "
            f"**Holdout simulations:** {result['holdout_simulations']:,} per scenario"
        ),
        "",
        "## Verdict",
        "",
        (
            f"The current squad ranks **{ranked.index(current) + 1}/{len(ranked)}** by base-scenario "
            f"mean points. The holdout leader is **{best['candidate_id']}** "
            f"({best['archetype']}) at {best['base_mean_points']:.2f} points versus "
            f"{current['base_mean_points']:.2f} for the current squad—a paired "
            f"{best['base_mean_delta_to_primary']:+.2f}-point difference over five gameweeks."
        ),
        "",
        (
            f"The recommendation is **{policy_leader['candidate_id']} ({policy_label})**: "
            f"with equal free-transfer access it leads the finalist holdout at "
            f"{policy_leader['base_mean_points']:.2f} points, "
            f"{policy_leader['base_mean_points'] - max(row['base_mean_points'] for row in result['policy_finalist_metrics'] if row['candidate_id'] != policy_leader['candidate_id']):.2f} "
            "ahead of the next route."
        ),
        "",
        (
            "The knockout is a diagnostic view: after each gameweek it removes the bottom half by "
            "cumulative score (128→64→32→16→8→4), then crowns the highest-scoring finalist. The "
            "recommendation is not selected from one bracket; it uses repeated holdout distributions."
        ),
        "",
        "## Holdout top ten — base forecast",
        "",
        "| Rank | ID | Archetype | Premiums | Bench | Mean | P10 | P90 | Top 10 | Champion | Δ current |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rank, row in enumerate(ranked[:10], start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['archetype']} | "
            f"{row['premium_names'] or '—'} | £{row['gw1_bench_spend']:.1f}m | "
            f"{row['base_mean_points']:.2f} | {row['base_p10_points']:.0f} | "
            f"{row['base_p90_points']:.0f} | {row['base_top_10_probability']:.1%} | "
            f"{row['base_champion_probability']:.1%} | "
            f"{row['base_mean_delta_to_primary']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Premium recovery stress",
            "",
            (
                "This second holdout raises play probability to at least 86% for available, highly "
                "owned £9.0m+ midfielders/forwards returning from a 60+ day break. It is a generic "
                "counterfactual, not a name-based boost."
            ),
            "",
            "| Rank | ID | Premiums | Base mean | Recovery mean | Recovery Δ current |",
            "| ---: | --- | --- | ---: | ---: | ---: |",
        ]
    )
    recovery_ranked = sorted(metrics, key=lambda row: row["recovery_mean_points"], reverse=True)
    for rank, row in enumerate(recovery_ranked[:10], start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['premium_names'] or '—'} | "
            f"{row['base_mean_points']:.2f} | {row['recovery_mean_points']:.2f} | "
            f"{row['recovery_mean_delta_to_primary']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "### Best named premium challengers",
            "",
            "| Premium | ID | Bench | Base rank | Base Δ | Recovery rank | Recovery Δ | Policy recovery Δ |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for premium in ("Haaland", "Saka", "Palmer", "Isak"):
        eligible = [row for row in metrics if premium in row["premium_names"].split(", ")]
        challenger = max(eligible, key=lambda row: row["recovery_mean_points"])
        policy_delta = _policy_recovery_delta_cell(
            policy_result_by_id, challenger["candidate_id"]
        )
        lines.append(
            f"| {premium} | {challenger['candidate_id']} | "
            f"£{challenger['gw1_bench_spend']:.1f}m | "
            f"{ranked.index(challenger) + 1} | "
            f"{challenger['base_mean_delta_to_primary']:+.2f} | "
            f"{recovery_ranked.index(challenger) + 1} | "
            f"{challenger['recovery_mean_delta_to_primary']:+.2f} | "
            f"{policy_delta} |"
        )
    appearance_ranked = sorted(metrics, key=lambda row: row["appearance_mean_points"], reverse=True)
    appearance_info = result["appearance_calibration"]
    lines.extend(
        [
            "",
            "## Appearance-risk stress",
            "",
            (
                "The raw model is well calibrated overall, but its 80%+ play probabilities are "
                "conservative in the rolling out-of-fold sample. This scenario applies a "
                "position-specific isotonic reliability map while preserving every player's xP; "
                "it changes only DNP/autosub risk."
            ),
            "",
            "| Rank | ID | Bench | Base mean | Calibrated mean | Calibrated Δ current |",
            "| ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for rank, row in enumerate(appearance_ranked[:10], start=1):
        lines.append(
            f"| {rank} | {row['candidate_id']} | £{row['gw1_bench_spend']:.1f}m | "
            f"{row['base_mean_points']:.2f} | {row['appearance_mean_points']:.2f} | "
            f"{row['appearance_mean_delta_to_primary']:+.2f} |"
        )
    lines.extend(
        [
            "",
            (
                "The reliability map changes play probability by "
                f"{appearance_info['mean_probability_change']:+.3f} on average across the live "
                "forecast rows; expected points are held constant."
            ),
        ]
    )
    policy_metrics = sorted(
        result["policy_finalist_metrics"],
        key=lambda row: row["base_mean_points"],
        reverse=True,
    )
    lines.extend(
        [
            "",
            "## Transfer-aware finalist holdout",
            "",
            (
                "The selection top ten plus the best premium and bench-band challengers get an "
                "equal free-transfer planning envelope. These are deterministic preseason routes, "
                "not claims that we would ignore new information at future deadlines."
            ),
            "",
            "| Rank | ID | Premiums | Fixed mean | Policy mean | P10 | Top 3 | Δ current policy |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    fixed_by_id = {row["candidate_id"]: row for row in metrics}
    for rank, row in enumerate(policy_metrics, start=1):
        fixed = fixed_by_id[row["candidate_id"]]
        lines.append(
            f"| {rank} | {row['candidate_id']} | {row['premium_names'] or '—'} | "
            f"{fixed['base_mean_points']:.2f} | {row['base_mean_points']:.2f} | "
            f"{row['base_p10_points']:.0f} | {row['base_top_3_probability']:.1%} | "
            f"{row['base_mean_delta_to_primary']:+.2f} |"
        )
    policy_details = {item["candidate_id"]: item for item in result["policy_finalists"]}
    policy_leader = policy_metrics[0]
    leader_transfers = policy_details[policy_leader["candidate_id"]]["base_transfer_policy"]
    lines.extend(
        [
            "",
            f"**{policy_leader['candidate_id']} planned route:**",
            "",
        ]
    )
    for event, plan in leader_transfers.items():
        inbound = ", ".join(item["name"] for item in plan["in"]) or "roll"
        outbound = ", ".join(item["name"] for item in plan["out"]) or "—"
        lines.append(
            f"- GW{event}: {outbound} → {inbound} "
            f"({plan['used']}/{plan['available']} free transfers used)"
        )
    evidence = result["historical_bench_evidence"]
    lines.extend(
        [
            "",
            "## Bench-spend interrogation",
            "",
            (
                f"The current candidate spends **£{current['gw1_bench_spend']:.1f}m** on its GW1 bench. "
                f"The 2019/20 eventual top ten averaged **£{evidence['gameweeks'][0]['mean_bench_spend']:.2f}m** "
                "in GW1 (range "
                f"£{evidence['gameweeks'][0]['minimum_bench_spend']:.1f}m–"
                f"£{evidence['gameweeks'][0]['maximum_bench_spend']:.1f}m). This is only ten "
                "survivorship-selected managers under older prices/rules, so it is a warning flag, "
                "not a target."
            ),
            "",
            (
                "| GW1 bench band | Candidates | Best base | Group base | "
                "Best calibrated | Best ID |"
            ),
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for label in ("≤£18.5m", "£18.6–20.0m", "£20.1–22.0m", ">£22.0m"):
        group = bench_groups.get(label, [])
        if not group:
            continue
        group_best = max(group, key=lambda row: row["base_mean_points"])
        calibrated_best = max(group, key=lambda row: row["appearance_mean_points"])
        lines.append(
            f"| {label} | {len(group)} | {group_best['base_mean_points']:.2f} | "
            f"{np.mean([row['base_mean_points'] for row in group]):.2f} | "
            f"{calibrated_best['appearance_mean_points']:.2f} | "
            f"{group_best['candidate_id']} |"
        )
    lines.extend(
        [
            "",
            "## Fixed-squad leader detail",
            "",
            (
                f"**{best['candidate_id']} · {best['archetype']} · £{best['budget_spent']:.1f}m spent · "
                f"£{best['gw1_bench_spend']:.1f}m bench**"
            ),
            "",
            "| Pos | Player | Club | Price | GW1 role |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    best_candidate = by_id[best["candidate_id"]]
    best_lineup = best_candidate["lineups"]["1"]
    starter_ids = set(best_lineup["starters"])
    bench_order = {
        int(element): index + 1 for index, element in enumerate(best_lineup["bench_order"])
    }
    for player in best_candidate["players"]:
        role = (
            "Starter"
            if player["element"] in starter_ids
            else f"Bench {bench_order[player['element']]}"
        )
        if player["element"] == best_lineup["captain"]:
            role = "Captain"
        elif player["element"] == best_lineup["vice_captain"]:
            role = "Vice-captain"
        lines.append(
            f"| {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {role} |"
        )
    calibration = result["calibration"]
    diagnostics = result["simulation_diagnostics"]["base_holdout"]
    diversity = result["candidate_diversity"]
    distribution_backtest = result["distribution_backtest"]
    lines.extend(
        [
            "",
            "## Tournament integrity checks",
            "",
            (
                f"The field contains {diversity['unique_squads']} unique squads and "
                f"{diversity['unique_players']} different players. Pairwise squads overlap by "
                f"{diversity['mean_pair_player_overlap']:.1f}/15 players on average "
                f"(range {diversity['minimum_pair_player_overlap']}–"
                f"{diversity['maximum_pair_player_overlap']}). Selection-versus-holdout rank "
                f"correlation is {result['selection_holdout_rank_correlation']:.3f}."
            ),
            "",
            (
                f"Across the {diagnostics['simulated_players']:.0f} players used by the field, "
                f"holdout simulated means differ from forecast xP by "
                f"{diagnostics['player_mean_bias']:+.3f} points on average "
                f"(absolute calibration error {diagnostics['player_mean_absolute_calibration_error']:.3f}). "
                f"Appearance-rate bias is {diagnostics['appearance_mean_bias']:+.4f}. GW1 point "
                f"correlation averages {diagnostics['same_team_gw1_points_correlation']:.3f} for "
                f"same-team pairs versus {diagnostics['other_team_gw1_points_correlation']:.3f} "
                "for different teams."
            ),
            "",
            (
                f"The season-forward marginal distribution replay covers "
                f"{distribution_backtest['rows']:,} player/gameweeks in 2024/25 and 2025/26. "
                f"Its nominal 10th–90th interval contains "
                f"{distribution_backtest['weighted_p10_p90_coverage']:.1%} of realised scores, "
                f"with {distribution_backtest['weighted_mean_bias']:+.3f} mean-point bias."
            ),
            "",
            "## What the simulation models",
            "",
            (
                f"- {calibration['played_rows']:,} historical played player/gameweeks calibrate "
                "conditional score residuals, split by position and forecast-strength quintile."
            ),
            (
                f"- {calibration['fixtures']:,} historical fixtures supply paired home/away, "
                "position-specific shocks; gameweek shocks correlate the whole slate."
            ),
            (
                "- Residual dispersion scales by position "
                f"({', '.join(f'{key} {value:.2f}' for key, value in calibration['residual_scale_by_position'].items())}), "
                "selected on 2024/25 interval coverage and checked forward on 2025/26."
            ),
            (
                "- A calibrated Gaussian copula carries player appearance risk across adjacent weeks; "
                "a separate persistent residual carries part of player-level forecast error."
            ),
            (
                "- Every squad uses its forecast-best legal XI, captain and vice each week. Realised "
                "DNPs invoke formation-valid autosubs and captain-to-vice fallback."
            ),
            (
                "- Player prices and the initial 15 are fixed for this five-week contest. That isolates "
                "the initial squad decision; transfers and price moves require a separate policy tournament."
            ),
            "",
            "## Limits that still matter",
            "",
            (
                "This is a correlated residual simulator, not yet a goal/assist/clean-sheet component "
                "model. It preserves historical match-level covariance in aggregate but cannot enforce "
                "every football identity (for example, a conceded goal simultaneously erasing every "
                "defender's clean sheet). The premium-recovery stress is intentionally separate from the "
                "base forecast. Candidate discovery and holdout use independent random seeds, but both "
                "ultimately depend on the same forecast and residual assumptions."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_tournament(
    *,
    candidate_count: int = 128,
    selection_simulations: int = 5_000,
    holdout_simulations: int = 25_000,
    seed: int = 20260802,
) -> dict[str, Any]:
    ensure_engine_layout()
    TOURNAMENT_DIR.mkdir(parents=True, exist_ok=True)
    payload = generate_candidates(candidate_count, DEFAULT_EVENTS, seed)
    candidates = payload["candidates"]
    rows, loaded = _load_rows(DEFAULT_EVENTS)
    by_player = loaded["by_player"]
    meta = loaded["meta"]
    rules = load_rules()
    for candidate in candidates:
        squad_rows = [meta[int(element)] for element in candidate["selected"]]
        validate_squad(squad_rows, rules)
        for event in DEFAULT_EVENTS:
            lineup = candidate["lineups"][str(event)]
            validate_lineup(
                squad_rows,
                lineup["starters"],
                lineup["bench_order"],
                lineup["captain"],
                lineup["vice_captain"],
                rules,
            )
    calibration = calibrate_residuals()
    distribution_backtest = backtest_marginal_distribution(seed + 77)

    selection_metrics, _, selection_diagnostics = _run_scenario(
        candidates,
        DEFAULT_EVENTS,
        by_player,
        meta,
        calibration,
        selection_simulations,
        seed + 101,
    )
    # We report all 128 on the untouched holdout. The selection run is retained to
    # quantify rank stability rather than silently tuning simulation seeds.
    base_metrics, _, base_diagnostics = _run_scenario(
        candidates,
        DEFAULT_EVENTS,
        by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )

    recovery_rows = _premium_recovery_rows(rows)
    recovery_by_player: dict[int, dict[int, dict]] = defaultdict(dict)
    for row in recovery_rows:
        recovery_by_player[int(row["element"])][int(row["event_number"])] = row
    recovery_candidates = []
    for candidate in candidates:
        recovered = dict(candidate)
        selected = [int(element) for element in candidate["selected"]]
        recovered["lineups"] = {
            str(event): _lineup_for_squad(selected, event, recovery_by_player, rules)
            for event in DEFAULT_EVENTS
        }
        recovery_candidates.append(recovered)
    recovery_metrics, _, recovery_diagnostics = _run_scenario(
        recovery_candidates,
        DEFAULT_EVENTS,
        recovery_by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )
    appearance_rows, appearance_calibration = _appearance_calibrated_rows(rows)
    appearance_by_player: dict[int, dict[int, dict]] = defaultdict(dict)
    for row in appearance_rows:
        appearance_by_player[int(row["element"])][int(row["event_number"])] = row
    appearance_metrics, _, appearance_diagnostics = _run_scenario(
        candidates,
        DEFAULT_EVENTS,
        appearance_by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )
    finalists = _finalist_candidates(candidates, selection_metrics)
    base_policy_candidates = [
        _policy_candidate(candidate, rows, DEFAULT_EVENTS) for candidate in finalists
    ]
    recovery_policy_candidates = [
        _policy_candidate(candidate, recovery_rows, DEFAULT_EVENTS) for candidate in finalists
    ]
    base_policy_metrics, _, base_policy_diagnostics = _run_scenario(
        base_policy_candidates,
        DEFAULT_EVENTS,
        by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )
    recovery_policy_metrics, _, recovery_policy_diagnostics = _run_scenario(
        recovery_policy_candidates,
        DEFAULT_EVENTS,
        recovery_by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )
    appearance_policy_metrics, _, appearance_policy_diagnostics = _run_scenario(
        base_policy_candidates,
        DEFAULT_EVENTS,
        appearance_by_player,
        meta,
        calibration,
        holdout_simulations,
        seed + 202,
    )
    policy_merged = _merge_candidate_metrics(
        base_policy_candidates,
        base_policy_metrics,
        recovery_policy_metrics,
        appearance_policy_metrics,
    )
    merged = _merge_candidate_metrics(
        candidates, base_metrics, recovery_metrics, appearance_metrics
    )
    selection_rank = {
        row["candidate_id"]: rank
        for rank, row in enumerate(
            sorted(selection_metrics, key=lambda item: item["mean_points"], reverse=True),
            start=1,
        )
    }
    holdout_rank = {
        row["candidate_id"]: rank
        for rank, row in enumerate(
            sorted(merged, key=lambda item: item["base_mean_points"], reverse=True),
            start=1,
        )
    }
    for row in merged:
        row["selection_rank"] = selection_rank[row["candidate_id"]]
        row["holdout_rank"] = holdout_rank[row["candidate_id"]]
    rank_correlation = float(
        np.corrcoef(
            [row["selection_rank"] for row in merged],
            [row["holdout_rank"] for row in merged],
        )[0, 1]
    )
    squad_sets = [{int(element) for element in candidate["selected"]} for candidate in candidates]
    pair_overlaps = [len(left & right) for left, right in combinations(squad_sets, 2)]
    primary_set = squad_sets[0]
    candidate_diversity = {
        "unique_squads": len({frozenset(squad) for squad in squad_sets}),
        "unique_players": len(set().union(*squad_sets)),
        "mean_pair_player_overlap": float(np.mean(pair_overlaps)),
        "minimum_pair_player_overlap": int(min(pair_overlaps)),
        "maximum_pair_player_overlap": int(max(pair_overlaps)),
        "mean_primary_player_retention": float(
            np.mean([len(primary_set & squad) / 15.0 for squad in squad_sets[1:]])
        ),
    }
    policy_order = sorted(policy_merged, key=lambda row: row["base_mean_points"], reverse=True)
    fixed_order = sorted(merged, key=lambda row: row["base_mean_points"], reverse=True)
    result = {
        "version": 1,
        "engine": TOURNAMENT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "selection_simulations": selection_simulations,
        "holdout_simulations": holdout_simulations,
        "selection_holdout_rank_correlation": rank_correlation,
        "candidate_diversity": candidate_diversity,
        "recommendation": {
            "candidate_id": policy_order[0]["candidate_id"],
            "basis": "transfer-aware holdout mean points",
            "policy_mean_points": policy_order[0]["base_mean_points"],
            "edge_over_policy_runner_up": (
                policy_order[0]["base_mean_points"] - policy_order[1]["base_mean_points"]
            ),
            "fixed_squad_leader": fixed_order[0]["candidate_id"],
            "provisional_until_deadline_refresh": True,
        },
        "candidate_sha256": sha256_file(CANDIDATES_JSON),
        "forecast_sha256": sha256_file(CURRENT_FORECAST),
        "model_sha256": sha256_file(MODEL_FILE),
        "calibration": {
            "rows": calibration.rows,
            "played_rows": calibration.played_rows,
            "fixtures": calibration.fixtures,
            "play_rho": calibration.play_rho,
            "points_rho": calibration.points_rho,
            "residual_scale_by_position": RESIDUAL_SCALE_BY_POSITION,
            "global_shock_sd": calibration.global_sd,
            "fixture_shock_sd": calibration.fixture_sd,
            "idiosyncratic_sd": calibration.idiosyncratic_sd,
        },
        "distribution_backtest": distribution_backtest,
        "simulation_diagnostics": {
            "selection": selection_diagnostics,
            "base_holdout": base_diagnostics,
            "premium_recovery_holdout": recovery_diagnostics,
            "appearance_calibrated_holdout": appearance_diagnostics,
            "base_policy_holdout": base_policy_diagnostics,
            "premium_recovery_policy_holdout": recovery_policy_diagnostics,
            "appearance_calibrated_policy_holdout": appearance_policy_diagnostics,
        },
        "appearance_calibration": appearance_calibration,
        "historical_bench_evidence": _historical_bench_evidence(),
        "selection_metrics": selection_metrics,
        "holdout_metrics": merged,
        "policy_finalist_metrics": policy_merged,
        "policy_finalists": [
            {
                "candidate_id": base["candidate_id"],
                "base_transfer_policy": base["transfer_policy"],
                "premium_recovery_transfer_policy": recovery["transfer_policy"],
            }
            for base, recovery in zip(
                base_policy_candidates, recovery_policy_candidates, strict=True
            )
        ],
        "assumptions": [
            "The starting squad is held fixed through GW5 to isolate initial construction.",
            "Lineups and captaincy re-optimize from the current forecast each gameweek.",
            "Historical residual blocks approximate match and gameweek correlation.",
            "No chips, transfers, price changes or post-snapshot news are simulated.",
            "The premium-recovery scenario is a separate generic sensitivity test.",
            "The appearance-calibrated scenario preserves player expected points.",
        ],
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    table_rows = []
    for row in merged:
        table_rows.append(
            {
                key: value
                for key, value in row.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
        )
    pq.write_table(pa.Table.from_pylist(table_rows), RESULTS_PARQUET, compression="zstd")
    REPORT.write_text(_render_report(result, candidates), encoding="utf-8")
    return result
