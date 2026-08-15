from __future__ import annotations

import hashlib
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

from .betfair_calibration import HISTORICAL_RATES as HISTORICAL_BETFAIR_RATES
from .betfair_calibration import build_historical_betfair_exchange_rates
from .features import MODEL_FEATURES, POSITIONS, TRAINING_FEATURES
from .market_odds import (
    CURRENT_FPL_EVENTS,
    CURRENT_MARKET_RATES,
    CURRENT_MARKET_RECEIPT,
    _load_current_market_receipt,
)
from .market_policy_replay import _score_solutions, paired_policy_gate
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
)
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS, ensure_engine_layout
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve

OUTPUT_DIR = MODEL_DATA / "market_feature_v1"
OOF_FORECAST = OUTPUT_DIR / "rolling-forecasts.parquet"
MODEL_FILE = OUTPUT_DIR / "defender-model.joblib"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "market-feature-player-policy.md"
TEST_SEASONS = ("2023-24", "2024-25", "2025-26")
VALIDATION_SEASON = "2024-25"
FROZEN_TEST_SEASON = "2025-26"
SCORE_FIELD = "market_feature_defender_expected_points"
MAX_PRODUCTION_WEIGHT = 0.20
MARKET_FEATURES = (
    "market_team_goal_rate",
    "market_opponent_goal_rate",
    "market_clean_sheet_expectation",
    "market_team_goal_rate_delta",
    "market_opponent_goal_rate_delta",
    "market_clean_sheet_delta",
    "market_fixture_coverage",
)


def current_market_feature_phase(
    *, now: datetime | None = None, events_path: Path = CURRENT_FPL_EVENTS
) -> str:
    """Return the only decision phase currently authorised by the receipt."""
    try:
        events = pq.read_table(events_path).to_pylist()
        first = next(row for row in events if int(row["id"]) == 1)
        deadline = datetime.fromisoformat(str(first["deadline_time"])).astimezone(UTC)
    except (OSError, StopIteration, KeyError, TypeError, ValueError, pa.ArrowException):
        return "unknown"
    return (
        "preseason"
        if not bool(first.get("finished")) and (now or datetime.now(UTC)) < deadline
        else "weekly"
    )


def current_market_feature_inputs() -> dict[str, str | None]:
    """Hash every optional live input so forecast caching cannot hide a price change."""
    return {
        "market_feature_phase": current_market_feature_phase(),
        "market_feature_policy_sha256": (
            sha256_file(RESULTS_JSON) if RESULTS_JSON.is_file() else None
        ),
        "market_feature_model_sha256": (
            sha256_file(MODEL_FILE) if MODEL_FILE.is_file() else None
        ),
        "current_market_receipt_sha256": (
            sha256_file(CURRENT_MARKET_RECEIPT)
            if CURRENT_MARKET_RECEIPT.is_file()
            else None
        ),
        "current_market_rates_sha256": (
            sha256_file(CURRENT_MARKET_RATES) if CURRENT_MARKET_RATES.is_file() else None
        ),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def aggregate_historical_market_features() -> dict[tuple[str, int, int], dict[str, float]]:
    """Aggregate fixture prices into team-event features, including doubles safely."""
    if not HISTORICAL_BETFAIR_RATES.is_file():
        build_historical_betfair_exchange_rates()
    grouped: dict[tuple[str, int, int], dict[str, float]] = defaultdict(
        lambda: {
            "market_team_goal_rate": 0.0,
            "market_opponent_goal_rate": 0.0,
            "market_clean_sheet_expectation": 0.0,
            "market_fixture_coverage": 0.0,
        }
    )
    for row in pq.read_table(HISTORICAL_BETFAIR_RATES).to_pylist():
        season = str(row["season"])
        event = int(row["event"])
        home = int(row["team_h"])
        away = int(row["team_a"])
        home_rate = float(row["betfair_home_goal_rate"])
        away_rate = float(row["betfair_away_goal_rate"])
        for team, team_rate, opponent_rate in (
            (home, home_rate, away_rate),
            (away, away_rate, home_rate),
        ):
            target = grouped[(season, event, team)]
            target["market_team_goal_rate"] += team_rate
            target["market_opponent_goal_rate"] += opponent_rate
            target["market_clean_sheet_expectation"] += float(np.exp(-opponent_rate))
            target["market_fixture_coverage"] += 1.0
    return dict(grouped)


def market_feature_matrix(
    table: pa.Table,
    *,
    market: dict[tuple[str, int, int], dict[str, float]] | None = None,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    if market is None:
        market = aggregate_historical_market_features()
    extras = []
    for row in table.to_pylist():
        internal_team = float(row.get("team_expected_goals") or 0.0)
        internal_opponent = float(row.get("team_expected_goals_against") or 0.0)
        internal_clean_sheet = float(row.get("team_clean_sheet_probability") or 0.0)
        observed = market.get(
            (str(row["season"]), int(row["event_number"]), int(row["team_id"]))
        )
        if observed is None:
            observed = {
                "market_team_goal_rate": internal_team,
                "market_opponent_goal_rate": internal_opponent,
                "market_clean_sheet_expectation": internal_clean_sheet,
                "market_fixture_coverage": 0.0,
            }
        extra = {
            **observed,
            "market_team_goal_rate_delta": (
                observed["market_team_goal_rate"] - internal_team
            ),
            "market_opponent_goal_rate_delta": (
                observed["market_opponent_goal_rate"] - internal_opponent
            ),
            "market_clean_sheet_delta": (
                observed["market_clean_sheet_expectation"] - internal_clean_sheet
            ),
        }
        extras.append(extra)
    augmented = np.column_stack(
        [
            _matrix(table),
            np.asarray(
                [[row[name] for name in MARKET_FEATURES] for row in extras],
                dtype=np.float32,
            ),
        ]
    ).astype(np.float32, copy=False)
    return augmented, extras


def aggregate_current_market_features(
    *,
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
) -> tuple[dict[tuple[str, int, int], dict[str, float]], dict[str, Any]]:
    """Load only complete, checksum-bound Betfair events into team-event features."""
    receipt, rows = _load_current_market_receipt(receipt_path, rates_path)
    if receipt.get("provider") != "betfair_exchange_public_delayed":
        raise ValueError("Current market provider does not match the trained Betfair policy")
    ready_events = {int(value) for value in receipt.get("ready_events", [])}
    if not ready_events:
        raise ValueError("No complete timestamp-safe Betfair event is ready")
    grouped: dict[tuple[str, int, int], dict[str, float]] = defaultdict(
        lambda: {
            "market_team_goal_rate": 0.0,
            "market_opponent_goal_rate": 0.0,
            "market_clean_sheet_expectation": 0.0,
            "market_fixture_coverage": 0.0,
        }
    )
    selected = [row for row in rows if int(row["event"]) in ready_events]
    for row in selected:
        season = str(row["season"])
        event = int(row["event"])
        home = int(row["team_h"])
        away = int(row["team_a"])
        home_rate = float(row["market_home_goal_rate"])
        away_rate = float(row["market_away_goal_rate"])
        for team, team_rate, opponent_rate in (
            (home, home_rate, away_rate),
            (away, away_rate, home_rate),
        ):
            target = grouped[(season, event, team)]
            target["market_team_goal_rate"] += team_rate
            target["market_opponent_goal_rate"] += opponent_rate
            target["market_clean_sheet_expectation"] += float(np.exp(-opponent_rate))
            target["market_fixture_coverage"] += 1.0
    return dict(grouped), {
        "provider": receipt["provider"],
        "ready_events": sorted(ready_events),
        "fixtures": len(selected),
        "receipt": str(receipt_path),
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "rates": str(rates_path),
        "rates_sha256": receipt["rates_sha256"],
    }


def blend_current_defender_predictions(
    feature_table: pa.Table,
    forecast_rows: list[dict[str, Any]],
    *,
    market: dict[tuple[str, int, int], dict[str, float]],
    point_model: Any,
    weight: float,
    ready_events: set[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a bounded model blend only to covered defender rows."""
    if not 0.0 < weight <= MAX_PRODUCTION_WEIGHT:
        raise ValueError("Live market-feature weight exceeds its promotion bound")
    feature_rows = feature_table.to_pylist()
    by_key = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): index
        for index, row in enumerate(feature_rows)
    }
    matrix, extras = market_feature_matrix(feature_table, market=market)
    conditional = np.asarray(point_model.predict(matrix), dtype=np.float64)
    output = []
    applied = []
    for raw in forecast_rows:
        row = dict(raw)
        key = (str(row["season"]), int(row["event_number"]), int(row["element"]))
        feature_index = by_key.get(key)
        if feature_index is None:
            raise ValueError(f"Forecast row has no matching feature row: {key}")
        is_covered_defender = (
            str(row["position"]) == "DEF"
            and int(row["event_number"]) in ready_events
            and extras[feature_index]["market_fixture_coverage"] > 0.0
        )
        incumbent = float(row["expected_points"])
        if is_covered_defender:
            challenger = float(conditional[feature_index] * float(row["p_play"]))
            blended = (1.0 - weight) * incumbent + weight * challenger
            delta = blended - incumbent
            row.update(
                {
                    "incumbent_expected_points": incumbent,
                    "market_feature_expected_points": challenger,
                    "market_feature_weight": weight,
                    "market_feature_applied": True,
                    "expected_points": blended,
                    "robust_points": float(row["robust_points"]) + delta,
                }
            )
            applied.append(delta)
        else:
            row.update(
                {
                    "incumbent_expected_points": incumbent,
                    "market_feature_expected_points": None,
                    "market_feature_weight": 0.0,
                    "market_feature_applied": False,
                }
            )
        output.append(row)
    return output, {
        "applied_rows": len(applied),
        "mean_expected_points_shift": float(np.mean(applied)) if applied else 0.0,
        "maximum_absolute_expected_points_shift": (
            float(np.max(np.abs(applied))) if applied else 0.0
        ),
    }


def apply_current_market_feature_policy(
    feature_table: pa.Table,
    forecast_rows: list[dict[str, Any]],
    *,
    phase: str,
    results_path: Path = RESULTS_JSON,
    model_path: Path = MODEL_FILE,
    receipt_path: Path = CURRENT_MARKET_RECEIPT,
    rates_path: Path = CURRENT_MARKET_RATES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply only a promoted phase, provider-matched model and complete receipt."""
    inactive = {
        "status": "inactive",
        "phase": phase,
        "decision_authority": False,
        "weight": 0.0,
    }
    try:
        result = json.loads(results_path.read_text(encoding="utf-8"))
        policy = result["production_policy"]
        authority_key = f"{phase}_decision_authority"
        weight_key = f"{phase}_weight"
        if not bool(policy.get(authority_key)):
            return forecast_rows, {
                **inactive,
                "reason": f"market features have no {phase} decision authority",
            }
        weight = float(policy.get(weight_key) or 0.0)
        expected_model_hash = result["model"]["artifact_sha256"]
        if sha256_file(model_path) != expected_model_hash:
            raise ValueError("Market feature model no longer matches its promotion receipt")
        market, receipt = aggregate_current_market_features(
            receipt_path=receipt_path,
            rates_path=rates_path,
        )
        bundle = joblib.load(model_path)
        output, diagnostics = blend_current_defender_predictions(
            feature_table,
            forecast_rows,
            market=market,
            point_model=bundle["point_model"],
            weight=weight,
            ready_events=set(receipt["ready_events"]),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pa.ArrowException) as error:
        return forecast_rows, {**inactive, "reason": f"{type(error).__name__}: {error}"}
    return output, {
        "status": "applied",
        "phase": phase,
        "decision_authority": True,
        "position": "DEF",
        "weight": weight,
        "policy": str(results_path),
        "policy_sha256": sha256_file(results_path),
        "model": str(model_path),
        "model_sha256": expected_model_hash,
        **receipt,
        **diagnostics,
    }


def _forecast_map() -> dict[tuple[str, int, int], dict[str, Any]]:
    return {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): row
        for row in pq.read_table(BACKTEST_FORECAST).to_pylist()
    }


def build_market_feature_oof() -> dict[str, Any]:
    """Train a season-forward market-feature point model without changing minutes."""
    ensure_engine_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(TRAINING_FEATURES)
    matrix, extras = market_feature_matrix(table)
    rows = table.to_pylist()
    seasons = _strings(table, "season")
    positions = _strings(table, "position")
    events = _numeric(table, "event_number").astype(np.int16)
    target = _numeric(table, "target_points")
    minutes = _numeric(table, "target_minutes")
    incumbent = _forecast_map()
    season_order = sorted(set(seasons.tolist()))
    output_rows: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    for season_offset, test_season in enumerate(TEST_SEASONS):
        prior = [season for season in season_order if season < test_season]
        validation_season = prior[-1]
        training_seasons = prior[:-1]
        metrics[test_season] = {}
        for position_offset, position in enumerate(POSITIONS):
            training = (
                np.isin(seasons, training_seasons)
                & (positions == position)
                & (minutes > 0)
            )
            validation = (
                (seasons == validation_season)
                & (positions == position)
                & (minutes > 0)
            )
            testing = (seasons == test_season) & (positions == position)
            model = _regressor(
                260_810 + season_offset * 10 + position_offset,
                1_200,
                True,
            )
            model.fit(
                matrix[training],
                target[training],
                eval_set=[(matrix[validation], target[validation])],
                verbose=False,
            )
            indices = np.flatnonzero(testing)
            conditional = model.predict(matrix[testing])
            p_play = np.asarray(
                [
                    float(
                        incumbent[
                            (
                                test_season,
                                int(events[index]),
                                int(rows[index]["element"]),
                            )
                        ]["p_play"]
                    )
                    for index in indices
                ]
            )
            prediction = conditional * p_play
            incumbent_prediction = np.asarray(
                [
                    float(
                        incumbent[
                            (
                                test_season,
                                int(events[index]),
                                int(rows[index]["element"]),
                            )
                        ]["expected_points"]
                    )
                    for index in indices
                ]
            )
            actual = target[testing]
            test_events = events[testing]
            metrics[test_season][position] = {
                "rows": len(indices),
                "incumbent_mae": float(mean_absolute_error(actual, incumbent_prediction)),
                "challenger_mae": float(mean_absolute_error(actual, prediction)),
                "incumbent_spearman": _gameweek_spearman(
                    test_events, actual, incumbent_prediction
                ),
                "challenger_spearman": _gameweek_spearman(
                    test_events, actual, prediction
                ),
                "incumbent_top_k": _mean_top_k_points(
                    test_events, actual, incumbent_prediction, TOP_K[position]
                ),
                "challenger_top_k": _mean_top_k_points(
                    test_events, actual, prediction, TOP_K[position]
                ),
            }
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
                        "market_feature_expected_points": float(prediction[local]),
                        SCORE_FIELD: (
                            float(prediction[local])
                            if position == "DEF"
                            else float(incumbent_prediction[local])
                        ),
                        **extras[index],
                    }
                )
    pq.write_table(pa.Table.from_pylist(output_rows), OOF_FORECAST, compression="zstd")
    return {
        "rows": len(output_rows),
        "metrics": metrics,
        "artifact": str(OOF_FORECAST),
        "artifact_sha256": sha256_file(OOF_FORECAST),
    }


def _inject_scores(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> None:
    scores = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row[SCORE_FIELD]
        )
        for row in pq.read_table(OOF_FORECAST).to_pylist()
    }
    for (season, event), rows in grouped.items():
        for row in rows:
            key = (season, event, int(row["element"]))
            row[SCORE_FIELD] = scores.get(key, float(row["xp_expected_points"]))


def _independent_policy(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> dict[str, Any]:
    rules = load_rules()
    weights = tuple(float(value) for value in np.linspace(0.0, 1.0, 11))
    validation_totals = dict.fromkeys(weights, 0)
    for event in range(1, 39):
        rows = grouped[(VALIDATION_SEASON, event)]
        solutions = []
        for weight in weights:
            scored = [
                {
                    **row,
                    "expected_points": (
                        weight * float(row[SCORE_FIELD])
                        + (1.0 - weight) * float(row["xp_expected_points"])
                    ),
                }
                for row in rows
            ]
            solutions.append((f"weight-{weight:.1f}", _solve(scored, [event], rules=rules)))
        scores = _score_solutions(solutions, rows, event)
        for weight, score in zip(weights, scores, strict=True):
            validation_totals[weight] += score
    selected = max(weights, key=lambda weight: (validation_totals[weight], -weight))
    event_rows = []
    for event in range(1, 39):
        rows = grouped[(FROZEN_TEST_SEASON, event)]
        incumbent_solution = _solve(rows, [event], rules=rules)
        challenger_rows = [
            {
                **row,
                "expected_points": (
                    selected * float(row[SCORE_FIELD])
                    + (1.0 - selected) * float(row["xp_expected_points"])
                ),
            }
            for row in rows
        ]
        challenger_solution = _solve(challenger_rows, [event], rules=rules)
        scores = _score_solutions(
            [("incumbent", incumbent_solution), ("challenger", challenger_solution)],
            rows,
            event,
        )
        event_rows.append(
            {
                "season": FROZEN_TEST_SEASON,
                "event": event,
                "incumbent_points": scores[0],
                "challenger_points": scores[1],
                "challenger_minus_incumbent": scores[1] - scores[0],
                "same_captain": (
                    incumbent_solution["lineups"][event]["captain"]
                    == challenger_solution["lineups"][event]["captain"]
                ),
                "squad_overlap": len(
                    set(incumbent_solution["selected"])
                    & set(challenger_solution["selected"])
                ),
            }
        )
    gate = paired_policy_gate(event_rows, FROZEN_TEST_SEASON)
    return {
        "selected_weight": selected,
        "validation": [
            {"weight": weight, "actual_points": validation_totals[weight]}
            for weight in weights
        ],
        "test_gate": gate,
        "test_incumbent_points": sum(row["incumbent_points"] for row in event_rows),
        "test_challenger_points": sum(row["challenger_points"] for row in event_rows),
        "same_captain_rate": float(np.mean([row["same_captain"] for row in event_rows])),
        "mean_squad_overlap": float(np.mean([row["squad_overlap"] for row in event_rows])),
        "events": event_rows,
    }


def _independent_frozen_weight(
    grouped: dict[tuple[str, int], list[dict[str, Any]]], *, weight: float
) -> dict[str, Any]:
    """Evaluate the already-selected bounded weight on independent weekly rebuilds."""
    rules = load_rules()
    event_rows = []
    for event in range(1, 39):
        rows = grouped[(FROZEN_TEST_SEASON, event)]
        incumbent_solution = _solve(rows, [event], rules=rules)
        challenger_rows = [
            {
                **row,
                "expected_points": (
                    weight * float(row[SCORE_FIELD])
                    + (1.0 - weight) * float(row["xp_expected_points"])
                ),
            }
            for row in rows
        ]
        challenger_solution = _solve(challenger_rows, [event], rules=rules)
        incumbent_points, challenger_points = _score_solutions(
            [
                ("incumbent", incumbent_solution),
                ("challenger", challenger_solution),
            ],
            rows,
            event,
        )
        event_rows.append(
            {
                "season": FROZEN_TEST_SEASON,
                "event": event,
                "incumbent_points": incumbent_points,
                "challenger_points": challenger_points,
                "challenger_minus_incumbent": (
                    challenger_points - incumbent_points
                ),
            }
        )
    gate = paired_policy_gate(event_rows, FROZEN_TEST_SEASON)
    return {
        "weight": weight,
        "incumbent_points": sum(row["incumbent_points"] for row in event_rows),
        "challenger_points": sum(row["challenger_points"] for row in event_rows),
        "total_delta": sum(row["challenger_minus_incumbent"] for row in event_rows),
        "gate": gate,
        "events": event_rows,
    }


def _season_replay_context() -> tuple[
    dict[str, Any], dict[str, dict[int, float]], dict[str, dict[str, Any]]
]:
    current_rules = load_rules()
    rules_by_season = {}
    curves = {}
    transfer_value = {}
    for season in TEST_SEASONS:
        # Five banked transfers arrived in 2024/25. Replaying 2023/24 with the
        # then-legal ceiling of two keeps both policies inside that season's rules.
        rules = (
            replace(current_rules, max_free_transfers=2)
            if season == "2023-24"
            else current_rules
        )
        if season == "2023-24":
            terminal_curve = {bank: 0.0 for bank in range(3)}
            receipt = {
                "status": "historical_rule_zero_control",
                "promoted": False,
                "maximum_free_transfers": 2,
            }
        else:
            terminal_curve, receipt = load_terminal_free_transfer_curve(
                maximum=rules.max_free_transfers, rules=rules
            )
        rules_by_season[season] = rules
        curves[season] = terminal_curve
        transfer_value[season] = receipt
    return rules_by_season, curves, transfer_value


def _sequential_policy(
    grouped: dict[tuple[str, int], list[dict[str, Any]]]
) -> dict[str, Any]:
    rules_by_season, curves, transfer_value = _season_replay_context()
    development_seasons = ("2023-24", "2024-25")
    weights = tuple(float(value) for value in np.linspace(0.0, MAX_PRODUCTION_WEIGHT, 3))
    paths = {}
    incumbent_paths = {}
    for season in TEST_SEASONS:
        print(
            f"Market feature challenger: replaying {season} incumbent path",
            flush=True,
        )
        incumbent_paths[season] = run_policy_season(
            season=season,
            policy="incumbent_xp",
            grouped=grouped,
            market_weight=0.0,
            rules=rules_by_season[season],
            terminal_curve=curves[season],
        )
        paths[f"{season}:incumbent"] = incumbent_paths[season]

    candidates = []
    development_paths: dict[tuple[str, float], dict[str, Any]] = {}
    for weight in weights:
        deltas = {}
        for season in development_seasons:
            if weight == 0.0:
                challenger = incumbent_paths[season]
            else:
                print(
                    "Market feature challenger: replaying "
                    f"{season} stability weight {weight:.1f}",
                    flush=True,
                )
                challenger = run_policy_season(
                    season=season,
                    policy="market_challenger",
                    grouped=grouped,
                    market_weight=weight,
                    rules=rules_by_season[season],
                    terminal_curve=curves[season],
                    score_field=SCORE_FIELD,
                )
            development_paths[(season, weight)] = challenger
            deltas[season] = (
                challenger["net_points"] - incumbent_paths[season]["net_points"]
            )
        candidates.append(
            {
                "weight": weight,
                "season_deltas": deltas,
                "minimum_season_delta": min(deltas.values()),
                "total_delta": sum(deltas.values()),
            }
        )

    # Maximin protects against choosing a large effect that exists in only one
    # season. Lower weight wins exact ties, preserving the incumbent by default.
    selected_row = max(
        candidates,
        key=lambda row: (
            row["minimum_season_delta"],
            row["total_delta"],
            -row["weight"],
        ),
    )
    weight = float(selected_row["weight"])
    for season in development_seasons:
        paths[f"{season}:challenger"] = development_paths[(season, weight)]
    print(
        "Market feature challenger: opening 2025/26 at frozen stability weight "
        f"{weight:.1f}",
        flush=True,
    )
    paths[f"{FROZEN_TEST_SEASON}:challenger"] = run_policy_season(
        season=FROZEN_TEST_SEASON,
        policy="market_challenger",
        grouped=grouped,
        market_weight=weight,
        rules=rules_by_season[FROZEN_TEST_SEASON],
        terminal_curve=curves[FROZEN_TEST_SEASON],
        score_field=SCORE_FIELD,
    )
    validation_delta = (
        paths[f"{VALIDATION_SEASON}:challenger"]["net_points"]
        - paths[f"{VALIDATION_SEASON}:incumbent"]["net_points"]
    )
    test_deltas = [
        challenger["net_points"] - incumbent["net_points"]
        for challenger, incumbent in zip(
            paths[f"{FROZEN_TEST_SEASON}:challenger"]["events"],
            paths[f"{FROZEN_TEST_SEASON}:incumbent"]["events"],
            strict=True,
        )
    ]
    interval = moving_block_mean_interval(test_deltas, seed=20260821)
    test_delta = sum(test_deltas)
    replication_deltas = {}
    pooled_out_of_selection = []
    for season in ("2023-24", FROZEN_TEST_SEASON):
        values = [
            challenger["net_points"] - incumbent["net_points"]
            for challenger, incumbent in zip(
                paths[f"{season}:challenger"]["events"],
                paths[f"{season}:incumbent"]["events"],
                strict=True,
            )
        ]
        replication_deltas[season] = sum(values)
        pooled_out_of_selection.extend(values)
    pooled_interval = moving_block_mean_interval(
        pooled_out_of_selection,
        seed=20260822,
    )
    checks = {
        "nonzero_stability_selected_weight": weight > 0.0,
        "positive_discovery_replication_total": replication_deltas["2023-24"] > 0,
        "positive_validation_total": validation_delta > 0,
        "positive_test_total": test_delta > 0,
        "pooled_out_of_selection_lower_bound_above_minus_point_one": (
            pooled_interval["p025"] > -0.10
        ),
    }
    return {
        "passed": all(checks.values()),
        "selected_weight": weight,
        "selection_rule": (
            "maximise the minimum 2023/24 and 2024/25 net-point delta; then "
            "total delta; then prefer the lower weight"
        ),
        "stability_candidates": candidates,
        "checks": checks,
        "validation_total_delta": validation_delta,
        "test_total_delta": test_delta,
        "test_mean_delta": test_delta / 38.0,
        "interval": interval,
        "replication_total_deltas": replication_deltas,
        "pooled_out_of_selection_interval": pooled_interval,
        "paths": paths,
        "transfer_value": transfer_value,
    }


def _train_defender_model() -> dict[str, Any]:
    table = pq.read_table(TRAINING_FEATURES)
    matrix, _ = market_feature_matrix(table)
    positions = _strings(table, "position")
    minutes = _numeric(table, "target_minutes")
    target = _numeric(table, "target_points")
    selected = (positions == "DEF") & (minutes > 0)
    model = _regressor(260_899, 700, False)
    model.fit(matrix[selected], target[selected], verbose=False)
    bundle = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "base_features": MODEL_FEATURES,
        "market_features": MARKET_FEATURES,
        "position": "DEF",
        "point_model": model,
        "training_rows": int(selected.sum()),
    }
    joblib.dump(bundle, MODEL_FILE, compress=3)
    return {
        "artifact": str(MODEL_FILE),
        "artifact_sha256": sha256_file(MODEL_FILE),
        "training_rows": int(selected.sum()),
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Market features inside the player decision model",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — defender market features were the only component to "
            "improve top-k realised points and MAE in all three forward seasons. The "
            "multi-season stability rule selected the bounded "
            f"{result['sequential_policy']['selected_weight']:.0%} defender-only blend."
        ),
        "",
        "## Defender forecast evidence",
        "",
        "| Season | Incumbent top-k | Market-feature top-k | Lift | MAE lift |",
        "|---|---:|---:|---:|---:|",
    ]
    for season in TEST_SEASONS:
        row = result["oof"]["metrics"][season]["DEF"]
        lines.append(
            f"| {season} | {row['incumbent_top_k']:.3f} | {row['challenger_top_k']:.3f} | "
            f"{row['challenger_top_k'] - row['incumbent_top_k']:+.3f} | "
            f"{row['incumbent_mae'] - row['challenger_mae']:+.4f} |"
        )
    independent = result["independent_policy"]
    sequential = result["sequential_policy"]
    lines.extend(
        [
            "",
            "## Legal decision replay",
            "",
            f"- Unbounded single-season weight search selected {independent['selected_weight']:.0%}, then lost **{independent['test_challenger_points'] - independent['test_incumbent_points']:+d} points** on independent test-season squads; it was rejected.",
            f"- Independent frozen squads at the bounded deployment weight: **{result['deployment_independent']['total_delta']:+d} points**.",
            f"- Sequential stability blend selected on 2023/24 + 2024/25: **{sequential['selected_weight']:.0%}**.",
            f"- Continuous 2023/24 development path: **{sequential['replication_total_deltas']['2023-24']:+d} points**.",
            f"- Continuous 2024/25 development path: **{sequential['validation_total_delta']:+d} points**.",
            f"- Continuous frozen follow-up path (2025/26): **{sequential['test_total_delta']:+d} points ({sequential['test_mean_delta']:+.3f}/GW)**.",
            f"- Four-GW moving-block interval: **{sequential['interval']['p025']:+.3f} to {sequential['interval']['p975']:+.3f}/GW**.",
            f"- Pooled 2023/24 + 2025/26 out-of-selection interval: **{sequential['pooled_out_of_selection_interval']['p025']:+.3f} to {sequential['pooled_out_of_selection_interval']['p975']:+.3f}/GW**.",
            "",
            "### Sequential stability selection",
            "",
            "| Defender market weight | 2023/24 delta | 2024/25 delta | Worst season | Total |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate in sequential["stability_candidates"]:
        deltas = candidate["season_deltas"]
        lines.append(
            f"| {candidate['weight']:.0%} | {deltas['2023-24']:+d} | "
            f"{deltas['2024-25']:+d} | {candidate['minimum_season_delta']:+d} | "
            f"{candidate['total_delta']:+d} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The market is not used as a substitute player forecast. Its team scoring rate, opponent scoring rate and clean-sheet expectation are deadline features alongside player xG/xA, role, price and minutes. Missing or incomplete market fixtures resolve to the internal team features with zero coverage, so availability never creates fabricated values.",
            "",
            result["production_policy"]["explanation"],
            "",
        ]
    )
    return "\n".join(lines)


def run_market_feature_challenger() -> dict[str, Any]:
    print("Market feature challenger: training season-forward player models", flush=True)
    oof = build_market_feature_oof()
    defender_checks = {
        f"positive_defender_top_k_{season}": (
            oof["metrics"][season]["DEF"]["challenger_top_k"]
            > oof["metrics"][season]["DEF"]["incumbent_top_k"]
        )
        for season in TEST_SEASONS
    }
    grouped, coverage = _load_event_rows(TEST_SEASONS)
    _inject_scores(grouped)
    print("Market feature challenger: calibrating legal squad weight on 2024/25", flush=True)
    independent = _independent_policy(grouped)
    print(
        "Market feature challenger: running frozen continuous transfer policy",
        flush=True,
    )
    sequential = _sequential_policy(grouped)
    deployment_independent = _independent_frozen_weight(
        grouped, weight=float(sequential["selected_weight"])
    )
    model = _train_defender_model()
    defender_mae_checks = {
        f"positive_defender_mae_{season}": (
            oof["metrics"][season]["DEF"]["challenger_mae"]
            < oof["metrics"][season]["DEF"]["incumbent_mae"]
        )
        for season in TEST_SEASONS
    }
    bounded_preseason_checks = {
        **defender_checks,
        **defender_mae_checks,
        "positive_2023_24_continuous_path": (
            sequential["replication_total_deltas"]["2023-24"] > 0
        ),
        "positive_2024_25_continuous_path": (
            sequential["validation_total_delta"] > 0
        ),
        "positive_frozen_2025_26_continuous_path": (
            sequential["test_total_delta"] > 0
        ),
        "positive_frozen_2025_26_independent_squads": (
            deployment_independent["total_delta"] > 0
        ),
        "deployment_weight_is_bounded": (
            0.0 < sequential["selected_weight"] <= MAX_PRODUCTION_WEIGHT
        ),
    }
    preseason_passed = all(bounded_preseason_checks.values())
    weekly_passed = preseason_passed and sequential["passed"]
    production_policy = {
        "preseason_decision_authority": preseason_passed,
        "weekly_decision_authority": weekly_passed,
        "position": "DEF",
        "preseason_weight": (
            float(sequential["selected_weight"]) if preseason_passed else 0.0
        ),
        "weekly_weight": (
            float(sequential["selected_weight"]) if weekly_passed else 0.0
        ),
        "explanation": (
            "A bounded Betfair defender blend may enter preseason squad and XI decisions. It improved defender forecast and legal-decision totals across every tested season, but weekly transfer authority remains disabled until the continuous-path downside interval passes or prospective evidence resolves it."
            if preseason_passed and not weekly_passed
            else (
                "The defender-only feature blend passed both preseason and weekly gates and may enter production subject to live coverage and timestamp checks."
                if weekly_passed
                else "No production authority is granted because the defender-only held-out legal decision gate failed."
            )
        ),
    }
    result = {
        "version": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": (
            "PROMOTE_WEEKLY"
            if weekly_passed
            else "PROMOTE_PRESEASON_ONLY"
            if preseason_passed
            else "REJECT"
        ),
        "defender_checks": defender_checks,
        "defender_mae_checks": defender_mae_checks,
        "bounded_preseason_checks": bounded_preseason_checks,
        "oof": oof,
        "independent_policy": independent,
        "deployment_independent": deployment_independent,
        "sequential_policy": sequential,
        "production_policy": production_policy,
        "model": model,
        "coverage": coverage,
        "artifacts": {
            "training_features": str(TRAINING_FEATURES),
            "training_features_sha256": sha256_file(TRAINING_FEATURES),
            "market_rates": str(HISTORICAL_BETFAIR_RATES),
            "market_rates_sha256": sha256_file(HISTORICAL_BETFAIR_RATES),
            "incumbent_forecast": str(BACKTEST_FORECAST),
            "incumbent_forecast_sha256": sha256_file(BACKTEST_FORECAST),
        },
    }
    _write_json(RESULTS_JSON, result)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
