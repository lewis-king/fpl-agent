from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .appearance_audit import _selectable_rows
from .appearance_calibration import CALIBRATION_FILE, load_appearance_calibration
from .appearance_challenger import ARTIFACT as CHALLENGER_ARTIFACT
from .appearance_challenger import TEST_SEASONS
from .features import TRAINING_FEATURES
from .models import BACKTEST_FORECAST
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import load_rules
from .tournament import _score_candidates

OUTPUT_DIR = MODEL_DATA / "appearance_challenger_v2"
REPLAY_ARTIFACT = OUTPUT_DIR / "policy-replay.json"
RETIREMENT_RECEIPT = OUTPUT_DIR / "production-retirement.json"
PRE_RETIREMENT_ARTIFACT = OUTPUT_DIR / "production-calibration-before-retirement.json"
REPORT = REPORTS / "appearance-policy-replay.md"


def _adjust_play(raw: float, calibrator: dict[str, Any]) -> float:
    clipped = float(np.clip(raw, 1e-6, 1.0 - 1e-6))
    play = calibrator["play"]
    logit = np.log(clipped / (1.0 - clipped))
    return float(
        1.0
        / (
            1.0
            + np.exp(
                -(
                    float(play["intercept"])
                    + float(play["coefficient"]) * logit
                )
            )
        )
    )


def policy_replay_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = np.asarray([float(row["calibrated_minus_raw_points"]) for row in rows])
    if not len(deltas):
        raise ValueError("appearance policy replay contains no events")
    standard_error = float(deltas.std(ddof=1) / np.sqrt(len(deltas))) if len(deltas) > 1 else 0.0
    overall = float(deltas.mean())
    season_means = {
        season: float(
            np.mean(
                [
                    row["calibrated_minus_raw_points"]
                    for row in rows
                    if row["season"] == season
                ]
            )
        )
        for season in sorted({str(row["season"]) for row in rows})
    }
    checks = {
        "positive_overall_mean": overall > 0.0,
        "no_material_season_regression": all(value >= -0.05 for value in season_means.values()),
        "paired_lower_bound_above_minus_point_one": overall - 1.96 * standard_error > -0.10,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "events": len(rows),
        "mean_delta": overall,
        "delta_95ci_low": overall - 1.96 * standard_error,
        "delta_95ci_high": overall + 1.96 * standard_error,
        "season_mean_delta": season_means,
        "calibrated_win_rate": float(np.mean(deltas > 0.0)),
        "tie_rate": float(np.mean(deltas == 0.0)),
    }


def _candidate_payload(solution: dict[str, Any], event: int) -> dict[str, Any]:
    lineup = solution["lineups"][event]
    return {
        "candidate_id": f"event-{event}",
        "selected": list(solution["selected"]),
        "lineups": {
            str(event): {
                "starters": list(lineup["starters"]),
                "bench_order": list(lineup["bench_order"]),
                "captain": int(lineup["captain"]),
                "vice_captain": int(lineup["vice_captain"]),
            }
        },
    }


def _render_report(result: dict[str, Any]) -> str:
    gate = result["gate"]
    lines = [
        "# Appearance calibration policy replay",
        "",
        f"**Built:** {result['created_at']}  ",
        f"**Position:** {result['position']}  ",
        f"**Events:** {gate['events']}  ",
        f"**Retention gate:** {'PASS' if gate['passed'] else 'FAIL'}",
        "",
        (
            "Each event independently solves a legal £100m 15-player squad, starting XI, bench, "
            "captain and vice under the raw and calibrated forecasts. Both are then scored on the "
            "same realised player points and minutes with exact formation-valid autosubs and "
            "captain fallback."
        ),
        "",
        "## Paired result",
        "",
        f"- Mean calibrated minus raw points: **{gate['mean_delta']:+.3f}**",
        (
            f"- Paired 95% interval: **[{gate['delta_95ci_low']:+.3f}, "
            f"{gate['delta_95ci_high']:+.3f}]**"
        ),
        f"- Calibrated win rate: **{gate['calibrated_win_rate']:.1%}**",
        f"- Exact tie rate: **{gate['tie_rate']:.1%}**",
        "",
        "| Season | Mean delta |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {season} | {delta:+.3f} |"
        for season, delta in gate["season_mean_delta"].items()
    )
    lines.extend(
        [
            "",
            "## Selection changes",
            "",
            f"- Exact squad unchanged: **{result['exact_squad_rate']:.1%}**",
            f"- Captain unchanged: **{result['same_captain_rate']:.1%}**",
            f"- Mean squad overlap: **{result['mean_squad_overlap']:.2f}/15**",
            "",
            (
                "A failed retention gate is evidence to remove this calibration from production; "
                "it is not evidence that appearance probabilities are unimportant."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def retire_failed_appearance_calibration(
    *,
    position: str,
    replay_path: Path = REPLAY_ARTIFACT,
    calibration_path: Path = CALIBRATION_FILE,
    archive_path: Path = PRE_RETIREMENT_ARTIFACT,
    receipt_path: Path = RETIREMENT_RECEIPT,
) -> dict[str, Any]:
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if replay.get("position") != position:
        raise ValueError("appearance replay position does not match retirement target")
    gate = replay.get("gate")
    if not isinstance(gate, dict) or gate.get("passed") is not False:
        raise ValueError("only a failed policy replay can retire a production calibration")
    current_bytes = calibration_path.read_bytes()
    current = json.loads(current_bytes)
    promoted = [str(value) for value in current.get("promoted_positions", [])]
    if position not in promoted or position not in current.get("calibrators", {}):
        raise ValueError(f"{position} is not a promoted production calibration")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        if archive_path.read_bytes() != current_bytes:
            raise ValueError("pre-retirement appearance archive already contains different bytes")
    else:
        temporary_archive = archive_path.with_suffix(archive_path.suffix + ".tmp")
        temporary_archive.write_bytes(current_bytes)
        temporary_archive.replace(archive_path)

    updated = dict(current)
    updated["version"] = max(int(current.get("version", 1)) + 1, 2)
    updated["created_at"] = datetime.now(UTC).isoformat()
    updated["promoted_positions"] = [value for value in promoted if value != position]
    updated["calibrators"] = {
        key: value for key, value in current.get("calibrators", {}).items() if key != position
    }
    updated_gate = {key: dict(value) for key, value in current.get("gate", {}).items()}
    if position in updated_gate:
        updated_gate[position]["promoted"] = False
        updated_gate[position]["policy_replay_passed"] = False
    updated["gate"] = updated_gate
    updated["retirement"] = {
        "position": position,
        "reason": "failed frozen legal-squad policy replay",
        "replay": str(replay_path),
        "replay_sha256": sha256_file(replay_path),
        "mean_delta": float(gate["mean_delta"]),
        "delta_95ci_low": float(gate["delta_95ci_low"]),
        "delta_95ci_high": float(gate["delta_95ci_high"]),
        "season_mean_delta": gate["season_mean_delta"],
    }
    before_hash = sha256_file(calibration_path)
    _atomic_json(calibration_path, updated)
    load_appearance_calibration.cache_clear()
    receipt = {
        "receipt_version": 1,
        "created_at": updated["created_at"],
        "position": position,
        "status": "retired",
        "before_artifact": str(archive_path),
        "before_sha256": before_hash,
        "after_artifact": str(calibration_path),
        "after_sha256": sha256_file(calibration_path),
        "replay": str(replay_path),
        "replay_sha256": sha256_file(replay_path),
        "production_promoted_positions": updated["promoted_positions"],
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def run_appearance_policy_replay(
    *,
    position: str = "FWD",
    challenger_path: Path = CHALLENGER_ARTIFACT,
) -> dict[str, Any]:
    if position not in {"GK", "DEF", "MID", "FWD"}:
        raise ValueError(f"unsupported appearance replay position {position}")
    challenger = json.loads(challenger_path.read_text(encoding="utf-8"))
    validation_calibrators = {
        str(row["test_season"]): row["calibrator"]
        for row in challenger["validations"]
        if row["position"] == position and row["method"] == "play_logistic"
    }
    if set(validation_calibrators) != set(TEST_SEASONS):
        raise ValueError("appearance challenger lacks both forward play calibrators")

    feature_rows = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in TEST_SEASONS
    }
    candidate_values = _selectable_rows()
    candidate_keys = {
        (str(season), int(event), int(element))
        for season, event, element in zip(
            candidate_values["season"],
            candidate_values["event_number"],
            candidate_values["element"],
            strict=True,
        )
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(row["season"])
        if season not in TEST_SEASONS:
            continue
        market_price = row.get("market_price")
        if market_price is None or float(market_price) <= 0.0:
            continue
        key = (season, int(row["event_number"]), int(row["element"]))
        actual = feature_rows[key]
        grouped[(season, int(row["event_number"]))].append(
            {
                **row,
                "target_points": float(actual["target_points"]),
                "target_minutes": float(actual["target_minutes"]),
            }
        )

    rules = load_rules()
    event_results: list[dict[str, Any]] = []
    for (season, event), raw_rows in sorted(grouped.items()):
        calibrator = validation_calibrators[season]
        calibrated_rows = []
        for row in raw_rows:
            output = dict(row)
            key = (season, event, int(row["element"]))
            if row["position"] == position and key in candidate_keys:
                raw_play = float(row["p_play"])
                calibrated_play = _adjust_play(raw_play, calibrator)
                output["p_play"] = calibrated_play
                output["expected_points"] = (
                    float(row["expected_points"])
                    * calibrated_play
                    / max(raw_play, 0.01)
                )
            calibrated_rows.append(output)

        raw_solution = _solve(raw_rows, [event], rules=rules)
        calibrated_solution = _solve(calibrated_rows, [event], rules=rules)
        player_ids = sorted(int(row["element"]) for row in raw_rows)
        actual_by_player = {int(row["element"]): row for row in raw_rows}
        points = np.asarray(
            [[[actual_by_player[player]["target_points"] for player in player_ids]]],
            dtype=np.int16,
        )
        played = np.asarray(
            [[[actual_by_player[player]["target_minutes"] > 0 for player in player_ids]]],
            dtype=bool,
        )
        meta = {int(row["element"]): row for row in raw_rows}
        candidates = [
            _candidate_payload(raw_solution, event),
            _candidate_payload(calibrated_solution, event),
        ]
        scores = _score_candidates(
            candidates,
            player_ids,
            (event,),
            points,
            played,
            meta,
        )[0, :, 0]
        raw_selected = set(raw_solution["selected"])
        calibrated_selected = set(calibrated_solution["selected"])
        event_results.append(
            {
                "season": season,
                "event": event,
                "raw_points": int(scores[0]),
                "calibrated_points": int(scores[1]),
                "calibrated_minus_raw_points": int(scores[1] - scores[0]),
                "squad_overlap": len(raw_selected & calibrated_selected),
                "same_squad": raw_selected == calibrated_selected,
                "raw_captain": int(raw_solution["lineups"][event]["captain"]),
                "calibrated_captain": int(
                    calibrated_solution["lineups"][event]["captain"]
                ),
            }
        )

    gate = policy_replay_gate(event_results)
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "position": position,
        "method": "position-specific play logistic calibration",
        "gate": gate,
        "exact_squad_rate": float(np.mean([row["same_squad"] for row in event_results])),
        "same_captain_rate": float(
            np.mean(
                [
                    row["raw_captain"] == row["calibrated_captain"]
                    for row in event_results
                ]
            )
        ),
        "mean_squad_overlap": float(
            np.mean([row["squad_overlap"] for row in event_results])
        ),
        "events": event_results,
        "source_artifacts": {
            "appearance_challenger": str(challenger_path),
            "appearance_challenger_sha256": sha256_file(challenger_path),
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "backtest_forecast": str(BACKTEST_FORECAST),
            "backtest_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPLAY_ARTIFACT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result
