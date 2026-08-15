import numpy as np
import pyarrow as pa
import pytest

from fplagent_engine.attacking_chance_challenger import (
    CHANCE_FEATURES,
    blend_current_attacking_predictions,
    chance_quality_matrix,
)
from fplagent_engine.features import ATTACKING_HISTORY_FEATURES, MODEL_FEATURES

PRIORS = {
    "GK": {"xg": 0.005, "xa": 0.005},
    "DEF": {"xg": 0.05, "xa": 0.06},
    "MID": {"xg": 0.20, "xa": 0.18},
    "FWD": {"xg": 0.35, "xa": 0.14},
}


def _row(element: int, position: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {feature: 0.0 for feature in MODEL_FEATURES}
    row.update({feature: 0.0 for feature in ATTACKING_HISTORY_FEATURES})
    row.update(
        {
            "season": "2025-26",
            "event_number": 8,
            "element": element,
            "team_id": 3,
            "position": position,
            "history_events": 20.0,
            "availability_chance": 100.0,
            "form5_minutes": 80.0,
            "form10_minutes": 80.0,
            "form38_minutes": 75.0,
            "form5_xg": 0.20,
            "form10_xg": 0.18,
            "form38_xg": 0.15,
            "form5_xa": 0.10,
            "form10_xa": 0.09,
            "form38_xa": 0.08,
            "form10_goals": 0.30,
            "form10_assists": 0.05,
            "team_expected_goals": 1.8,
            "penalty_order": 99.0,
            "corner_order": 99.0,
        }
    )
    row.update(overrides)
    return row


def test_chance_features_shrink_rates_and_allocate_team_share() -> None:
    table = pa.Table.from_pylist(
        [
            _row(1, "MID", form10_xg=0.50, form38_xg=0.25),
            _row(2, "FWD", form10_xg=0.08, form38_xg=0.12),
        ]
    )

    matrix, extras = chance_quality_matrix(table, priors=PRIORS)

    assert matrix.shape == (2, len(MODEL_FEATURES) + len(CHANCE_FEATURES))
    assert extras[0]["xg_team_share_10"] > extras[1]["xg_team_share_10"]
    assert sum(row["xg_team_share_10"] for row in extras) == pytest.approx(1.0)
    assert extras[0]["team_allocated_xg"] > extras[1]["team_allocated_xg"]
    assert extras[0]["finishing_surplus_per90_10"] < 0.0
    assert PRIORS["MID"]["xg"] < extras[0]["shrunk_xg_per90_10"] < 0.5625


def test_live_blend_changes_only_midfielders_and_forwards() -> None:
    class ConstantModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, matrix: np.ndarray) -> np.ndarray:
            return np.full(len(matrix), self.value)

    table = pa.Table.from_pylist([_row(1, "MID"), _row(2, "DEF")])
    forecast = [
        {
            "season": "2025-26",
            "event_number": 8,
            "element": 1,
            "position": "MID",
            "expected_points": 5.0,
            "robust_points": 4.8,
            "p_play": 0.8,
        },
        {
            "season": "2025-26",
            "event_number": 8,
            "element": 2,
            "position": "DEF",
            "expected_points": 4.0,
            "robust_points": 3.9,
            "p_play": 0.9,
        },
    ]

    blended, diagnostics = blend_current_attacking_predictions(
        table,
        forecast,
        models={"MID": [ConstantModel(10.0)], "FWD": [ConstantModel(10.0)]},
        priors=PRIORS,
        weight=0.2,
    )

    assert blended[0]["attacking_chance_applied"] is True
    assert blended[0]["attacking_chance_expected_points"] == pytest.approx(8.0)
    assert blended[0]["expected_points"] == pytest.approx(5.6)
    assert blended[0]["robust_points"] == pytest.approx(5.4)
    assert blended[1]["attacking_chance_applied"] is False
    assert blended[1]["expected_points"] == 4.0
    assert diagnostics["applied_rows"] == 1
