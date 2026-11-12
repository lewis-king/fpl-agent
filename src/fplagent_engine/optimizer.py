from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import highspy
import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.paths import PROCESSED

from .acceleration import policy_worker_count
from .paths import ARTIFACTS, DECISIONS, FORECASTS, REPORTS, ensure_engine_layout
from .rules import SquadRules, load_rules, validate_lineup, validate_squad

MODEL_FILE = ARTIFACTS / "forecast_v2" / "models.joblib"
CURRENT_FORECAST = FORECASTS / "2026-27-preseason.parquet"
DECISION_JSON = DECISIONS / "2026-27-gw1-initial-squad.json"
DECISION_REPORT = REPORTS / "gw1-initial-squad.md"

POSITION_SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
DEFAULT_HORIZON_DECAY = 0.88
BENCH_AUTOSUB_WEIGHT = 0.08


def _weights(events: list[int], decay: float = DEFAULT_HORIZON_DECAY) -> dict[int, float]:
    if not 0.0 < decay <= 1.0:
        raise ValueError("horizon decay must be in (0, 1]")
    return {event: decay ** (event - min(events)) for event in events}


def _next_free_transfer_bank(available: int, used: int, maximum: int) -> int:
    if available < 1 or maximum < 1 or not 0 <= used <= available:
        raise ValueError("invalid free-transfer state")
    return min(maximum, available - used + 1)


def _player_rows(path: Path = CURRENT_FORECAST) -> tuple[list[dict], list[int]]:
    rows = pq.read_table(path).to_pylist()
    events = sorted({int(row["event_number"]) for row in rows})
    return rows, events


def _solve(
    rows: list[dict],
    events: list[int],
    *,
    score_by_row: np.ndarray | None = None,
    exclude_squad: set[int] | None = None,
    initial_squad: set[int] | None = None,
    horizon_decay: float = DEFAULT_HORIZON_DECAY,
    bench_autosub_weight: float = BENCH_AUTOSUB_WEIGHT,
    gw1_bench_spend: tuple[float | None, float | None] | None = None,
    gw1_defenders: int | None = None,
    forbid_transfer_events: set[int] | None = None,
    required_players: set[int] | None = None,
    excluded_players: set[int] | None = None,
    club_minimums: dict[int, int] | None = None,
    initial_club_counts: dict[int, int] | None = None,
    rules: SquadRules | None = None,
    highs_threads: int | None = None,
) -> dict[str, Any]:
    if not 0.0 <= bench_autosub_weight <= 1.0:
        raise ValueError("bench_autosub_weight must be in [0, 1]")
    if gw1_defenders is not None and gw1_defenders not in {3, 4, 5}:
        raise ValueError("gw1_defenders must be 3, 4, or 5")
    forbidden_transfers = set(forbid_transfer_events or set())
    required = set(required_players or set())
    excluded = set(excluded_players or set())
    minimums = dict(club_minimums or {})
    exact_counts = dict(initial_club_counts or {})
    if required & excluded:
        raise ValueError("required_players and excluded_players must not overlap")
    if any(count < 1 or count > 3 for count in minimums.values()):
        raise ValueError("club minimums must be between 1 and 3")
    if any(count < 0 or count > 3 for count in exact_counts.values()):
        raise ValueError("initial club counts must be between 0 and 3")
    if any(
        team_id in minimums and minimums[team_id] > count
        for team_id, count in exact_counts.items()
    ):
        raise ValueError("initial club counts must satisfy club minimums")
    invalid_forbidden = forbidden_transfers - set(events[1:])
    if invalid_forbidden:
        raise ValueError(
            f"forbid_transfer_events must be later events in the horizon: {invalid_forbidden}"
        )
    by_player: dict[int, dict[int, dict]] = defaultdict(dict)
    player_meta: dict[int, dict] = {}
    for index, row in enumerate(rows):
        element = int(row["element"])
        event = int(row["event_number"])
        enriched = dict(row)
        if score_by_row is not None:
            enriched["optimization_points"] = float(score_by_row[index])
        else:
            enriched["optimization_points"] = float(row["expected_points"])
        by_player[element][event] = enriched
        player_meta[element] = row
    players = sorted(by_player)
    unknown_constraints = (required | excluded) - set(players)
    if unknown_constraints:
        raise ValueError(
            f"constrained players are not available in the forecast: {sorted(unknown_constraints)}"
        )
    player_index = {element: index for index, element in enumerate(players)}
    event_index = {event: index for index, event in enumerate(events)}
    n_players = len(players)
    n_events = len(events)

    rules = rules or load_rules()
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("random_seed", 7)
    highs.setOptionValue("mip_rel_gap", 1e-7)
    highs.setOptionValue("time_limit", 120.0)
    if highs_threads is not None:
        if highs_threads < 1:
            raise ValueError("highs_threads must be positive")
        highs.setOptionValue("threads", int(highs_threads))
    integer = highspy.HighsVarType.kInteger
    squad = highs.addVariables(n_players * n_events, lb=0, ub=1, type=integer, out_array=True)
    start = highs.addVariables(n_players * n_events, lb=0, ub=1, type=integer, out_array=True)
    captain = highs.addVariables(n_players * n_events, lb=0, ub=1, type=integer, out_array=True)
    transfer_events = events[1:]
    transfer_in = highs.addVariables(
        n_players * len(transfer_events), lb=0, ub=1, type=integer, out_array=True
    )
    free_transfer_bank = highs.addVariables(
        len(transfer_events),
        lb=1,
        ub=rules.max_free_transfers,
        type=integer,
        out_array=True,
    )

    def squad_var(element: int, event: int):
        return squad[player_index[element] * n_events + event_index[event]]

    def start_var(element: int, event: int):
        return start[player_index[element] * n_events + event_index[event]]

    def captain_var(element: int, event: int):
        return captain[player_index[element] * n_events + event_index[event]]

    def transfer_var(element: int, event: int):
        transfer_index = transfer_events.index(event)
        return transfer_in[player_index[element] * len(transfer_events) + transfer_index]

    team_ids = sorted({int(player_meta[element]["team_id"]) for element in players})
    for event in events:
        highs.addConstr(
            sum(squad_var(element, event) for element in players) == rules.squad_size,
            name=f"squad_size_{event}",
        )
        for position, count in rules.squad_positions.items():
            highs.addConstr(
                sum(
                    squad_var(element, event)
                    for element in players
                    if player_meta[element]["position"] == position
                )
                == count,
                name=f"squad_{position.lower()}_{event}",
            )
        for team_id in team_ids:
            highs.addConstr(
                sum(
                    squad_var(element, event)
                    for element in players
                    if int(player_meta[element]["team_id"]) == team_id
                )
                <= rules.club_limit,
                name=f"club_{team_id}_{event}",
            )
        highs.addConstr(
            sum(
                float(player_meta[element]["market_price"]) * squad_var(element, event)
                for element in players
            )
            <= rules.budget,
            name=f"budget_{event}",
        )
        highs.addConstr(
            sum(start_var(element, event) for element in players) == rules.starting_size,
            name=f"starters_{event}",
        )
        highs.addConstr(
            sum(captain_var(element, event) for element in players) == 1,
            name=f"captain_{event}",
        )
        for element in players:
            highs.addConstr(start_var(element, event) <= squad_var(element, event))
            highs.addConstr(captain_var(element, event) <= start_var(element, event))
        for position in rules.squad_positions:
            starters_at_position = sum(
                start_var(element, event)
                for element in players
                if player_meta[element]["position"] == position
            )
            highs.addConstr(
                starters_at_position >= rules.minimum_starters[position],
                name=f"minimum_{position.lower()}_{event}",
            )
            highs.addConstr(
                starters_at_position <= rules.maximum_starters[position],
                name=f"maximum_{position.lower()}_{event}",
            )

    first_event = events[0]
    for element in required:
        highs.addConstr(
            squad_var(element, first_event) == 1,
            name=f"required_initial_player_{element}",
        )
    for element in excluded:
        highs.addConstr(
            squad_var(element, first_event) == 0,
            name=f"excluded_initial_player_{element}",
        )
    for team_id, count in minimums.items():
        if team_id not in team_ids:
            raise ValueError(f"club minimum references unknown team {team_id}")
        highs.addConstr(
            sum(
                squad_var(element, first_event)
                for element in players
                if int(player_meta[element]["team_id"]) == team_id
            )
            >= count,
            name=f"minimum_initial_club_{team_id}",
        )
    for team_id, count in exact_counts.items():
        if team_id not in team_ids:
            raise ValueError(f"initial club count references unknown team {team_id}")
        highs.addConstr(
            sum(
                squad_var(element, first_event)
                for element in players
                if int(player_meta[element]["team_id"]) == team_id
            )
            == count,
            name=f"exact_initial_club_{team_id}",
        )
    if initial_squad is not None:
        if len(initial_squad) != rules.squad_size or not initial_squad <= set(players):
            raise ValueError("initial_squad must contain 15 forecasted players")
        for element in players:
            highs.addConstr(
                squad_var(element, first_event) == (1 if element in initial_squad else 0),
                name=f"fixed_initial_squad_{element}",
            )
    if exclude_squad:
        highs.addConstr(
            sum(
                squad_var(element, first_event)
                for element in exclude_squad
                if element in player_index
            )
            <= rules.squad_size - 1,
            name="different_initial_squad",
        )
    if gw1_bench_spend is not None:
        minimum_bench, maximum_bench = gw1_bench_spend
        bench_cost = sum(
            float(player_meta[element]["market_price"])
            * (squad_var(element, first_event) - start_var(element, first_event))
            for element in players
        )
        if minimum_bench is not None:
            highs.addConstr(
                bench_cost >= minimum_bench,
                name="minimum_gw1_bench_spend",
            )
        if maximum_bench is not None:
            highs.addConstr(
                bench_cost <= maximum_bench,
                name="maximum_gw1_bench_spend",
            )
    if gw1_defenders is not None:
        highs.addConstr(
            sum(
                start_var(element, first_event)
                for element in players
                if player_meta[element]["position"] == "DEF"
            )
            == gw1_defenders,
            name="gw1_defender_count",
        )

    if transfer_events:
        highs.addConstr(free_transfer_bank[0] == 1, name="initial_free_transfer")
    for transfer_index, event in enumerate(transfer_events):
        previous_event = events[event_index[event] - 1]
        for element in players:
            transfer = transfer_var(element, event)
            highs.addConstr(
                transfer >= squad_var(element, event) - squad_var(element, previous_event)
            )
            highs.addConstr(transfer <= squad_var(element, event))
            highs.addConstr(transfer <= 1 - squad_var(element, previous_event))
        transfers_used = sum(transfer_var(element, event) for element in players)
        if event in forbidden_transfers:
            highs.addConstr(
                transfers_used == 0,
                name=f"forbid_transfers_{event}",
            )
        highs.addConstr(
            transfers_used <= free_transfer_bank[transfer_index],
            name=f"free_transfer_limit_{event}",
        )
        if transfer_index + 1 < len(transfer_events):
            highs.addConstr(
                free_transfer_bank[transfer_index + 1]
                <= free_transfer_bank[transfer_index] - transfers_used + 1,
                name=f"free_transfer_rollover_{event}",
            )

    horizon_weights = _weights(events, horizon_decay)
    objective = 0
    for element in players:
        for event in events:
            points = by_player[element][event]["optimization_points"]
            weight = horizon_weights[event]
            objective += weight * points * start_var(element, event)
            objective += weight * points * captain_var(element, event)
            objective += (
                bench_autosub_weight
                * weight
                * points
                * (squad_var(element, event) - start_var(element, event))
            )
    if transfer_events:
        objective -= 1e-6 * sum(transfer_in)
    highs.maximize(objective)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"HiGHS did not return an optimal squad: {highs.getModelStatus()}")

    planned_squads = {
        event: [element for element in players if highs.val(squad_var(element, event)) > 0.5]
        for event in events
    }
    selected = planned_squads[first_event]
    lineups = {}
    for event in events:
        event_squad = planned_squads[event]
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
        bench = [element for element in event_squad if element not in starters]
        reserve_goalkeepers = [
            element for element in bench if player_meta[element]["position"] == "GK"
        ]
        outfield_bench = sorted(
            (element for element in bench if player_meta[element]["position"] != "GK"),
            key=lambda element: (
                float(by_player[element][event]["expected_points"]),
                float(by_player[element][event]["p_play"]),
            ),
            reverse=True,
        )
        expected = sum(
            float(by_player[element][event]["expected_points"]) for element in starters
        ) + float(by_player[captain_id][event]["expected_points"])
        lineups[event] = {
            "starters": starters,
            "captain": captain_id,
            "vice_captain": vice_id,
            "bench_order": outfield_bench + reserve_goalkeepers,
            "expected_points": expected,
            "formation": "-".join(
                str(sum(player_meta[element]["position"] == position for element in starters))
                for position in ("DEF", "MID", "FWD")
            ),
        }

    transfers = {}
    available = 1
    for event in transfer_events:
        previous_event = events[event_index[event] - 1]
        inbound = sorted(set(planned_squads[event]) - set(planned_squads[previous_event]))
        outbound = sorted(set(planned_squads[previous_event]) - set(planned_squads[event]))
        if len(inbound) > available:
            raise RuntimeError(f"Transfer plan exceeds the free-transfer bank in GW{event}")
        transfers[event] = {
            "available": available,
            "used": len(inbound),
            "in": inbound,
            "out": outbound,
        }
        available = _next_free_transfer_bank(available, len(inbound), rules.max_free_transfers)

    return {
        "objective": float(highs.getObjectiveValue()),
        "selected": selected,
        "planned_squads": planned_squads,
        "transfers": transfers,
        "lineups": lineups,
        "player_meta": player_meta,
        "by_player": by_player,
        "budget": sum(float(player_meta[element]["market_price"]) for element in selected),
        "weights": horizon_weights,
        "horizon_decay": horizon_decay,
        "max_free_transfers": rules.max_free_transfers,
        "forbid_transfer_events": sorted(forbidden_transfers),
    }


def _player_item(solution: dict[str, Any], element: int, event: int = 1) -> dict[str, Any]:
    meta = solution["player_meta"][element]
    forecast = solution["by_player"][element][event]
    return {
        "element": element,
        "name": meta["player_name"],
        "team": meta["team_short_name"],
        "position": meta["position"],
        "price": float(meta["market_price"]) / 10.0,
        "expected_points": float(forecast["expected_points"]),
        "robust_points": float(forecast["robust_points"]),
        "p_play": float(forecast["p_play"]),
        "uncertainty": float(forecast["epistemic_uncertainty"]),
        "cold_start": bool(forecast["cold_start"]),
        "news": forecast.get("news") or "",
    }


_STABILITY_ROWS: list[dict] | None = None
_STABILITY_EVENTS: list[int] | None = None


def _init_stability_worker(rows: list[dict], events: list[int]) -> None:
    global _STABILITY_ROWS, _STABILITY_EVENTS
    _STABILITY_ROWS = rows
    _STABILITY_EVENTS = events


def _solve_stability_sample(score_by_row: np.ndarray) -> tuple[tuple[int, ...], int]:
    if _STABILITY_ROWS is None or _STABILITY_EVENTS is None:
        raise RuntimeError("stability worker was not initialized")
    solution = _solve(
        _STABILITY_ROWS,
        _STABILITY_EVENTS,
        score_by_row=score_by_row,
        highs_threads=1,
    )
    return tuple(solution["selected"]), int(solution["lineups"][1]["captain"])


def _stability(
    rows: list[dict], events: list[int], primary: dict[str, Any], samples: int
) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("stability samples must be positive")
    rng = np.random.default_rng(20260802)
    selection_count: Counter[int] = Counter()
    captain_count: Counter[int] = Counter()
    exact = 0
    perturbations = [
        np.asarray(
            [
                float(row["expected_points"])
                + rng.normal(0.0, max(float(row["epistemic_uncertainty"]), 0.05))
                for row in rows
            ],
            dtype=np.float64,
        )
        for _ in range(samples)
    ]
    workers = min(samples, policy_worker_count())
    if workers == 1:
        solved = []
        for perturbed in perturbations:
            # Reuse the parent process's existing HiGHS scheduler. HiGHS cannot
            # change its global thread count after a prior solve in-process.
            solution = _solve(rows, events, score_by_row=perturbed)
            solved.append(
                (tuple(solution["selected"]), int(solution["lineups"][1]["captain"]))
            )
    else:
        print(
            f"Initial squad: solving {samples} stability samples with {workers} workers",
            flush=True,
        )
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=get_context("spawn"),
            initializer=_init_stability_worker,
            initargs=(rows, events),
        ) as executor:
            solved = list(executor.map(_solve_stability_sample, perturbations, chunksize=1))

    primary_selected = set(primary["selected"])
    for selected_values, captain in solved:
        selected = set(selected_values)
        selection_count.update(selected)
        captain_count.update([captain])
        exact += selected == primary_selected
    return {
        "samples": samples,
        "exact_squad_rate": exact / samples,
        "mean_primary_player_retention": float(
            np.mean([selection_count[element] / samples for element in primary["selected"]])
        ),
        "gw1_captain_rate": captain_count[primary["lineups"][1]["captain"]] / samples,
        "player_selection_rate": {
            str(element): selection_count[element] / samples for element in primary["selected"]
        },
    }


def _horizon_sensitivity(
    rows: list[dict], events: list[int], primary: dict[str, Any]
) -> dict[str, Any]:
    primary_squad = set(primary["selected"])
    scenarios = {}
    for decay in (0.80, DEFAULT_HORIZON_DECAY, 0.95):
        solution = (
            primary if decay == DEFAULT_HORIZON_DECAY else _solve(rows, events, horizon_decay=decay)
        )
        selected = set(solution["selected"])
        scenarios[f"{decay:.2f}"] = {
            "initial_squad_retention": len(primary_squad & selected) / len(primary_squad),
            "gw1_captain": solution["lineups"][1]["captain"],
            "gw1_expected_points": solution["lineups"][1]["expected_points"],
            "planned_transfers": sum(item["used"] for item in solution["transfers"].values()),
        }
    return {
        "primary_decay": DEFAULT_HORIZON_DECAY,
        "scenarios": scenarios,
    }


def _render(receipt: dict[str, Any]) -> str:
    squad = receipt["squad"]
    lineup = receipt["gameweeks"]["1"]
    starter_ids = set(lineup["starters"])
    captain = lineup["captain"]
    vice = lineup["vice_captain"]
    lines = [
        "# FPLAgent initial squad — 2026/27 GW1",
        "",
        f"Generated {receipt['created_at']}. This is a {receipt['model_version']} decision receipt, ",
        "not a claim that the model has passed a full prospective season.",
        "",
        (
            f"**Budget:** £{receipt['budget_spent']:.1f}m · "
            f"**Bank:** £{receipt['bank']:.1f}m · "
            f"**GW1 expected points:** {lineup['expected_points']:.2f} · "
            f"**Formation:** {lineup['formation']}"
        ),
        "",
        "## Starting XI",
        "",
        "| Pos | Player | Club | Price | xP | Play | Note |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for player in sorted(
        (item for item in squad if item["element"] in starter_ids),
        key=lambda item: (POSITION_ORDER[item["position"]], -item["expected_points"]),
    ):
        note = "Captain" if player["element"] == captain else ""
        if player["element"] == vice:
            note = "Vice-captain"
        lines.append(
            f"| {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {player['expected_points']:.2f} | "
            f"{player['p_play']:.0%} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Bench",
            "",
            "| Order | Pos | Player | Club | Price | xP | Play |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    by_id = {item["element"]: item for item in squad}
    for order, element in enumerate(lineup["bench_order"], start=1):
        player = by_id[element]
        lines.append(
            f"| {order} | {player['position']} | {player['name']} | {player['team']} | "
            f"£{player['price']:.1f}m | {player['expected_points']:.2f} | "
            f"{player['p_play']:.0%} |"
        )
    lines.extend(
        [
            "",
            "## Model receipt",
            "",
            f"- Model: `{receipt['model_version']}`",
            f"- Forecast horizon objective: GW1–GW{receipt['horizon']}",
            f"- Future-point discount per gameweek: {receipt['horizon_decay']:.0%}",
            (
                "- Transfer-aware planning envelope: "
                f"{sum(item['used'] for item in receipt['planned_transfers'].values())} "
                "free transfers across the horizon"
            ),
            f"- Exact squad stability: {receipt['stability']['exact_squad_rate']:.0%}",
            (
                "- Mean selected-player retention under model-error perturbation: "
                f"{receipt['stability']['mean_primary_player_retention']:.0%}"
            ),
            f"- GW1 captain stability: {receipt['stability']['gw1_captain_rate']:.0%}",
            f"- Alternative objective gap: {receipt['edge_over_alternative']:.3f}",
            "",
            (
                "The optimizer maximizes discounted expected points, applies the live £100.0m "
                "budget, exact 2/5/5/3 squad composition, legal formations, maximum three "
                "players per club, and the live five-free-transfer carry cap. Future transfers "
                "value flexibility; they are a planning envelope rather than locked advice."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def select_initial_squad(
    stability_samples: int = 20, *, report_path: Path = DECISION_REPORT
) -> dict[str, Any]:
    ensure_engine_layout()
    if not CURRENT_FORECAST.exists():
        raise FileNotFoundError("Current forecast missing; run fplagent forecast first")
    rows, events = _player_rows()
    primary = _solve(rows, events)
    alternative = _solve(rows, events, exclude_squad=set(primary["selected"]))
    stability = _stability(rows, events, primary, stability_samples)
    horizon_sensitivity = _horizon_sensitivity(rows, events, primary)
    rules = load_rules()
    selected_rows = [primary["player_meta"][element] for element in primary["selected"]]
    validate_squad(selected_rows, rules)
    for event, lineup in primary["lineups"].items():
        event_squad_rows = [
            primary["player_meta"][element] for element in primary["planned_squads"][event]
        ]
        validate_squad(event_squad_rows, rules)
        validate_lineup(
            event_squad_rows,
            lineup["starters"],
            lineup["bench_order"],
            lineup["captain"],
            lineup["vice_captain"],
            rules,
        )
    squad = [_player_item(primary, element) for element in primary["selected"]]
    squad.sort(key=lambda item: (POSITION_ORDER[item["position"]], -item["price"]))
    gameweeks = {}
    for event, lineup in primary["lineups"].items():
        gameweeks[str(event)] = {
            **lineup,
            "planned_squad": list(primary["planned_squads"][event]),
            "starters": list(lineup["starters"]),
            "bench_order": list(lineup["bench_order"]),
        }
    planned_transfers = {
        str(event): {
            "available": plan["available"],
            "used": plan["used"],
            "in": [_player_item(primary, element, event) for element in plan["in"]],
            "out": [_player_item(primary, element, event) for element in plan["out"]],
        }
        for event, plan in primary["transfers"].items()
    }
    rules_path = PROCESSED / "fpl" / "2026-27" / "preseason" / "rules.parquet"
    receipt = {
        "receipt_version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "decision_event": 1,
        "decision_type": "initial_squad",
        "horizon": max(events),
        "model_version": rows[0]["model_version"],
        "model_sha256": sha256_file(MODEL_FILE),
        "forecast_sha256": sha256_file(CURRENT_FORECAST),
        "rules_sha256": sha256_file(rules_path),
        "snapshot_at": rows[0]["snapshot_at"],
        "objective": primary["objective"],
        "alternative_objective": alternative["objective"],
        "edge_over_alternative": primary["objective"] - alternative["objective"],
        "budget_spent": primary["budget"] / 10.0,
        "bank": (rules.budget - primary["budget"]) / 10.0,
        "horizon_decay": primary["horizon_decay"],
        "weights": {str(key): value for key, value in primary["weights"].items()},
        "squad": squad,
        "gameweeks": gameweeks,
        "planned_transfers": planned_transfers,
        "best_alternative_squad": [
            _player_item(alternative, element) for element in alternative["selected"]
        ],
        "stability": stability,
        "horizon_sensitivity": horizon_sensitivity,
        "assumptions": [
            "Future free transfers are modeled; hits and future price changes are not.",
            "GW2+ availability flags decay toward role priors.",
            "Model-error perturbations are not calibrated match-outcome simulations yet.",
            "Future transfer paths value flexibility and are not locked recommendations.",
            "This remains subject to prospective pre-deadline updates.",
        ],
    }
    DECISION_JSON.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render(receipt), encoding="utf-8")
    return receipt
