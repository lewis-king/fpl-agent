from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .component_backtest import (
    OOF_FORECAST,
    _component_oof,
    _reconstruct_expected_points,
)
from .component_simulator import calibrate_empirical_components
from .market_odds import (
    HISTORICAL_MARKET_RATES,
    RAW_DIR,
    SOURCE_NOTES,
    _market_pair,
    _metrics,
    _odds,
    build_historical_market_goal_rates,
    infer_goal_rates,
)
from .market_transfer_replay import (
    _load_event_rows,
    moving_block_mean_interval,
    run_policy_season,
)
from .paths import MODEL_DATA, NORMALIZED, REPORTS, ensure_engine_layout
from .rules import load_rules
from .transfer_value import load_terminal_free_transfer_curve

SEASONS = ("2024-25", "2025-26")
ARCHIVE_SEASONS = (
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    *SEASONS,
)
VALIDATION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
HISTORICAL_RATES = NORMALIZED / "historical_betfair_exchange_goal_rates.parquet"
HISTORICAL_RECEIPT = NORMALIZED / "historical_betfair_exchange_goal_rates_receipt.json"
OUTPUT_DIR = MODEL_DATA / "betfair_exchange_policy_v1"
PLAYER_FORECAST = OUTPUT_DIR / "rolling-player-components.parquet"
RESULTS_JSON = OUTPUT_DIR / "results.json"
REPORT = REPORTS / "betfair-exchange-calibration.md"
SCORE_FIELD = "betfair_exchange_component_expected_points"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _metric_arrays(rows: list[dict[str, Any]], prefix: str) -> np.ndarray:
    return np.asarray(
        [
            value
            for row in rows
            for value in (row[f"{prefix}_home_goal_rate"], row[f"{prefix}_away_goal_rate"])
        ],
        dtype=np.float64,
    )


def build_historical_betfair_exchange_rates() -> dict[str, Any]:
    """Materialize non-closing BFE prices, with explicit average-market gaps."""
    ensure_engine_layout()
    if not HISTORICAL_MARKET_RATES.is_file():
        build_historical_market_goal_rates()
    base_rows = [
        row
        for row in pq.read_table(HISTORICAL_MARKET_RATES).to_pylist()
        if str(row["season"]) in ARCHIVE_SEASONS
    ]
    output_rows: list[dict[str, Any]] = []
    sources = []
    for season in ARCHIVE_SEASONS:
        path = RAW_DIR / f"{season}-E0.csv"
        payload = path.read_bytes()
        source_rows = list(
            csv.DictReader(payload.decode("utf-8-sig", errors="replace").splitlines())
        )
        by_pair = {_market_pair(row): row for row in source_rows}
        sources.append(
            {
                "season": season,
                "path": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        for base in (row for row in base_rows if str(row["season"]) == season):
            pair = _market_pair(
                {
                    "HomeTeam": str(base["home_name"]),
                    "AwayTeam": str(base["away_name"]),
                }
            )
            source = by_pair.get(pair)
            if source is None:
                raise ValueError(f"Missing Football-Data row for {season} {pair[0]} v {pair[1]}")
            one_x_two = _odds(source, ("BFEH", "BFED", "BFEA"))
            totals = _odds(source, ("BFE>2.5", "BFE<2.5"))
            available = one_x_two is not None and totals is not None
            if available:
                home_rate, away_rate, probabilities = infer_goal_rates(one_x_two, totals)
            else:
                home_rate = float(base["market_home_goal_rate"])
                away_rate = float(base["market_away_goal_rate"])
                probabilities = {
                    "home_probability": None,
                    "draw_probability": None,
                    "away_probability": None,
                    "over_2_5_probability": None,
                    "fit_rmse": None,
                }
            output_rows.append(
                {
                    **base,
                    "betfair_exchange_available": available,
                    "betfair_exchange_fallback": not available,
                    "betfair_home_odds": one_x_two[0] if one_x_two else None,
                    "betfair_draw_odds": one_x_two[1] if one_x_two else None,
                    "betfair_away_odds": one_x_two[2] if one_x_two else None,
                    "betfair_over_2_5_odds": totals[0] if totals else None,
                    "betfair_under_2_5_odds": totals[1] if totals else None,
                    "betfair_home_goal_rate": home_rate,
                    "betfair_away_goal_rate": away_rate,
                    **{f"betfair_{key}": value for key, value in probabilities.items()},
                }
            )
    pq.write_table(pa.Table.from_pylist(output_rows), HISTORICAL_RATES, compression="zstd")

    by_season = {}
    for season in SEASONS:
        rows = [
            row
            for row in output_rows
            if row["season"] == season and row["betfair_exchange_available"]
        ]
        actual = np.asarray(
            [value for row in rows for value in (row["home_goals"], row["away_goals"])],
            dtype=np.float64,
        )
        by_season[season] = {
            "fixtures": len(rows),
            "coverage": len(rows) / 380.0,
            "betfair_exchange": _metrics(actual, _metric_arrays(rows, "betfair")),
            "market_average_same_fixtures": _metrics(actual, _metric_arrays(rows, "market")),
            "incumbent_same_fixtures": _metrics(actual, _metric_arrays(rows, "incumbent")),
        }
    test = by_season[TEST_SEASON]
    fixture_checks = {
        "test_exchange_beats_internal_poisson_deviance": (
            test["betfair_exchange"]["poisson_deviance"]
            < test["incumbent_same_fixtures"]["poisson_deviance"]
        ),
        "test_exchange_beats_internal_goal_mae": (
            test["betfair_exchange"]["goal_mae"]
            < test["incumbent_same_fixtures"]["goal_mae"]
        ),
        "test_exchange_beats_internal_clean_sheet_brier": (
            test["betfair_exchange"]["clean_sheet_brier"]
            < test["incumbent_same_fixtures"]["clean_sheet_brier"]
        ),
        "test_exchange_coverage_at_least_90_percent": test["coverage"] >= 0.90,
    }
    receipt = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS" if all(fixture_checks.values()) else "FAIL",
        "fixture_gate": {"passed": all(fixture_checks.values()), "checks": fixture_checks},
        "by_season": by_season,
        "rows": len(output_rows),
        "fallback_rows": sum(bool(row["betfair_exchange_fallback"]) for row in output_rows),
        "information_policy": {
            "columns_used": ["BFEH", "BFED", "BFEA", "BFE>2.5", "BFE<2.5"],
            "closing_columns_used": False,
            "missing_exchange_fixture_policy": "market-average rate fallback, explicitly flagged",
            "historical_live_method_match": "near, not exact: archive supplies exchange odds; live uses delayed best-back/best-lay probability midpoint",
        },
        "source": {"notes_url": SOURCE_NOTES, "seasons": sources},
        "artifact": str(HISTORICAL_RATES),
        "artifact_sha256": sha256_file(HISTORICAL_RATES),
    }
    _write_json(HISTORICAL_RECEIPT, receipt)
    return receipt


def _historical_exchange_rates() -> tuple[
    dict[tuple[str, int, int], float], dict[tuple[str, int, int], float]
]:
    if not HISTORICAL_RATES.is_file():
        build_historical_betfair_exchange_rates()
    team: dict[tuple[str, int, int], float] = {}
    opponent: dict[tuple[str, int, int], float] = {}
    for row in pq.read_table(HISTORICAL_RATES).to_pylist():
        season = str(row["season"])
        event = int(row["event"])
        home = int(row["team_h"])
        away = int(row["team_a"])
        home_rate = float(row["betfair_home_goal_rate"])
        away_rate = float(row["betfair_away_goal_rate"])
        team[(season, event, home)] = home_rate
        team[(season, event, away)] = away_rate
        opponent[(season, event, home)] = away_rate
        opponent[(season, event, away)] = home_rate
    return team, opponent


def build_betfair_player_challenger() -> dict[str, Any]:
    """Reconstruct the existing OOF player components using exchange fixture rates."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rates, opponent_rates = _historical_exchange_rates()
    empirical = calibrate_empirical_components()
    component = _component_oof()
    output: list[dict[str, Any]] = []
    for season in SEASONS:
        rows = [
            row for row in pq.read_table(OOF_FORECAST).to_pylist() if row["season"] == season
        ]
        p_play = np.asarray([float(row["p_play"]) for row in rows])
        appearance = np.asarray([float(row["appearance_points"]) for row in rows])
        minutes = np.asarray([float(row["expected_minutes"]) for row in rows])
        probabilities = np.zeros((len(rows), 4), dtype=np.float64)
        probabilities[:, 1] = np.clip(2.0 * p_play - appearance, 0.0, 1.0)
        longer = np.clip(appearance - p_play, 0.0, 1.0)
        remaining = minutes - 28.0 * probabilities[:, 1]
        probabilities[:, 3] = np.clip((remaining - 75.0 * longer) / 15.0, 0.0, 1.0)
        probabilities[:, 2] = np.clip(longer - probabilities[:, 3], 0.0, 1.0)
        probabilities[:, 0] = np.clip(1.0 - probabilities[:, 1:].sum(axis=1), 0.0, 1.0)
        keys = [
            (season, int(row["event_number"]), int(row["element"])) for row in rows
        ]
        rebuilt = _reconstruct_expected_points(
            test_season=season,
            selected_rows=rows,
            selected_probabilities=probabilities,
            expected_minutes=minutes,
            p_play=p_play,
            appearance_points=appearance,
            predicted_goals=np.asarray([component[key]["goals"] for key in keys]),
            predicted_assists=np.asarray([component[key]["assists"] for key in keys]),
            predicted_bonus=np.asarray([component[key]["bonus"] for key in keys]),
            predicted_saves=np.asarray([component[key]["saves"] for key in keys]),
            empirical=empirical,
            team_goal_rate=rates,
            opponent_goal_rate=opponent_rates,
        )
        for index, row in enumerate(rows):
            output.append(
                {
                    "season": season,
                    "event_number": int(row["event_number"]),
                    "element": int(row["element"]),
                    SCORE_FIELD: float(rebuilt["expected"][index]),
                }
            )
    pq.write_table(pa.Table.from_pylist(output), PLAYER_FORECAST, compression="zstd")
    return {
        "rows": len(output),
        "artifact": str(PLAYER_FORECAST),
        "artifact_sha256": sha256_file(PLAYER_FORECAST),
    }


def _render(result: dict[str, Any]) -> str:
    fixture = result["fixture_calibration"]
    gate = result["policy_gate"]
    lines = [
        "# Betfair Exchange calibration and legal policy replay",
        "",
        f"Generated: {result['created_at']}",
        "",
        "## Verdict",
        "",
        (
            f"**{result['verdict']}** — validation selected a {result['selected_weight']:.0%} "
            f"exchange-component weight. The untouched {TEST_SEASON} continuous legal policy "
            f"changed net points by {gate['test_total_delta']:+.0f} "
            f"({gate['test_mean_delta']:+.3f}/GW)."
        ),
        "",
        "## Fixture calibration",
        "",
        "| Season | Coverage | Exchange deviance | Average deviance | Internal deviance | Exchange CS Brier |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for season in SEASONS:
        row = fixture["by_season"][season]
        lines.append(
            f"| {season} | {row['fixtures']}/380 ({row['coverage']:.1%}) | "
            f"{row['betfair_exchange']['poisson_deviance']:.4f} | "
            f"{row['market_average_same_fixtures']['poisson_deviance']:.4f} | "
            f"{row['incumbent_same_fixtures']['poisson_deviance']:.4f} | "
            f"{row['betfair_exchange']['clean_sheet_brier']:.4f} |"
        )
    lines.extend(
        [
            "",
            "The broad market average is a slightly stronger fixture forecaster than the single Betfair Exchange column on both seasons. Betfair still beats the internal fixture model on the untouched season, which is the relevant question when it is the only complete live market source.",
            "",
            "## Validation-selected policy weight",
            "",
            "| Weight | 2024/25 net points |",
            "|---:|---:|",
        ]
    )
    for row in result["weight_calibration"]:
        lines.append(f"| {row['weight']:.2f} | {row['net_points']} |")
    lines.extend(
        [
            "",
            "## Untouched sequential path",
            "",
            f"- Incumbent: **{result['paths'][f'{TEST_SEASON}:incumbent']['net_points']}** net points",
            f"- Betfair challenger: **{result['paths'][f'{TEST_SEASON}:betfair']['net_points']}** net points",
            f"- Broad market control at the same weight: **{result['paths'][f'{TEST_SEASON}:market_average_control']['net_points']}** net points",
            f"- Four-GW moving-block interval: **{gate['interval']['p025']:+.3f} to {gate['interval']['p975']:+.3f} points/GW**",
            "",
            "## Production rule",
            "",
            result["production_policy"]["explanation"],
            "",
            "Historical `BFE*` prices are non-closing exchange odds. The current anonymous feed uses delayed best-back/best-lay probability midpoints, so prospective receipts continue to monitor this near-but-not-identical method. Missing historical BFE fixtures use the market-average rate and are explicitly flagged; no closing columns are used.",
            "",
        ]
    )
    return "\n".join(lines)


def run_betfair_exchange_calibration() -> dict[str, Any]:
    print("Betfair calibration: building fixture-rate evidence", flush=True)
    fixture = build_historical_betfair_exchange_rates()
    print("Betfair calibration: reconstructing player components", flush=True)
    player = build_betfair_player_challenger()
    grouped, coverage = _load_event_rows()
    scores = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row[SCORE_FIELD]
        )
        for row in pq.read_table(PLAYER_FORECAST).to_pylist()
    }
    for (season, event), rows in grouped.items():
        for row in rows:
            key = (season, event, int(row["element"]))
            row[SCORE_FIELD] = scores.get(key, float(row["xp_expected_points"]))
    rules = load_rules()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=rules.max_free_transfers, rules=rules
    )
    weights = tuple(float(value) for value in np.linspace(0.0, 1.0, 11))
    validation = {}
    for index, weight in enumerate(weights, start=1):
        print(
            f"Betfair calibration: validation path {index}/{len(weights)} "
            f"(weight {weight:.2f})",
            flush=True,
        )
        validation[weight] = run_policy_season(
            season=VALIDATION_SEASON,
            policy="market_challenger",
            grouped=grouped,
            market_weight=weight,
            rules=rules,
            terminal_curve=terminal_curve,
            score_field=SCORE_FIELD,
        )
    selected = max(weights, key=lambda weight: (validation[weight]["net_points"], -weight))
    print(
        f"Betfair calibration: validation selected weight {selected:.2f}; "
        "opening untouched test season",
        flush=True,
    )
    incumbent = run_policy_season(
        season=TEST_SEASON,
        policy="incumbent_xp",
        grouped=grouped,
        market_weight=0.0,
        rules=rules,
        terminal_curve=terminal_curve,
    )
    challenger = run_policy_season(
        season=TEST_SEASON,
        policy="market_challenger",
        grouped=grouped,
        market_weight=selected,
        rules=rules,
        terminal_curve=terminal_curve,
        score_field=SCORE_FIELD,
    )
    average_control = run_policy_season(
        season=TEST_SEASON,
        policy="market_challenger",
        grouped=grouped,
        market_weight=selected,
        rules=rules,
        terminal_curve=terminal_curve,
    )
    print("Betfair calibration: completed legal-policy gate", flush=True)
    deltas = [
        candidate["net_points"] - base["net_points"]
        for candidate, base in zip(challenger["events"], incumbent["events"], strict=True)
    ]
    interval = moving_block_mean_interval(deltas, seed=20260810)
    validation_delta = validation[selected]["net_points"] - validation[0.0]["net_points"]
    test_delta = challenger["net_points"] - incumbent["net_points"]
    checks = {
        "fixture_gate_passed": fixture["fixture_gate"]["passed"],
        "nonzero_weight_selected_without_test_access": selected > 0.0,
        "positive_validation_total": validation_delta > 0,
        "positive_untouched_test_total": test_delta > 0,
        "test_block_lower_bound_above_minus_point_one": interval["p025"] > -0.10,
    }
    passed = all(checks.values())
    # Historical and live exchange observations are close but not identical. Even a passing
    # replay therefore starts with a deliberately bounded influence while prospective receipts
    # accumulate, rather than replacing the internal team model outright.
    production_weight = min(selected, 0.25) if passed else 0.0
    production_policy = {
        "decision_authority": passed,
        "goal_rate_weight": production_weight,
        "explanation": (
            f"Promote a bounded {production_weight:.0%} blend of timestamp-safe, fully covered "
            "Betfair goal rates into production; retain the internal model for the remaining "
            "weight and disable the blend whenever coverage or timestamp checks fail."
            if passed
            else "Do not promote Betfair into decision authority: retain it as a visible shadow scenario because the held-out legal-policy gate failed."
        ),
    }
    paths = {
        f"{VALIDATION_SEASON}:incumbent": validation[0.0],
        f"{VALIDATION_SEASON}:betfair": validation[selected],
        f"{TEST_SEASON}:incumbent": incumbent,
        f"{TEST_SEASON}:betfair": challenger,
        f"{TEST_SEASON}:market_average_control": average_control,
    }
    result = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PROMOTE_BOUNDED" if passed else "REJECT",
        "selected_weight": selected,
        "production_weight": production_weight,
        "fixture_calibration": fixture,
        "player_challenger": player,
        "weight_calibration": [
            {"weight": weight, "net_points": validation[weight]["net_points"]}
            for weight in weights
        ],
        "policy_gate": {
            "passed": passed,
            "checks": checks,
            "validation_total_delta": validation_delta,
            "test_total_delta": test_delta,
            "test_mean_delta": test_delta / 38.0,
            "interval": interval,
        },
        "production_policy": production_policy,
        "coverage": coverage,
        "transfer_value": terminal_receipt,
        "paths": paths,
        "artifacts": {
            "historical_rates": str(HISTORICAL_RATES),
            "historical_rates_sha256": sha256_file(HISTORICAL_RATES),
            "historical_receipt": str(HISTORICAL_RECEIPT),
            "historical_receipt_sha256": sha256_file(HISTORICAL_RECEIPT),
            "player_forecast": str(PLAYER_FORECAST),
            "player_forecast_sha256": sha256_file(PLAYER_FORECAST),
        },
    }
    _write_json(RESULTS_JSON, result)
    REPORT.write_text(_render(result), encoding="utf-8")
    return result
