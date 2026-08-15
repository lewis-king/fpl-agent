from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.metrics import mean_absolute_error

from fplagent_data.database import DATABASE
from fplagent_data.http import sha256_file
from fplagent_data.paths import MANIFESTS, PROCESSED

from .attacking_chance_challenger import (
    ATTACKING_POSITIONS,
    TEST_SEASONS,
    _independent_frozen_replay,
    _run_sequential_policy,
)
from .features import CURRENT_FEATURES, MODEL_FEATURES, TRAINING_FEATURES
from .market_transfer_replay import _load_event_rows
from .models import (
    BACKTEST_FORECAST,
    TOP_K,
    _gameweek_spearman,
    _matrix,
    _mean_top_k_points,
    _numeric,
    _regressor,
    _strings,
    require_cuda,
)
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout

VERSION = "understat_preseason_v1"
OUTPUT_DIR = MODEL_DATA / VERSION
OOF_FORECAST = OUTPUT_DIR / "rolling-forecasts.parquet"
MODEL_FILE = OUTPUT_DIR / "models.joblib"
RESULTS_JSON = OUTPUT_DIR / "results.json"
EXTERNAL_RECEIPT = MODEL_DATA / "external_player_data_v1" / "receipt.json"
REPORT = REPORTS / "understat-preseason-feature-challenger.md"
CURRENT_UNDERSTAT_PLAYERS = PROCESSED / "understat" / "EPL" / "2025" / "players.parquet"
CURRENT_FPL_PLAYERS = PROCESSED / "fpl" / "2026-27" / "preseason" / "players.parquet"

DEVELOPMENT_SEASONS = ("2023-24", "2024-25")
FROZEN_TEST_SEASON = "2025-26"
SCORE_FIELD = "understat_expected_points"
WEIGHTS = (0.0, 0.05, 0.10, 0.15)
MAX_PRODUCTION_WEIGHT = 0.15
SEEDS = (260_915, 260_927)
EXTERNAL_FEATURES = (
    "understat_matched",
    "understat_log_minutes",
    "understat_games",
    "understat_npxg90",
    "understat_xa90",
    "understat_shots90",
    "understat_key_passes90",
    "understat_xg_chain90",
    "understat_xg_buildup90",
    "understat_finishing_surplus90",
)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize_player_name(value: Any) -> str:
    expanded = str(value or "").translate(
        str.maketrans({"ß": "ss", "ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d"})
    )
    ascii_name = (
        unicodedata.normalize("NFKD", expanded)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"[^a-z0-9]", "", ascii_name)


def match_understat_player(
    fpl_player: dict[str, Any],
    understat_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    aliases = [
        f"{fpl_player.get('first_name') or ''} {fpl_player.get('second_name') or ''}",
        fpl_player.get("known_name"),
        fpl_player.get("web_name"),
    ]
    hits: dict[int, dict[str, Any]] = {}
    methods = []
    for method, alias in zip(("full_name", "known_name", "web_name"), aliases, strict=True):
        normalized = normalize_player_name(alias)
        if not normalized:
            continue
        for row in understat_index.get(normalized, []):
            hits[int(row["understat_player_id"])] = row
            methods.append(method)
    if len(hits) != 1:
        return None, "ambiguous" if hits else "unmatched"
    return next(iter(hits.values())), methods[0]


def _understat_index(source_season_start: int) -> dict[str, list[dict[str, Any]]]:
    path = (
        PROCESSED
        / "understat"
        / "EPL"
        / str(source_season_start)
        / "players.parquet"
    )
    if not path.is_file():
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for row in pq.read_table(path).to_pylist():
        index.setdefault(normalize_player_name(row["player_name"]), []).append(row)
    return index


def _fpl_players() -> dict[tuple[str, int], dict[str, Any]]:
    if not DATABASE.is_file():
        raise FileNotFoundError("Build the DuckDB catalog before the Understat challenger")
    connection = duckdb.connect(str(DATABASE), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT season, id, first_name, second_name, web_name, known_name
            FROM vaastav_players
            """
        ).fetchall()
    finally:
        connection.close()
    columns = ("season", "id", "first_name", "second_name", "web_name", "known_name")
    output = {
        (str(row[0]), int(row[1])): dict(zip(columns, row, strict=True)) for row in rows
    }
    if CURRENT_FPL_PLAYERS.is_file():
        for row in pq.read_table(CURRENT_FPL_PLAYERS).to_pylist():
            output[("2026-27", int(row["id"]))] = {
                key: row.get(key) for key in columns
            }
    return output


def _feature_values(row: dict[str, Any] | None) -> dict[str, float]:
    if row is None:
        return {name: 0.0 for name in EXTERNAL_FEATURES}
    minutes = max(float(row.get("minutes") or 0.0), 0.0)
    denominator = max(minutes, 180.0)
    scale = 90.0 / denominator
    return {
        "understat_matched": 1.0,
        "understat_log_minutes": float(np.log1p(minutes)),
        "understat_games": float(row.get("games") or 0.0),
        "understat_npxg90": float(row.get("npxg") or 0.0) * scale,
        "understat_xa90": float(row.get("xa") or 0.0) * scale,
        "understat_shots90": float(row.get("shots") or 0.0) * scale,
        "understat_key_passes90": float(row.get("key_passes") or 0.0) * scale,
        "understat_xg_chain90": float(row.get("xg_chain") or 0.0) * scale,
        "understat_xg_buildup90": float(row.get("xg_buildup") or 0.0) * scale,
        "understat_finishing_surplus90": (
            float(row.get("non_penalty_goals") or 0.0) - float(row.get("npxg") or 0.0)
        )
        * scale,
    }


def external_feature_matrix(
    table: pa.Table,
) -> tuple[np.ndarray, list[dict[str, float]], dict[str, Any]]:
    fpl_players = _fpl_players()
    rows = table.to_pylist()
    keys = sorted({(str(row["season"]), int(row["element"])) for row in rows})
    indexes: dict[int, dict[str, list[dict[str, Any]]]] = {}
    mapped: dict[tuple[str, int], dict[str, Any] | None] = {}
    match_method: dict[tuple[str, int], str] = {}
    coverage: dict[str, dict[str, int | float]] = {}
    for season, element in keys:
        source_start = int(season[:4]) - 1
        indexes.setdefault(source_start, _understat_index(source_start))
        fpl = fpl_players.get((season, element))
        external, method = (
            match_understat_player(fpl, indexes[source_start])
            if fpl is not None
            else (None, "missing_fpl_identity")
        )
        mapped[(season, element)] = external
        match_method[(season, element)] = method
    for season in sorted({season for season, _ in keys}):
        season_keys = [key for key in keys if key[0] == season]
        matched = sum(mapped[key] is not None for key in season_keys)
        coverage[season] = {
            "players": len(season_keys),
            "matched": matched,
            "match_rate": matched / len(season_keys) if season_keys else 0.0,
            "source_season_start": int(season[:4]) - 1,
        }
    extras = [_feature_values(mapped[(str(row["season"]), int(row["element"]))]) for row in rows]
    matrix = np.column_stack(
        [
            _matrix(table),
            np.asarray(
                [[row[name] for name in EXTERNAL_FEATURES] for row in extras],
                dtype=np.float32,
            ),
        ]
    ).astype(np.float32, copy=False)
    return matrix, extras, {
        "coverage": coverage,
        "matched_players": sum(value is not None for value in mapped.values()),
        "players": len(mapped),
        "methods": {
            method: sum(value == method for value in match_method.values())
            for method in sorted(set(match_method.values()))
        },
    }


def _incumbent_map() -> dict[tuple[str, int, int], dict[str, Any]]:
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }


def build_understat_oof() -> dict[str, Any]:
    table = pq.read_table(TRAINING_FEATURES)
    matrix, extras, mapping = external_feature_matrix(table)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    target = _numeric(table, "target_points")
    minutes = _numeric(table, "target_minutes")
    rows = table.to_pylist()
    incumbent = _incumbent_map()
    output_rows: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    fits = []
    for season_offset, test_season in enumerate(TEST_SEASONS):
        training_scope = seasons < test_season
        metrics[test_season] = {}
        for position_offset, position in enumerate(ATTACKING_POSITIONS):
            training = training_scope & (positions == position) & (minutes > 0.0)
            testing = (seasons == test_season) & (positions == position)
            predictions = []
            for seed_offset, seed in enumerate(SEEDS):
                model = _regressor(
                    seed + 100 * season_offset + 10 * position_offset + seed_offset,
                    550,
                    False,
                )
                model.fit(matrix[training], target[training], verbose=False)
                predictions.append(model.predict(matrix[testing]))
            conditional = np.mean(predictions, axis=0)
            indices = np.flatnonzero(testing)
            keys = [
                (test_season, int(events[index]), int(rows[index]["element"]))
                for index in indices
            ]
            p_play = np.asarray([float(incumbent[key]["p_play"]) for key in keys])
            challenger = np.clip(conditional * p_play, -2.0, 20.0)
            incumbent_prediction = np.asarray(
                [float(incumbent[key]["expected_points"]) for key in keys]
            )
            actual = target[testing]
            test_events = events[testing]
            metrics[test_season][position] = {
                "rows": len(indices),
                "training_rows": int(training.sum()),
                "matched_rows": int(sum(extras[index]["understat_matched"] for index in indices)),
                "incumbent_mae": float(mean_absolute_error(actual, incumbent_prediction)),
                "challenger_mae": float(mean_absolute_error(actual, challenger)),
                "incumbent_spearman": _gameweek_spearman(
                    test_events, actual, incumbent_prediction
                ),
                "challenger_spearman": _gameweek_spearman(test_events, actual, challenger),
                "incumbent_top_k": _mean_top_k_points(
                    test_events, actual, incumbent_prediction, TOP_K[position]
                ),
                "challenger_top_k": _mean_top_k_points(
                    test_events, actual, challenger, TOP_K[position]
                ),
            }
            fits.append(
                {
                    "test_season": test_season,
                    "position": position,
                    "training_rows": int(training.sum()),
                    "training_seasons": sorted(set(map(str, seasons[training]))),
                }
            )
            for local, index in enumerate(indices):
                output_rows.append(
                    {
                        "season": test_season,
                        "event_number": int(events[index]),
                        "element": int(rows[index]["element"]),
                        "position": position,
                        "target_points": float(actual[local]),
                        "incumbent_expected_points": float(incumbent_prediction[local]),
                        SCORE_FIELD: float(challenger[local]),
                        **extras[index],
                    }
                )
    OOF_FORECAST.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(output_rows), OOF_FORECAST, compression="zstd")
    return {
        "rows": len(output_rows),
        "metrics": metrics,
        "fits": fits,
        "mapping": mapping,
        "artifact": str(OOF_FORECAST),
        "artifact_sha256": sha256_file(OOF_FORECAST),
    }


def _inject_scores(grouped: dict[tuple[str, int], list[dict[str, Any]]]) -> None:
    scores = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row[SCORE_FIELD]
        )
        for row in pq.read_table(OOF_FORECAST).to_pylist()
    }
    for (season, event), rows in grouped.items():
        for row in rows:
            row[SCORE_FIELD] = scores.get(
                (season, event, int(row["element"])), float(row["xp_expected_points"])
            )


def _train_final_models(table: pa.Table, matrix: np.ndarray) -> dict[str, Any]:
    positions = _strings(table, "position")
    minutes = _numeric(table, "target_minutes")
    target = _numeric(table, "target_points")
    fitted = {}
    training_rows = {}
    for position_offset, position in enumerate(ATTACKING_POSITIONS):
        selected = (positions == position) & (minutes > 0.0)
        fitted[position] = []
        for seed_offset, seed in enumerate(SEEDS):
            model = _regressor(seed + 2_000 + 10 * position_offset + seed_offset, 550, False)
            model.fit(matrix[selected], target[selected], verbose=False)
            fitted[position].append(model)
        training_rows[position] = int(selected.sum())
    bundle = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "base_features": MODEL_FEATURES,
        "external_features": EXTERNAL_FEATURES,
        "positions": fitted,
        "training_rows": training_rows,
        "seeds": SEEDS,
    }
    joblib.dump(bundle, MODEL_FILE, compress=3)
    return {
        "path": str(MODEL_FILE),
        "sha256": sha256_file(MODEL_FILE),
        "training_rows": training_rows,
    }


def current_understat_inputs() -> dict[str, str | None]:
    try:
        result = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        active = bool((result.get("production_policy") or {}).get("decision_authority"))
    except (OSError, json.JSONDecodeError):
        active = False
    if not active:
        return {
            "understat_policy_sha256": None,
            "understat_model_sha256": None,
            "understat_players_sha256": None,
        }
    return {
        "understat_policy_sha256": sha256_file(RESULTS_JSON),
        "understat_model_sha256": sha256_file(MODEL_FILE),
        "understat_players_sha256": sha256_file(CURRENT_UNDERSTAT_PLAYERS),
    }


def apply_current_understat_policy(
    feature_table: pa.Table,
    forecast_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inactive = {"status": "inactive", "decision_authority": False, "weight": 0.0}
    try:
        result = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        policy = result["production_policy"]
        if not bool(policy.get("decision_authority")):
            return forecast_rows, {**inactive, "reason": "promotion gate is closed"}
        weight = float(policy["weight"])
        bundle = joblib.load(MODEL_FILE)
        if sha256_file(MODEL_FILE) != str(result["model"]["sha256"]):
            raise ValueError("Understat model hash differs from its promotion receipt")
        matrix, extras, mapping = external_feature_matrix(feature_table)
        positions = _strings(feature_table, "position")
        predictions: dict[int, float] = {}
        for position in ATTACKING_POSITIONS:
            indices = np.flatnonzero(positions == position)
            values = np.mean(
                [model.predict(matrix[indices]) for model in bundle["positions"][position]],
                axis=0,
            )
            predictions.update({int(index): float(values[i]) for i, index in enumerate(indices)})
        output = []
        shifts = []
        for index, raw in enumerate(forecast_rows):
            row = dict(raw)
            if str(row["position"]) in ATTACKING_POSITIONS and extras[index][
                "understat_matched"
            ]:
                incumbent = float(row["expected_points"])
                challenger = predictions[index] * float(row["p_play"])
                blended = (1.0 - weight) * incumbent + weight * challenger
                delta = blended - incumbent
                row.update(
                    {
                        SCORE_FIELD: challenger,
                        "understat_weight": weight,
                        "understat_applied": True,
                        "expected_points": blended,
                        "robust_points": float(row["robust_points"]) + delta,
                    }
                )
                shifts.append(delta)
            else:
                row.update(
                    {SCORE_FIELD: None, "understat_weight": 0.0, "understat_applied": False}
                )
            output.append(row)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return forecast_rows, {**inactive, "reason": f"{type(error).__name__}: {error}"}
    return output, {
        "status": "applied",
        "decision_authority": True,
        "positions": list(ATTACKING_POSITIONS),
        "weight": weight,
        "applied_rows": len(shifts),
        "mean_expected_points_shift": float(np.mean(shifts)) if shifts else 0.0,
        "maximum_absolute_expected_points_shift": (
            float(np.max(np.abs(shifts))) if shifts else 0.0
        ),
        "mapping": mapping,
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Understat preseason feature challenger",
        "",
        f"Generated: {result['created_at']}",
        "",
        f"**Verdict: {result['verdict']}**",
        "",
        (
            "Understat is an independent player-stat source, not an expected-points oracle. "
            "Only the previous completed season is joined to each target season, and the current "
            "FPL forecast keeps ownership of minutes, availability, fixtures and point scoring."
        ),
        "",
        "## Time-forward player evidence",
        "",
        "| Season | Position | Match rows | Top-k lift | MAE lift |",
        "|---|---|---:|---:|---:|",
    ]
    for season in TEST_SEASONS:
        for position in ATTACKING_POSITIONS:
            row = result["oof"]["metrics"][season][position]
            lines.append(
                f"| {season} | {position} | {row['matched_rows']}/{row['rows']} | "
                f"{row['challenger_top_k'] - row['incumbent_top_k']:+.3f} | "
                f"{row['incumbent_mae'] - row['challenger_mae']:+.4f} |"
            )
    lines.extend(
        [
            "",
            "## Exact legal decision replay",
            "",
            f"Selected bounded blend: **{result['sequential_policy']['selected_weight']:.0%}**.",
            "",
        ]
    )
    for season, delta in result["sequential_policy"]["deltas_by_season"].items():
        lines.append(f"- {season}: {delta:+d} net points")
    lines.extend(
        [
            f"- Frozen independent weekly rebuilds: {result['independent_replay']['total_delta']:+d} points",
            "",
            "## Authority",
            "",
            result["production_policy"]["explanation"],
            "",
            (
                "FBref collection remains unimplemented because the automated endpoint returned "
                "HTTP 403. It is not silently substituted or counted as a second provider."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_understat_challenger() -> dict[str, Any]:
    require_cuda()
    ensure_engine_layout()
    print("Understat challenger: fitting season-forward player forecasts", flush=True)
    oof = build_understat_oof()
    grouped, _ = _load_event_rows(TEST_SEASONS)
    _inject_scores(grouped)
    sequential = _run_sequential_policy(
        grouped,
        score_field=SCORE_FIELD,
        label="Understat challenger",
        weights=WEIGHTS,
    )
    selected_weight = float(sequential["selected_weight"])
    independent = _independent_frozen_replay(
        grouped,
        weight=selected_weight,
        score_field=SCORE_FIELD,
    )
    forecast_checks = {}
    for season in TEST_SEASONS:
        for position in ATTACKING_POSITIONS:
            row = oof["metrics"][season][position]
            forecast_checks[f"positive_top_k_{season}_{position}"] = (
                row["challenger_top_k"] > row["incumbent_top_k"]
            )
            forecast_checks[f"nonnegative_mae_{season}_{position}"] = (
                row["challenger_mae"] <= row["incumbent_mae"]
            )
    decision_checks = {
        "nonzero_bounded_weight": 0.0 < selected_weight <= MAX_PRODUCTION_WEIGHT,
        "positive_development_seasons": all(
            sequential["deltas_by_season"][season] > 0 for season in DEVELOPMENT_SEASONS
        ),
        "positive_frozen_continuous_path": sequential["deltas_by_season"][
            FROZEN_TEST_SEASON
        ]
        > 0,
        "positive_frozen_independent_rebuilds": independent["total_delta"] > 0,
        "frozen_interval_not_materially_negative": sequential["frozen_interval"]["p025"]
        > -0.10,
    }
    checks = {**forecast_checks, **decision_checks}
    passed = all(checks.values())
    table = pq.read_table(TRAINING_FEATURES)
    matrix, _, mapping = external_feature_matrix(table)
    model = _train_final_models(table, matrix)
    verdict = "PROMOTE" if passed else "HOLD_SHADOW"
    current_table = pq.read_table(CURRENT_FEATURES)
    _, _, current_mapping = external_feature_matrix(current_table)
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "oof": oof,
        "sequential_policy": sequential,
        "independent_replay": independent,
        "gate": {"passed": passed, "checks": checks},
        "production_policy": {
            "decision_authority": passed,
            "positions": list(ATTACKING_POSITIONS),
            "weight": selected_weight if passed else 0.0,
            "maximum_weight": MAX_PRODUCTION_WEIGHT,
            "explanation": (
                "The bounded independent-data blend passed every forecast and legal-decision gate."
                if passed
                else "Understat remains shadow evidence because at least one time-forward gate failed."
            ),
        },
        "model": model,
        "mapping": {"historical": mapping, "current": current_mapping},
        "contract": {
            "target_season_uses": "previous completed EPL season only",
            "base_features": list(MODEL_FEATURES),
            "external_features": list(EXTERNAL_FEATURES),
            "official_fpl_expected_points_allowed": False,
            "source_manifests": [
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
                for path in sorted(MANIFESTS.glob("understat-EPL-*.json"))
            ],
        },
    }
    _atomic_json(RESULTS_JSON, result)
    external_receipt = {
        "version": 1,
        "created_at": result["created_at"],
        "providers": ["Understat"],
        "current": bool(current_mapping["coverage"].get("2026-27", {}).get("matched", 0)),
        "historical_time_forward_backtest": True,
        "decision_authority": passed,
        "understat_results": str(RESULTS_JSON),
        "understat_results_sha256": sha256_file(RESULTS_JSON),
        "current_mapping": current_mapping,
        "fbref_status": "not_collected_http_403",
    }
    _atomic_json(EXTERNAL_RECEIPT, external_receipt)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
