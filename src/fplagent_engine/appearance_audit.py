from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from fplagent_data.http import sha256_file

from .appearance_calibration import CALIBRATION_FILE, load_appearance_calibration
from .features import TRAINING_FEATURES
from .models import BACKTEST_FORECAST, TOP_K
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

OUTPUT_DIR = MODEL_DATA / "appearance_audit_v1"
METRICS_FILE = OUTPUT_DIR / "metrics.json"
REPORT = REPORTS / "appearance-reliability-audit.md"
TEST_SEASONS = ("2024-25", "2025-26")
POSITIONS = ("GK", "DEF", "MID", "FWD")


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _selectable_rows() -> dict[str, np.ndarray]:
    connection = duckdb.connect()
    try:
        table = connection.execute(
            f"""
            WITH ranked AS (
                SELECT
                    r.season,
                    r.event_number,
                    r.element,
                    r.position,
                    r.expected_points,
                    r.p_play,
                    f.target_minutes,
                    f.cold_start,
                    f.history_events,
                    row_number() OVER (
                        PARTITION BY r.season, r.event_number, r.position
                        ORDER BY r.expected_points DESC, r.element
                    ) AS points_rank,
                    row_number() OVER (
                        PARTITION BY r.season, r.event_number, r.position
                        ORDER BY r.expected_points / nullif(r.market_price, 0) DESC, r.element
                    ) AS value_rank
                FROM read_parquet('{_sql_path(BACKTEST_FORECAST)}') r
                JOIN read_parquet('{_sql_path(TRAINING_FEATURES)}') f
                  USING (season, event_number, element)
                WHERE r.p_play IS NOT NULL AND f.target_minutes IS NOT NULL
            )
            SELECT *
            FROM ranked
            WHERE points_rank <= CASE position
                WHEN 'GK' THEN {TOP_K['GK']}
                WHEN 'DEF' THEN {TOP_K['DEF']}
                WHEN 'MID' THEN {TOP_K['MID']}
                ELSE {TOP_K['FWD']}
            END
            OR value_rank <= CASE position
                WHEN 'GK' THEN {TOP_K['GK']}
                WHEN 'DEF' THEN {TOP_K['DEF']}
                WHEN 'MID' THEN {TOP_K['MID']}
                ELSE {TOP_K['FWD']}
            END
            ORDER BY season, event_number, position, points_rank, value_rank
            """
        ).fetch_arrow_table()
    finally:
        connection.close()
    return {
        name: np.asarray(table[name].to_pylist(), dtype=object)
        for name in table.column_names
    }


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(float), 1e-5, 1.0 - 1e-5)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    clipped = np.clip(predicted.astype(float), 1e-5, 1.0 - 1e-5)
    return {
        "rows": len(actual),
        "brier": float(brier_score_loss(actual, clipped)),
        "log_loss": float(log_loss(actual, clipped, labels=[0, 1])),
        "play_probability_bias": float(clipped.mean() - actual.mean()),
        "actual_dnp": int((1 - actual).sum()),
        "expected_dnp": float((1.0 - clipped).sum()),
    }


def _prior_season(season: str) -> str:
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def audit_appearance_reliability() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    values = _selectable_rows()
    seasons = values["season"].astype(str)
    positions = values["position"].astype(str)
    events = values["event_number"].astype(int)
    p_play = values["p_play"].astype(float)
    actual = (values["target_minutes"].astype(float) > 0).astype(int)
    validations = []
    for test_season in TEST_SEASONS:
        prior = _prior_season(test_season)
        for position in POSITIONS:
            train = (seasons == prior) & (positions == position)
            test = (seasons == test_season) & (positions == position)
            model = LogisticRegression(C=1.0, max_iter=2_000)
            model.fit(_logit(p_play[train]), actual[train])
            predicted = model.predict_proba(_logit(p_play[test]))[:, 1]
            gw1 = test & (events == 1)
            validations.append(
                {
                    "test_season": test_season,
                    "train_season": prior,
                    "position": position,
                    "raw": _metrics(actual[test], p_play[test]),
                    "calibrated": _metrics(actual[test], predicted),
                    "gw1_raw": _metrics(actual[gw1], p_play[gw1]),
                    "gw1_calibrated": _metrics(
                        actual[gw1], predicted[events[test] == 1]
                    ),
                    "coefficient": float(model.coef_[0, 0]),
                    "intercept": float(model.intercept_[0]),
                }
            )
    position_gate = {}
    for position in POSITIONS:
        slices = [row for row in validations if row["position"] == position]
        position_gate[position] = {
            "forward_slices": len(slices),
            "brier_wins": sum(
                row["calibrated"]["brier"] < row["raw"]["brier"] for row in slices
            ),
            "log_loss_wins": sum(
                row["calibrated"]["log_loss"] < row["raw"]["log_loss"]
                for row in slices
            ),
        }
        position_gate[position]["promoted"] = (
            position_gate[position]["forward_slices"] == len(TEST_SEASONS)
            and position_gate[position]["brier_wins"] == len(TEST_SEASONS)
            and position_gate[position]["log_loss_wins"] == len(TEST_SEASONS)
        )
    promoted = [position for position in POSITIONS if position_gate[position]["promoted"]]
    final_calibrators = {}
    for position in promoted:
        selected = (seasons == "2025-26") & (positions == position)
        model = LogisticRegression(C=1.0, max_iter=2_000)
        model.fit(_logit(p_play[selected]), actual[selected])
        final_calibrators[position] = {
            "coefficient": float(model.coef_[0, 0]),
            "intercept": float(model.intercept_[0]),
            "training_season": "2025-26",
            "training_rows": int(selected.sum()),
        }
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "union of top expected-points and top expected-points-per-price players "
            "per position and Gameweek"
        ),
        "method": "position-specific logistic recalibration of logit(P(any minutes))",
        "promoted_positions": promoted,
        "calibrators": final_calibrators,
        "gate": position_gate,
    }
    CALIBRATION_FILE.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    load_appearance_calibration.cache_clear()
    result = {
        **artifact,
        "candidate_pool_rows": len(seasons),
        "season_rows": {
            season: int((seasons == season).sum()) for season in sorted(set(seasons))
        },
        "validations": validations,
        "artifact": str(CALIBRATION_FILE),
        "artifact_sha256": sha256_file(CALIBRATION_FILE),
        "decision": (
            "Only positions improving both Brier score and log loss in both strict "
            "season-forward tests are applied. All rejected positions remain unmodified."
        ),
    }
    METRICS_FILE.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Appearance reliability audit",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Candidate rows:** {result['candidate_pool_rows']:,}  ",
        (
            "**Promoted positions:** "
            + (", ".join(result["promoted_positions"]) or "none")
        ),
        "",
        (
            "This audit is deliberately restricted to the union of leading raw-points and value "
            "candidates the optimiser could realistically select. That captures both premium "
            "starters and cheap bench routes without allowing hundreds of irrelevant players to "
            "dominate the score."
        ),
        "",
        "## Strict forward results",
        "",
        "| Season | Pos | Raw Brier | Cal Brier | Raw log loss | Cal log loss | Raw/actual DNP |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["validations"]:
        lines.append(
            f"| {row['test_season']} | {row['position']} | "
            f"{row['raw']['brier']:.4f} | {row['calibrated']['brier']:.4f} | "
            f"{row['raw']['log_loss']:.4f} | {row['calibrated']['log_loss']:.4f} | "
            f"{row['raw']['expected_dnp']:.1f}/{row['raw']['actual_dnp']} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            result["decision"],
            "",
            (
                "A global correction was rejected during exploration because it improved 2024/25 "
                "but worsened the latest season. This artifact cannot silently alter a failed position."
            ),
            "",
        ]
    )
    return "\n".join(lines)
