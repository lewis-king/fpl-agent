from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .artifact_lineage import load_json_artifact, require_current_forecast, require_recorded_file
from .models import CURRENT_FORECAST
from .optimizer import _solve
from .paths import DECISIONS, MODEL_DATA, ensure_engine_layout
from .rules import load_rules, validate_lineup, validate_squad
from .tournament import (
    DEFAULT_EVENTS,
    _candidate_record,
    _load_rows,
    _solve_static,
)

PLAYER_CALIBRATION_PARQUET = MODEL_DATA / "tournament_v2" / "component-player-calibration.parquet"
SELECTION_RESULTS_JSON = MODEL_DATA / "tournament_v2" / "component-gw1-5-results.json"
COMPONENT_CANDIDATES_JSON = DECISIONS / "2026-27-gw1-component-candidates.json"
COMPONENT_BACKTEST_METRICS = MODEL_DATA / "component_backtest_v1" / "metrics.json"


def _component_means() -> dict[tuple[int, int], float]:
    rows = pq.read_table(PLAYER_CALIBRATION_PARQUET).to_pylist()
    return {
        (int(row["element"]), int(row["event"])): float(row["raw_component_mean"]) for row in rows
    }


def _modified_rows(
    rows: list[dict], component: dict[tuple[int, int], float], raw_weight: float
) -> list[dict]:
    output = []
    for original in rows:
        row = dict(original)
        key = (int(row["element"]), int(row["event_number"]))
        raw = component[key]
        xp = float(row["expected_points"])
        blended = raw_weight * raw + (1.0 - raw_weight) * xp
        row["incumbent_expected_points"] = xp
        row["raw_component_points"] = raw
        row["expected_points"] = blended
        row["conditional_points_if_playing"] = blended / max(float(row["p_play"]), 0.005)
        output.append(row)
    return output


def _by_player(rows: list[dict]) -> tuple[dict[int, dict[int, dict]], dict[int, dict]]:
    player_rows: dict[int, dict[int, dict]] = defaultdict(dict)
    meta = {}
    for row in rows:
        element = int(row["element"])
        player_rows[element][int(row["event_number"])] = row
        meta[element] = row
    return player_rows, meta


def _transfer_policy(solution: dict[str, Any]) -> dict[str, Any]:
    return {
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


def generate_component_candidates() -> dict[str, Any]:
    ensure_engine_layout()
    if not PLAYER_CALIBRATION_PARQUET.exists() or not SELECTION_RESULTS_JSON.exists():
        raise FileNotFoundError(
            "Run a component tournament selection pass before generating native candidates"
        )
    selection_receipt = load_json_artifact(
        SELECTION_RESULTS_JSON, "component tournament selection receipt"
    )
    require_current_forecast(
        selection_receipt,
        CURRENT_FORECAST,
        "component tournament selection receipt",
        fields=("artifacts", "forecast_sha256"),
    )
    require_recorded_file(
        selection_receipt,
        ("artifacts", "player_calibration_sha256"),
        PLAYER_CALIBRATION_PARQUET,
        "component tournament player calibration",
    )
    if not COMPONENT_BACKTEST_METRICS.exists():
        raise FileNotFoundError("Run fplagent backtest-components before candidate generation")
    backtest_receipt = json.loads(COMPONENT_BACKTEST_METRICS.read_text(encoding="utf-8"))
    selected_raw_weight = float(backtest_receipt["blend_selection"]["selected_raw_weight"])
    rows, _ = _load_rows(DEFAULT_EVENTS)
    component = _component_means()
    rules = load_rules()
    candidates = []
    seen: set[tuple[frozenset[int], tuple[tuple[int, tuple[int, ...]], ...]]] = set()
    index = 1

    def add(candidate: dict[str, Any]) -> None:
        nonlocal index
        planned = candidate.get("planned_squads", {})
        policy_key = tuple(
            sorted((int(event), tuple(sorted(map(int, squad)))) for event, squad in planned.items())
        )
        key = (frozenset(map(int, candidate["selected"])), policy_key)
        if key in seen:
            return
        seen.add(key)
        candidate["candidate_id"] = f"C{index:03d}"
        index += 1
        candidates.append(candidate)

    raw_weights = sorted(
        {
            0.0,
            selected_raw_weight,
            max(0.0, selected_raw_weight - 0.05),
            min(1.0, selected_raw_weight + 0.05),
            0.25,
            0.50,
            0.75,
            1.00,
        }
    )
    for raw_weight in raw_weights:
        modified = _modified_rows(rows, component, raw_weight)
        by_player, meta = _by_player(modified)
        for decay in (0.80, 0.88, 0.95):
            static_solution = _solve_static(
                by_player,
                meta,
                DEFAULT_EVENTS,
                rules,
                horizon_decay=decay,
                bench_weight=0.08,
            )
            static = _candidate_record(
                0,
                static_solution,
                f"component-static:w{raw_weight:.2f}:d{decay:.2f}",
                by_player,
                meta,
                DEFAULT_EVENTS,
            )
            static["component_raw_weight"] = raw_weight
            static["horizon_decay"] = decay
            static["policy_kind"] = "fixed"
            add(static)

            dynamic_solution = _solve(modified, list(DEFAULT_EVENTS), horizon_decay=decay)
            dynamic_record = {
                "selected": dynamic_solution["selected"],
                "lineups": dynamic_solution["lineups"],
                "base_objective": float(dynamic_solution["objective"]),
            }
            dynamic = _candidate_record(
                0,
                dynamic_record,
                f"component-policy:w{raw_weight:.2f}:d{decay:.2f}",
                by_player,
                meta,
                DEFAULT_EVENTS,
            )
            dynamic["planned_squads"] = {
                str(event): list(dynamic_solution["planned_squads"][event])
                for event in DEFAULT_EVENTS
            }
            dynamic["lineups"] = {
                str(event): dict(dynamic_solution["lineups"][event]) for event in DEFAULT_EVENTS
            }
            dynamic["transfer_policy"] = _transfer_policy(dynamic_solution)
            dynamic["component_raw_weight"] = raw_weight
            dynamic["horizon_decay"] = decay
            dynamic["policy_kind"] = "transfer-aware"
            add(dynamic)

    _, loaded = _load_rows(DEFAULT_EVENTS)
    original_meta = loaded["meta"]
    for candidate in candidates:
        squad_rows = [original_meta[int(element)] for element in candidate["selected"]]
        validate_squad(squad_rows, rules)
        for event in DEFAULT_EVENTS:
            squad = candidate.get("planned_squads", {}).get(str(event), candidate["selected"])
            event_rows = [original_meta[int(element)] for element in squad]
            validate_squad(event_rows, rules)
            lineup = candidate["lineups"][str(event)]
            validate_lineup(
                event_rows,
                lineup["starters"],
                lineup["bench_order"],
                lineup["captain"],
                lineup["vice_captain"],
                rules,
            )
    payload = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "season": "2026-27",
        "events": list(DEFAULT_EVENTS),
        "candidate_count": len(candidates),
        "selection_seed": selection_receipt["seed"],
        "selection_simulations": selection_receipt["simulations"],
        "selection_engine": selection_receipt["engine"],
        "historically_selected_raw_weight": selected_raw_weight,
        "raw_weights": raw_weights,
        "component_backtest_sha256": sha256_file(COMPONENT_BACKTEST_METRICS),
        "selection_results_sha256": sha256_file(SELECTION_RESULTS_JSON),
        "player_calibration_sha256": sha256_file(PLAYER_CALIBRATION_PARQUET),
        "forecast_sha256": sha256_file(CURRENT_FORECAST),
        "candidates": candidates,
    }
    COMPONENT_CANDIDATES_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload
