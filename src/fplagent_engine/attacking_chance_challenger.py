from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.metrics import mean_absolute_error

from fplagent_data.http import sha256_file

from .features import (
    ATTACKING_HISTORY_FEATURES,
    MODEL_FEATURES,
    TRAINING_FEATURES,
)
from .market_policy_replay import _score_solutions
from .market_transfer_replay import (
    _load_event_rows,
    moving_block_mean_interval,
    run_policy_season,
)
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
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve

OUTPUT_DIR = MODEL_DATA / "attacking_chance_v1"
OOF_FORECAST = OUTPUT_DIR / "rolling-forecasts.parquet"
MODEL_FILE = OUTPUT_DIR / "models.joblib"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "attacking-chance-quality-challenger.md"

TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
DEVELOPMENT_SEASONS = ("2023-24", "2024-25")
FROZEN_TEST_SEASON = "2025-26"
ATTACKING_POSITIONS = ("MID", "FWD")
SCORE_FIELD = "attacking_chance_expected_points"
MAX_PRODUCTION_WEIGHT = 0.20
WEIGHTS = (0.0, 0.10, 0.20)
SEEDS = (260_831, 260_911)

CHANCE_FEATURES = (
    "shrunk_xg_per90_5",
    "shrunk_xa_per90_5",
    "shrunk_xg_per90_10",
    "shrunk_xa_per90_10",
    "shrunk_xg_per90_38",
    "shrunk_xa_per90_38",
    "recent_xg_rate_gap",
    "recent_xa_rate_gap",
    "finishing_surplus_per90_10",
    "assist_surplus_per90_10",
    "xg_team_share_10",
    "xa_team_share_10",
    "team_allocated_xg",
    "team_allocated_xa",
    "attacking_minutes_proxy",
    "xg_history_minutes",
    "penalty_taker",
    "primary_set_piece_taker",
    "chance_history_available",
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            default=lambda item: item.item() if isinstance(item, np.generic) else str(item),
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def current_attacking_chance_inputs() -> dict[str, str | None]:
    """Hash optional challenger inputs so a promoted policy cannot be cached away."""
    try:
        result = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        authority = bool(result["production_policy"]["decision_authority"])
    except (OSError, KeyError, json.JSONDecodeError):
        authority = False
    if not authority:
        return {
            "attacking_chance_policy_sha256": None,
            "attacking_chance_model_sha256": None,
        }
    return {
        "attacking_chance_policy_sha256": sha256_file(RESULTS_JSON),
        "attacking_chance_model_sha256": sha256_file(MODEL_FILE),
    }


def _safe_numeric(table: pa.Table, name: str) -> np.ndarray:
    if name not in table.column_names:
        raise ValueError(f"Attacking chance feature table is missing {name!r}")
    return np.asarray(_numeric(table, name), dtype=np.float64)


def estimate_position_priors(
    table: pa.Table, selected: np.ndarray | None = None
) -> dict[str, dict[str, float]]:
    """Estimate leakage-safe positional xG/xA rates from lagged long-run histories."""
    positions = _strings(table, "position")
    if selected is None:
        selected = np.ones(table.num_rows, dtype=bool)
    minutes = _safe_numeric(table, "form38_minutes")
    output: dict[str, dict[str, float]] = {}
    defaults = {
        "GK": {"xg": 0.005, "xa": 0.005},
        "DEF": {"xg": 0.055, "xa": 0.065},
        "MID": {"xg": 0.220, "xa": 0.180},
        "FWD": {"xg": 0.360, "xa": 0.135},
    }
    for position in ("GK", "DEF", "MID", "FWD"):
        mask = selected & (positions == position) & np.isfinite(minutes) & (minutes > 0.0)
        rates = {}
        for kind in ("xg", "xa"):
            values = _safe_numeric(table, f"form38_{kind}")
            valid = mask & np.isfinite(values)
            if valid.sum() < 100:
                rates[kind] = defaults[position][kind]
                continue
            rate = 90.0 * float(np.sum(values[valid])) / float(np.sum(minutes[valid]))
            rates[kind] = float(np.clip(rate, 0.001, 1.5))
        output[position] = rates
    return output


def _shrunk_rate(
    average_events: np.ndarray,
    average_minutes: np.ndarray,
    event_counts: np.ndarray,
    priors: np.ndarray,
    prior_minutes: float,
) -> tuple[np.ndarray, np.ndarray]:
    exposure = np.clip(average_minutes, 0.0, 90.0) * event_counts
    totals = np.nan_to_num(average_events, nan=0.0) * event_counts
    rate = 90.0 * (totals + priors * prior_minutes / 90.0) / (exposure + prior_minutes)
    return np.clip(rate, 0.0, 2.5), exposure


def chance_quality_matrix(
    table: pa.Table,
    *,
    priors: dict[str, dict[str, float]],
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Add reproducible long-horizon chance-quality features to the champion matrix."""
    missing = sorted(set(ATTACKING_HISTORY_FEATURES) - set(table.column_names))
    if missing:
        raise ValueError(f"Attacking history contract is missing columns: {missing}")
    rows = table.to_pylist()
    positions = _strings(table, "position")
    history = np.nan_to_num(_safe_numeric(table, "history_events"), nan=0.0)
    availability = np.clip(
        np.nan_to_num(_safe_numeric(table, "availability_chance"), nan=0.0) / 100.0,
        0.0,
        1.0,
    )
    prior_xg = np.asarray([priors[str(position)]["xg"] for position in positions])
    prior_xa = np.asarray([priors[str(position)]["xa"] for position in positions])
    rates: dict[tuple[str, int], np.ndarray] = {}
    exposures: dict[int, np.ndarray] = {}
    for horizon, prior_minutes in ((5, 270.0), (10, 540.0), (38, 900.0)):
        count = np.minimum(history, float(horizon))
        minutes = _safe_numeric(table, f"form{horizon}_minutes")
        for kind, position_prior in (("xg", prior_xg), ("xa", prior_xa)):
            rate, exposure = _shrunk_rate(
                _safe_numeric(table, f"form{horizon}_{kind}"),
                minutes,
                count,
                position_prior,
                prior_minutes,
            )
            rates[(kind, horizon)] = rate
            exposures[horizon] = exposure

    count10 = np.minimum(history, 10.0)
    minutes10 = _safe_numeric(table, "form10_minutes")
    exposure10 = np.clip(minutes10, 0.0, 90.0) * count10
    finishing_surplus = (
        90.0
        * (
            np.nan_to_num(_safe_numeric(table, "form10_goals"), nan=0.0)
            - np.nan_to_num(_safe_numeric(table, "form10_xg"), nan=0.0)
        )
        * count10
        / (exposure10 + 900.0)
    )
    assist_surplus = (
        90.0
        * (
            np.nan_to_num(_safe_numeric(table, "form10_assists"), nan=0.0)
            - np.nan_to_num(_safe_numeric(table, "form10_xa"), nan=0.0)
        )
        * count10
        / (exposure10 + 900.0)
    )
    minutes_proxy = np.clip(np.nan_to_num(minutes10, nan=0.0), 0.0, 90.0) * availability
    goal_propensity = rates[("xg", 10)] * np.maximum(minutes_proxy, 10.0) / 90.0
    assist_propensity = rates[("xa", 10)] * np.maximum(minutes_proxy, 10.0) / 90.0
    grouped: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(str(row["season"]), int(row["event_number"]), int(row["team_id"]))].append(
            index
        )
    xg_share = np.zeros(table.num_rows, dtype=np.float64)
    xa_share = np.zeros(table.num_rows, dtype=np.float64)
    for indices in grouped.values():
        selected = np.asarray(indices, dtype=np.int64)
        xg_share[selected] = goal_propensity[selected] / max(
            float(goal_propensity[selected].sum()), 1e-9
        )
        xa_share[selected] = assist_propensity[selected] / max(
            float(assist_propensity[selected].sum()), 1e-9
        )
    team_goals = np.nan_to_num(_safe_numeric(table, "team_expected_goals"), nan=0.0)
    penalty_order = np.nan_to_num(_safe_numeric(table, "penalty_order"), nan=99.0)
    corner_order = np.nan_to_num(_safe_numeric(table, "corner_order"), nan=99.0)
    columns = {
        "shrunk_xg_per90_5": rates[("xg", 5)],
        "shrunk_xa_per90_5": rates[("xa", 5)],
        "shrunk_xg_per90_10": rates[("xg", 10)],
        "shrunk_xa_per90_10": rates[("xa", 10)],
        "shrunk_xg_per90_38": rates[("xg", 38)],
        "shrunk_xa_per90_38": rates[("xa", 38)],
        "recent_xg_rate_gap": rates[("xg", 5)] - rates[("xg", 38)],
        "recent_xa_rate_gap": rates[("xa", 5)] - rates[("xa", 38)],
        "finishing_surplus_per90_10": finishing_surplus,
        "assist_surplus_per90_10": assist_surplus,
        "xg_team_share_10": xg_share,
        "xa_team_share_10": xa_share,
        "team_allocated_xg": team_goals * xg_share,
        "team_allocated_xa": team_goals * 0.78 * xa_share,
        "attacking_minutes_proxy": minutes_proxy,
        "xg_history_minutes": exposures[38],
        "penalty_taker": (penalty_order == 1.0).astype(np.float64),
        "primary_set_piece_taker": (corner_order <= 2.0).astype(np.float64),
        "chance_history_available": (exposures[10] > 0.0).astype(np.float64),
    }
    extras = [
        {name: float(columns[name][index]) for name in CHANCE_FEATURES}
        for index in range(table.num_rows)
    ]
    augmented = np.column_stack(
        [
            _matrix(table),
            np.asarray(
                [[row[name] for name in CHANCE_FEATURES] for row in extras],
                dtype=np.float32,
            ),
        ]
    ).astype(np.float32, copy=False)
    return augmented, extras


def _incumbent_map() -> dict[tuple[str, int, int], dict[str, Any]]:
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }


def build_attacking_chance_oof() -> dict[str, Any]:
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(TRAINING_FEATURES)
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    target = _numeric(table, "target_points")
    minutes = _numeric(table, "target_minutes")
    rows = table.to_pylist()
    incumbent = _incumbent_map()
    output_rows: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    fit_receipts = []
    for season_offset, test_season in enumerate(TEST_SEASONS):
        training_seasons = sorted({str(value) for value in seasons if str(value) < test_season})
        training_scope = np.isin(seasons, training_seasons)
        priors = estimate_position_priors(table, training_scope)
        matrix, extras = chance_quality_matrix(table, priors=priors)
        metrics[test_season] = {}
        for position_offset, position in enumerate(ATTACKING_POSITIONS):
            training = training_scope & (positions == position) & (minutes > 0.0)
            testing = (seasons == test_season) & (positions == position)
            if training.sum() < 1_000 or testing.sum() < 100:
                raise ValueError(
                    f"Insufficient attacking rows for {test_season} {position}: "
                    f"{training.sum()}/{testing.sum()}"
                )
            predictions = []
            for seed_offset, seed in enumerate(SEEDS):
                model = _regressor(
                    seed + 100 * season_offset + 10 * position_offset + seed_offset,
                    650,
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
            challenge = np.clip(conditional * p_play, -2.0, 20.0)
            incumbent_prediction = np.asarray(
                [float(incumbent[key]["expected_points"]) for key in keys]
            )
            actual = target[testing]
            test_events = events[testing]
            metrics[test_season][position] = {
                "rows": len(indices),
                "training_rows": int(training.sum()),
                "incumbent_mae": float(mean_absolute_error(actual, incumbent_prediction)),
                "challenger_mae": float(mean_absolute_error(actual, challenge)),
                "incumbent_spearman": _gameweek_spearman(
                    test_events, actual, incumbent_prediction
                ),
                "challenger_spearman": _gameweek_spearman(test_events, actual, challenge),
                "incumbent_top_k": _mean_top_k_points(
                    test_events, actual, incumbent_prediction, TOP_K[position]
                ),
                "challenger_top_k": _mean_top_k_points(
                    test_events, actual, challenge, TOP_K[position]
                ),
            }
            fit_receipts.append(
                {
                    "test_season": test_season,
                    "training_seasons": training_seasons,
                    "position": position,
                    "training_rows": int(training.sum()),
                    "priors": priors,
                }
            )
            for local, index in enumerate(indices):
                output_rows.append(
                    {
                        "season": test_season,
                        "event_number": int(events[index]),
                        "element": int(rows[index]["element"]),
                        "player_name": str(rows[index]["player_name"]),
                        "position": position,
                        "team_id": int(rows[index]["team_id"]),
                        "target_points": float(actual[local]),
                        "p_play": float(p_play[local]),
                        "incumbent_expected_points": float(incumbent_prediction[local]),
                        SCORE_FIELD: float(challenge[local]),
                        **extras[index],
                    }
                )
    pq.write_table(pa.Table.from_pylist(output_rows), OOF_FORECAST, compression="zstd")
    return {
        "rows": len(output_rows),
        "metrics": metrics,
        "fits": fit_receipts,
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


def _season_replay_context() -> tuple[dict[str, Any], dict[str, dict[int, float]]]:
    current = load_rules()
    rules_by_season = {}
    curves = {}
    for season in TEST_SEASONS:
        rules = replace(current, max_free_transfers=2) if season == "2023-24" else current
        rules_by_season[season] = rules
        if season == "2023-24":
            curves[season] = {bank: 0.0 for bank in range(3)}
        else:
            curves[season], _ = load_terminal_free_transfer_curve(
                maximum=rules.max_free_transfers,
                rules=rules,
            )
    return rules_by_season, curves


def _run_sequential_policy(
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    *,
    score_field: str = SCORE_FIELD,
    label: str = "Attacking chance",
    weights: tuple[float, ...] = WEIGHTS,
) -> dict[str, Any]:
    rules, curves = _season_replay_context()
    incumbent = {}
    paths = {}
    for season in TEST_SEASONS:
        print(f"{label}: replaying {season} incumbent path", flush=True)
        incumbent[season] = run_policy_season(
            season=season,
            policy="incumbent_xp",
            grouped=grouped,
            market_weight=0.0,
            rules=rules[season],
            terminal_curve=curves[season],
        )
        paths[f"{season}:incumbent"] = incumbent[season]
    candidates = []
    development_paths = {}
    for weight in weights:
        deltas = {}
        for season in DEVELOPMENT_SEASONS:
            if weight == 0.0:
                path = incumbent[season]
            else:
                print(
                    f"{label}: replaying {season} at bounded weight {weight:.0%}",
                    flush=True,
                )
                path = run_policy_season(
                    season=season,
                    policy="attacking_chance",
                    grouped=grouped,
                    market_weight=weight,
                    rules=rules[season],
                    terminal_curve=curves[season],
                    score_field=score_field,
                )
            development_paths[(season, weight)] = path
            deltas[season] = path["net_points"] - incumbent[season]["net_points"]
        candidates.append(
            {
                "weight": weight,
                "season_deltas": deltas,
                "minimum_season_delta": min(deltas.values()),
                "total_delta": sum(deltas.values()),
            }
        )
    selected = max(
        candidates,
        key=lambda row: (
            row["minimum_season_delta"],
            row["total_delta"],
            -row["weight"],
        ),
    )
    weight = float(selected["weight"])
    for season in DEVELOPMENT_SEASONS:
        paths[f"{season}:challenger"] = development_paths[(season, weight)]
    print(
        f"{label}: opening frozen {FROZEN_TEST_SEASON} at {weight:.0%}",
        flush=True,
    )
    paths[f"{FROZEN_TEST_SEASON}:challenger"] = (
        incumbent[FROZEN_TEST_SEASON]
        if weight == 0.0
        else run_policy_season(
            season=FROZEN_TEST_SEASON,
            policy="attacking_chance",
            grouped=grouped,
            market_weight=weight,
            rules=rules[FROZEN_TEST_SEASON],
            terminal_curve=curves[FROZEN_TEST_SEASON],
            score_field=score_field,
        )
    )
    deltas_by_season = {
        season: (
            paths[f"{season}:challenger"]["net_points"]
            - paths[f"{season}:incumbent"]["net_points"]
        )
        for season in TEST_SEASONS
    }
    event_deltas = {
        season: [
            challenger["net_points"] - champion["net_points"]
            for challenger, champion in zip(
                paths[f"{season}:challenger"]["events"],
                paths[f"{season}:incumbent"]["events"],
                strict=True,
            )
        ]
        for season in TEST_SEASONS
    }
    pooled_out_of_selection = [
        *event_deltas["2023-24"],
        *event_deltas[FROZEN_TEST_SEASON],
    ]
    return {
        "selected_weight": weight,
        "selection_rule": (
            "maximise the worst 2023/24 and 2024/25 continuous-path delta, then total "
            "delta, then prefer the lower bounded weight"
        ),
        "candidates": candidates,
        "deltas_by_season": deltas_by_season,
        "frozen_interval": moving_block_mean_interval(
            event_deltas[FROZEN_TEST_SEASON], seed=20260831
        ),
        "pooled_out_of_selection_interval": moving_block_mean_interval(
            pooled_out_of_selection, seed=20260901
        ),
        "paths": paths,
    }


def _independent_frozen_replay(
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    *,
    weight: float,
    score_field: str = SCORE_FIELD,
) -> dict[str, Any]:
    rules = load_rules()
    rows_by_event = []
    for event in range(1, 39):
        rows = grouped[(FROZEN_TEST_SEASON, event)]
        champion = _solve(rows, [event], rules=rules)
        candidate_rows = [
            {
                **row,
                "expected_points": (
                    (1.0 - weight) * float(row["xp_expected_points"])
                    + weight * float(row[score_field])
                ),
            }
            for row in rows
        ]
        challenger = _solve(candidate_rows, [event], rules=rules)
        champion_points, challenger_points = _score_solutions(
            [("champion", champion), ("challenger", challenger)], rows, event
        )
        rows_by_event.append(
            {
                "event": event,
                "incumbent_points": champion_points,
                "challenger_points": challenger_points,
                "delta": challenger_points - champion_points,
                "same_squad": set(champion["selected"]) == set(challenger["selected"]),
                "same_captain": (
                    champion["lineups"][event]["captain"]
                    == challenger["lineups"][event]["captain"]
                ),
            }
        )
    deltas = [row["delta"] for row in rows_by_event]
    return {
        "weight": weight,
        "incumbent_points": sum(row["incumbent_points"] for row in rows_by_event),
        "challenger_points": sum(row["challenger_points"] for row in rows_by_event),
        "total_delta": sum(deltas),
        "interval": moving_block_mean_interval(deltas, seed=20260902),
        "same_squad_rate": float(np.mean([row["same_squad"] for row in rows_by_event])),
        "same_captain_rate": float(
            np.mean([row["same_captain"] for row in rows_by_event])
        ),
        "events": rows_by_event,
    }


def _train_final_models() -> dict[str, Any]:
    table = pq.read_table(TRAINING_FEATURES)
    positions = _strings(table, "position")
    minutes = _numeric(table, "target_minutes")
    target = _numeric(table, "target_points")
    priors = estimate_position_priors(table)
    matrix, _ = chance_quality_matrix(table, priors=priors)
    models = {}
    training_rows = {}
    for position_offset, position in enumerate(ATTACKING_POSITIONS):
        selected = (positions == position) & (minutes > 0.0)
        fitted = []
        for seed_offset, seed in enumerate(SEEDS):
            model = _regressor(seed + 1_000 + 10 * position_offset + seed_offset, 650, False)
            model.fit(matrix[selected], target[selected], verbose=False)
            fitted.append(model)
        models[position] = fitted
        training_rows[position] = int(selected.sum())
    bundle = {
        "version": "attacking_chance_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "base_features": MODEL_FEATURES,
        "chance_features": CHANCE_FEATURES,
        "history_features": ATTACKING_HISTORY_FEATURES,
        "positions": models,
        "position_priors": priors,
        "training_rows": training_rows,
        "seeds": SEEDS,
    }
    joblib.dump(bundle, MODEL_FILE, compress=3)
    return {
        "artifact": str(MODEL_FILE),
        "artifact_sha256": sha256_file(MODEL_FILE),
        "training_rows": training_rows,
        "position_priors": priors,
    }


def blend_current_attacking_predictions(
    feature_table: pa.Table,
    forecast_rows: list[dict[str, Any]],
    *,
    models: dict[str, list[Any]],
    priors: dict[str, dict[str, float]],
    weight: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not 0.0 < weight <= MAX_PRODUCTION_WEIGHT:
        raise ValueError("Live attacking chance weight exceeds its promotion bound")
    matrix, _ = chance_quality_matrix(feature_table, priors=priors)
    feature_rows = feature_table.to_pylist()
    by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): index
        for index, row in enumerate(feature_rows)
    }
    conditional_by_position = {}
    feature_positions = _strings(feature_table, "position")
    for position in ATTACKING_POSITIONS:
        indices = np.flatnonzero(feature_positions == position)
        conditional_by_position[position] = (
            indices,
            np.mean([model.predict(matrix[indices]) for model in models[position]], axis=0),
        )
    predictions = {}
    for position, (indices, values) in conditional_by_position.items():
        for local, index in enumerate(indices):
            predictions[(position, int(index))] = float(values[local])
    output = []
    deltas = []
    for raw in forecast_rows:
        row = dict(raw)
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        index = by_key.get(key)
        position = str(row["position"])
        incumbent = float(row["expected_points"])
        if index is not None and position in ATTACKING_POSITIONS:
            challenger = predictions[(position, index)] * float(row["p_play"])
            blended = (1.0 - weight) * incumbent + weight * challenger
            delta = blended - incumbent
            row.update(
                {
                    "incumbent_expected_points_before_attacking_chance": incumbent,
                    SCORE_FIELD: float(challenger),
                    "attacking_chance_weight": weight,
                    "attacking_chance_applied": True,
                    "expected_points": float(blended),
                    "robust_points": float(row["robust_points"]) + delta,
                }
            )
            deltas.append(delta)
        else:
            row.update(
                {
                    "incumbent_expected_points_before_attacking_chance": incumbent,
                    SCORE_FIELD: None,
                    "attacking_chance_weight": 0.0,
                    "attacking_chance_applied": False,
                }
            )
        output.append(row)
    return output, {
        "applied_rows": len(deltas),
        "mean_expected_points_shift": float(np.mean(deltas)) if deltas else 0.0,
        "maximum_absolute_expected_points_shift": (
            float(np.max(np.abs(deltas))) if deltas else 0.0
        ),
    }


def apply_current_attacking_chance_policy(
    feature_table: pa.Table,
    forecast_rows: list[dict[str, Any]],
    *,
    results_path: Path = RESULTS_JSON,
    model_path: Path = MODEL_FILE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inactive = {"status": "inactive", "decision_authority": False, "weight": 0.0}
    try:
        result = json.loads(results_path.read_text(encoding="utf-8"))
        policy = result["production_policy"]
        if not bool(policy.get("decision_authority")):
            return forecast_rows, {**inactive, "reason": "promotion gate is closed"}
        weight = float(policy.get("weight") or 0.0)
        expected_hash = str(result["model"]["artifact_sha256"])
        if sha256_file(model_path) != expected_hash:
            raise ValueError("Attacking chance model no longer matches its promotion receipt")
        bundle = joblib.load(model_path)
        output, diagnostics = blend_current_attacking_predictions(
            feature_table,
            forecast_rows,
            models=bundle["positions"],
            priors=bundle["position_priors"],
            weight=weight,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pa.ArrowException) as error:
        return forecast_rows, {**inactive, "reason": f"{type(error).__name__}: {error}"}
    return output, {
        "status": "applied",
        "decision_authority": True,
        "positions": list(ATTACKING_POSITIONS),
        "weight": weight,
        "policy": str(results_path),
        "policy_sha256": sha256_file(results_path),
        "model": str(model_path),
        "model_sha256": expected_hash,
        **diagnostics,
    }


def _render(result: dict[str, Any]) -> str:
    sequential = result["sequential_policy"]
    independent = result["independent_frozen_replay"]
    lines = [
        "# Attacking chance-quality challenger",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — the multi-season stability rule selected a bounded "
            f"{sequential['selected_weight']:.0%} blend. The untouched 2025/26 continuous "
            f"path changed by {sequential['deltas_by_season']['2025-26']:+d} net points; "
            f"independent legal weekly rebuilds changed by {independent['total_delta']:+d}."
        ),
        "",
        (
            "This challenger adds long-horizon xG/xA, per-90 rates, team attacking share and "
            "explicit finishing/assist surplus to the same deadline-safe features as the "
            "champion. It reuses the champion appearance probability, so this test isolates "
            "attacking quality rather than quietly changing predicted minutes."
        ),
        "",
        "## Season-forward forecast evidence",
        "",
        "| Season | Pos | Incumbent top-k | Challenger top-k | Lift | MAE lift |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for season in TEST_SEASONS:
        for position in ATTACKING_POSITIONS:
            row = result["oof"]["metrics"][season][position]
            lines.append(
                f"| {season} | {position} | {row['incumbent_top_k']:.3f} | "
                f"{row['challenger_top_k']:.3f} | "
                f"{row['challenger_top_k'] - row['incumbent_top_k']:+.3f} | "
                f"{row['incumbent_mae'] - row['challenger_mae']:+.4f} |"
            )
    lines.extend(
        [
            "",
            "## Continuous legal decision replay",
            "",
            "| Weight | 2023/24 | 2024/25 | Worst | Total |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sequential["candidates"]:
        lines.append(
            f"| {row['weight']:.0%} | {row['season_deltas']['2023-24']:+d} | "
            f"{row['season_deltas']['2024-25']:+d} | "
            f"{row['minimum_season_delta']:+d} | {row['total_delta']:+d} |"
        )
    lines.extend(
        [
            "",
            f"- Frozen 2025/26 continuous delta: **{sequential['deltas_by_season']['2025-26']:+d} points**.",
            f"- Frozen four-GW interval: **{sequential['frozen_interval']['p025']:+.3f} to {sequential['frozen_interval']['p975']:+.3f}/GW**.",
            f"- Independent frozen rebuild delta: **{independent['total_delta']:+d} points**.",
            f"- Independent squad agreement: **{independent['same_squad_rate']:.1%}**; captain agreement: **{independent['same_captain_rate']:.1%}**.",
            "",
            "## Promotion gate",
            "",
        ]
    )
    for name, passed in result["gate"]["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    lines.extend(
        [
            "",
            "## Live data contract",
            "",
            (
                "All added inputs are available after every finalized Gameweek from the official "
                "event-live archive: player minutes, goals, assists, xG and xA. Team expected "
                "goals, opponent context, prices, availability and set-piece order already exist "
                "in the deadline feature matrix. No Understat/FBref field is required to serve "
                "this model."
            ),
            "",
            (
                "A failed gate leaves the champion untouched. A pass permits only the recorded "
                "bounded MID/FWD blend, with hashes for the model, feature table and OOF forecast."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_attacking_chance_challenger() -> dict[str, Any]:
    require_cuda()
    print("Attacking chance: building season-forward forecasts", flush=True)
    oof = build_attacking_chance_oof()
    grouped, coverage = _load_event_rows(TEST_SEASONS)
    _inject_scores(grouped)
    sequential = _run_sequential_policy(grouped)
    independent = _independent_frozen_replay(
        grouped, weight=float(sequential["selected_weight"])
    )
    model = _train_final_models()
    forecast_checks = {}
    for season in TEST_SEASONS:
        rows = oof["metrics"][season]
        forecast_checks[f"positive_mean_top_k_lift_{season}"] = bool(
            np.mean(
                [
                    rows[position]["challenger_top_k"]
                    - rows[position]["incumbent_top_k"]
                    for position in ATTACKING_POSITIONS
                ]
            )
            > 0.0
        )
        forecast_checks[f"nonnegative_mean_mae_lift_{season}"] = bool(
            np.mean(
                [
                    rows[position]["incumbent_mae"]
                    - rows[position]["challenger_mae"]
                    for position in ATTACKING_POSITIONS
                ]
            )
            >= 0.0
        )
    decision_checks = {
        "nonzero_bounded_weight": (
            0.0 < sequential["selected_weight"] <= MAX_PRODUCTION_WEIGHT
        ),
        "positive_2023_24_continuous_path": (
            sequential["deltas_by_season"]["2023-24"] > 0
        ),
        "positive_2024_25_continuous_path": (
            sequential["deltas_by_season"]["2024-25"] > 0
        ),
        "positive_frozen_2025_26_continuous_path": (
            sequential["deltas_by_season"][FROZEN_TEST_SEASON] > 0
        ),
        "positive_frozen_independent_rebuilds": independent["total_delta"] > 0,
        "pooled_out_of_selection_lower_bound_above_minus_point_one": (
            sequential["pooled_out_of_selection_interval"]["p025"] > -0.10
        ),
    }
    checks = {**forecast_checks, **decision_checks}
    passed = bool(all(checks.values()))
    positive_shadow = bool(
        sequential["selected_weight"] > 0.0
        and sequential["deltas_by_season"][FROZEN_TEST_SEASON] > 0
        and independent["total_delta"] > 0
    )
    verdict = "PROMOTE" if passed else "HOLD_SHADOW" if positive_shadow else "REJECT"
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "oof": oof,
        "sequential_policy": sequential,
        "independent_frozen_replay": independent,
        "gate": {"passed": passed, "checks": checks},
        "production_policy": {
            "decision_authority": passed,
            "positions": list(ATTACKING_POSITIONS),
            "weight": float(sequential["selected_weight"]) if passed else 0.0,
            "maximum_weight": MAX_PRODUCTION_WEIGHT,
            "explanation": (
                "The bounded attacking chance blend passed forecast and exact legal decision gates."
                if passed
                else "The champion remains unchanged because at least one frozen promotion gate failed."
            ),
        },
        "model": model,
        "coverage": coverage,
        "contract": {
            "base_features": list(MODEL_FEATURES),
            "history_features": list(ATTACKING_HISTORY_FEATURES),
            "chance_features": list(CHANCE_FEATURES),
            "positions": list(ATTACKING_POSITIONS),
            "seeds": list(SEEDS),
            "development_seasons": list(DEVELOPMENT_SEASONS),
            "frozen_test_season": FROZEN_TEST_SEASON,
        },
        "artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "incumbent_forecast": str(BACKTEST_FORECAST),
            "incumbent_forecast_sha256": sha256_file(BACKTEST_FORECAST),
            "challenger_oof": str(OOF_FORECAST),
            "challenger_oof_sha256": sha256_file(OOF_FORECAST),
        },
    }
    _write_json(RESULTS_JSON, result)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
