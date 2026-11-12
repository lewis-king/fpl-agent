from datetime import UTC, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.features import MODEL_FEATURES
from fplagent_engine.market_feature_challenger import (
    MARKET_FEATURES,
    _attacker_error_metrics,
    blend_current_attacker_goal_environment,
    blend_current_defender_predictions,
    current_market_feature_phase,
    market_feature_matrix,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {feature: 0.0 for feature in MODEL_FEATURES}
    row.update(
        {
            "season": "2025-26",
            "event_number": 7,
            "team_id": 3,
            "element": 42,
            "position": "DEF",
            "team_expected_goals": 1.2,
            "team_expected_goals_against": 0.8,
            "team_clean_sheet_probability": 0.45,
        }
    )
    row.update(overrides)
    return row


def test_market_features_preserve_level_and_disagreement_signal() -> None:
    table = pa.Table.from_pylist([_row()])
    observed = {
        ("2025-26", 7, 3): {
            "market_team_goal_rate": 1.7,
            "market_opponent_goal_rate": 0.6,
            "market_clean_sheet_expectation": 0.55,
            "market_fixture_coverage": 1.0,
        }
    }

    matrix, extras = market_feature_matrix(table, market=observed)

    assert matrix.shape == (1, len(MODEL_FEATURES) + len(MARKET_FEATURES))
    assert extras[0]["market_team_goal_rate_delta"] == pytest.approx(0.5)
    assert extras[0]["market_opponent_goal_rate_delta"] == pytest.approx(-0.2)
    assert extras[0]["market_clean_sheet_delta"] == pytest.approx(0.1)
    np.testing.assert_allclose(
        matrix[0, -len(MARKET_FEATURES) :],
        [extras[0][feature] for feature in MARKET_FEATURES],
    )


def test_missing_market_fixture_fails_closed_to_internal_team_features() -> None:
    table = pa.Table.from_pylist([_row()])

    _, extras = market_feature_matrix(table, market={})

    assert extras[0] == {
        "market_team_goal_rate": 1.2,
        "market_opponent_goal_rate": 0.8,
        "market_clean_sheet_expectation": 0.45,
        "market_fixture_coverage": 0.0,
        "market_team_goal_rate_delta": 0.0,
        "market_opponent_goal_rate_delta": 0.0,
        "market_clean_sheet_delta": 0.0,
    }


def test_preseason_market_authority_switches_off_after_gw1_deadline(tmp_path) -> None:
    events_path = tmp_path / "events.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": 1,
                    "deadline_time": "2026-08-21T17:30:00+00:00",
                    "finished": False,
                }
            ]
        ),
        events_path,
    )

    assert (
        current_market_feature_phase(now=datetime(2026, 8, 20, tzinfo=UTC), events_path=events_path)
        == "preseason"
    )
    assert (
        current_market_feature_phase(now=datetime(2026, 8, 22, tzinfo=UTC), events_path=events_path)
        == "weekly"
    )


def test_live_policy_blends_only_covered_defenders_at_bounded_weight() -> None:
    class PointModel:
        def predict(self, matrix: np.ndarray) -> np.ndarray:
            return np.full(len(matrix), 10.0)

    table = pa.Table.from_pylist([_row()])
    rows = [
        {
            "season": "2025-26",
            "event_number": 7,
            "element": 42,
            "position": "DEF",
            "expected_points": 5.0,
            "robust_points": 4.8,
            "p_play": 0.8,
        }
    ]
    market = {
        ("2025-26", 7, 3): {
            "market_team_goal_rate": 1.7,
            "market_opponent_goal_rate": 0.6,
            "market_clean_sheet_expectation": 0.55,
            "market_fixture_coverage": 1.0,
        }
    }

    blended, diagnostics = blend_current_defender_predictions(
        table,
        rows,
        market=market,
        point_model=PointModel(),
        weight=0.2,
        ready_events={7},
    )

    assert blended[0]["market_feature_applied"] is True
    assert blended[0]["market_feature_expected_points"] == pytest.approx(8.0)
    assert blended[0]["expected_points"] == pytest.approx(5.6)
    assert blended[0]["robust_points"] == pytest.approx(5.4)
    assert diagnostics["applied_rows"] == 1


def test_attacker_market_policy_applies_only_receipt_authorized_position() -> None:
    table = pa.Table.from_pylist(
        [
            _row(element=42, position="MID"),
            _row(element=43, position="FWD"),
        ]
    )
    rows = [
        {
            "season": "2025-26",
            "event_number": 7,
            "element": element,
            "position": position,
            "team_id": 3,
            "expected_points": 6.0,
            "robust_points": 5.8,
            "p_1_59": 0.1,
            "p_60_89": 0.7,
            "p_90_or_more": 0.1,
        }
        for element, position in ((42, "MID"), (43, "FWD"))
    ]
    market = {
        ("2025-26", 7, 3): {
            "market_team_goal_rate": 1.7,
            "market_opponent_goal_rate": 0.6,
            "market_clean_sheet_expectation": 0.55,
            "market_fixture_coverage": 1.0,
        }
    }

    blended, diagnostics = blend_current_attacker_goal_environment(
        table,
        rows,
        market=market,
        ready_events={7},
        weights={"MID": 0.0, "FWD": 0.05},
    )

    assert blended[0]["market_attacker_applied"] is False
    assert blended[0]["expected_points"] == 6.0
    assert blended[1]["market_attacker_applied"] is True
    assert blended[1]["expected_points"] > 6.0
    assert diagnostics["position_counts"] == {"FWD": 1}


def test_attacker_calibration_metrics_are_tail_sensitive() -> None:
    records = [(8.0, 5.0, 2.0, 1.35), (0.0, 2.0, 1.0, 0.75)]

    incumbent = _attacker_error_metrics(records, weight=0.0)
    candidate = _attacker_error_metrics(records, weight=0.05)

    assert candidate["rows"] == 2
    assert candidate["rmse"] < incumbent["rmse"]
