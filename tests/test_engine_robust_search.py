import json

import numpy as np

from fplagent_engine.robust_search import (
    SCENARIO_WEIGHTS,
    _candidate_id,
    _component_finalist_indices,
    _legal_swap_neighbours,
    _load_seed_squads,
    _weighted_regret,
)


def test_robust_candidate_id_is_order_independent() -> None:
    assert _candidate_id([3, 1, 2]) == _candidate_id([2, 3, 1])


def test_swap_neighbours_preserve_position_budget_and_club_limit() -> None:
    meta = {
        1: {"position": "GK", "team_id": 1, "market_price": 50},
        2: {"position": "GK", "team_id": 2, "market_price": 45},
        3: {"position": "GK", "team_id": 1, "market_price": 55},
        4: {"position": "GK", "team_id": 3, "market_price": 65},
    }
    neighbours = list(
        _legal_swap_neighbours(
            (1, 2),
            meta,
            {"GK": [1, 2, 3, 4]},
            budget=100,
            club_limit=1,
        )
    )

    assert (2, 3) in neighbours
    assert (1, 3) not in neighbours
    assert (1, 4) not in neighbours


def test_weighted_regret_is_zero_for_scenario_leader() -> None:
    values = {name: 10.0 for name in SCENARIO_WEIGHTS}
    result = _weighted_regret(values, values)

    assert result["weighted_mean_regret"] == 0.0
    assert result["worst_scenario_regret"] == 0.0
    assert result["robust_regret"] == 0.0


def test_worst_case_contributes_to_robust_regret() -> None:
    values = {name: 10.0 for name in SCENARIO_WEIGHTS}
    bests = dict(values)
    bests["high_goal_open"] = 14.0

    result = _weighted_regret(values, bests)

    assert result["weighted_mean_regret"] > 0.0
    assert result["worst_scenario_regret"] == 4.0
    assert result["robust_regret"] > result["weighted_mean_regret"]


def test_component_finalist_union_is_filled_to_requested_size() -> None:
    candidates = [
        {"gw1_formation": "4-3-3" if index < 90 else "3-4-3"}
        for index in range(100)
    ]
    values = np.arange(100, dtype=np.float64)
    metrics = {
        "evidence_mean": values,
        "cvar10": values,
        "raw_mean": values,
        "anchored_mean": values,
    }

    selected = _component_finalist_indices(candidates, metrics, 64)

    assert len(selected) == 64
    assert len(set(selected)) == 64


def test_component_finalists_preserve_mandatory_benchmarks() -> None:
    candidates = [
        {
            "gw1_formation": "4-3-3",
            "origin_ids": ["C007"] if index == 0 else [f"R{index:03d}"],
        }
        for index in range(100)
    ]
    values = np.arange(100, dtype=np.float64)
    metrics = {
        "evidence_mean": values,
        "cvar10": values,
        "raw_mean": values,
        "anchored_mean": values,
    }

    selected = _component_finalist_indices(candidates, metrics, 8, {"C007"})

    assert len(selected) == 8
    assert 0 in selected


def test_global_finalist_quota_respects_small_limit() -> None:
    protected = ["C007", "C005", "C009", "S028", "S001"]
    candidates = [
        {
            "gw1_formation": "4-3-3",
            "origin_ids": (
                [protected[index]]
                if index < len(protected)
                else ["global-milp"]
                if index % 2
                else ["global-evolution"]
            ),
        }
        for index in range(30)
    ]
    values = np.arange(30, dtype=np.float64)
    metrics = {
        "evidence_mean": values,
        "cvar10": values,
        "raw_mean": values,
        "anchored_mean": values,
    }

    selected = _component_finalist_indices(candidates, metrics, 8, set(protected))

    assert len(selected) == 8
    assert set(range(5)) <= set(selected)
    assert any("global-milp" in candidates[index]["origin_ids"] for index in selected)
    assert any("global-evolution" in candidates[index]["origin_ids"] for index in selected)


def test_seed_candidate_lineage_is_forecast_scoped_not_calibration_scoped(
    tmp_path, monkeypatch
) -> None:
    residual = tmp_path / "residual.json"
    component = tmp_path / "component.json"
    candidate = {"candidate_id": "S001", "selected": list(range(1, 16))}
    residual.write_text(
        json.dumps({"forecast_sha256": "current", "candidates": [candidate]}),
        encoding="utf-8",
    )
    component.write_text(
        json.dumps(
            {
                "forecast_sha256": "current",
                "player_calibration_sha256": "selection-pass-calibration",
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("fplagent_engine.robust_search.CANDIDATES_JSON", residual)
    monkeypatch.setattr("fplagent_engine.robust_search.COMPONENT_CANDIDATES_JSON", component)

    origins, order = _load_seed_squads("current")

    assert order == [tuple(range(1, 16))]
    assert origins[tuple(range(1, 16))] == {"S001"}


def test_adaptive_challenger_is_protected_only_for_matching_forecast(
    tmp_path, monkeypatch
) -> None:
    residual = tmp_path / "residual.json"
    component = tmp_path / "component.json"
    adaptive = tmp_path / "adaptive.json"
    residual.write_text(
        json.dumps(
            {
                "forecast_sha256": "current",
                "candidates": [{"candidate_id": "S001", "selected": list(range(1, 16))}],
            }
        ),
        encoding="utf-8",
    )
    component.write_text(
        json.dumps({"forecast_sha256": "current", "candidates": []}),
        encoding="utf-8",
    )
    adaptive.write_text(
        json.dumps(
            {
                "verdict": "REQUEST_FULL_PIPELINE",
                "lineage": {"current_forecast_sha256": "current"},
                "tournament": {
                    "full_pipeline_request_gate": {"passed": True},
                    "leader": {
                        "candidate_id": "AP-001",
                        "candidate": {"selected": list(range(16, 31))},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("fplagent_engine.robust_search.CANDIDATES_JSON", residual)
    monkeypatch.setattr(
        "fplagent_engine.robust_search.COMPONENT_CANDIDATES_JSON", component
    )
    monkeypatch.setattr("fplagent_engine.robust_search.ADAPTIVE_RESULTS", adaptive)

    origins, order = _load_seed_squads("current")

    adaptive_squad = tuple(range(16, 31))
    assert adaptive_squad in order
    assert origins[adaptive_squad] == {"AP-001", "adaptive-lead-shadow"}

    adaptive_payload = json.loads(adaptive.read_text(encoding="utf-8"))
    adaptive_payload["lineage"]["current_forecast_sha256"] = "old-forecast"
    adaptive.write_text(json.dumps(adaptive_payload), encoding="utf-8")
    origins, order = _load_seed_squads("current")

    assert adaptive_squad not in order
    assert adaptive_squad not in origins
