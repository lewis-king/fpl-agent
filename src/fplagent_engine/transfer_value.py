from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .models import BACKTEST_FORECAST
from .optimizer import _solve
from .paths import MODEL_DATA, REPORTS
from .rules import SquadRules, load_rules
from .season_state import (
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    calculated_selling_price,
    default_chip_inventory,
)
from .weekly_actions import generate_weekly_actions

VERSION = "terminal_free_transfer_value_v1"
ARTIFACT_DIR = MODEL_DATA / "transfer_value_v1"
ARTIFACT = ARTIFACT_DIR / "terminal-free-transfer-value.json"
REPORT = REPORTS / "terminal-free-transfer-value.md"


def _rules_sha256(rules: SquadRules) -> str:
    payload = json.dumps(asdict(rules), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _curve_from_observation(observation: dict[str, Any], maximum: int) -> np.ndarray:
    raw = observation.get("cumulative_value_by_bank")
    if not isinstance(raw, dict):
        raise TypeError("Transfer-value observation is missing cumulative_value_by_bank")
    try:
        curve = np.asarray([float(raw[str(bank)]) for bank in range(maximum + 1)])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Transfer-value curve must contain banks 0 through {maximum}") from exc
    if not np.all(np.isfinite(curve)):
        raise ValueError("Transfer-value curve contains non-finite values")
    if abs(curve[0]) > 1e-9 or np.any(curve < -1e-9) or np.any(np.diff(curve) < -1e-9):
        raise ValueError("Transfer-value curve must start at zero and be non-decreasing")
    return np.maximum(curve, 0.0)


def fit_terminal_free_transfer_curve(
    observations: list[dict[str, Any]],
    *,
    maximum: int = 5,
    training_seasons: tuple[str, ...] = ("2023-24", "2024-25"),
    validation_season: str = "2025-26",
    minimum_training_states: int = 20,
    minimum_validation_states: int = 10,
    bootstrap_samples: int = 1_000,
    seed: int = 20260807,
) -> dict[str, Any]:
    if maximum < 1:
        raise ValueError("maximum transfer bank must be positive")
    if validation_season in training_seasons:
        raise ValueError("Validation season must remain outside the training seasons")
    if bootstrap_samples < 100:
        raise ValueError("At least 100 bootstrap samples are required")
    normalized = [
        (observation, _curve_from_observation(observation, maximum))
        for observation in observations
    ]
    train = np.asarray(
        [curve for row, curve in normalized if str(row.get("season")) in training_seasons]
    )
    validation = np.asarray(
        [curve for row, curve in normalized if str(row.get("season")) == validation_season]
    )
    if len(train) < minimum_training_states:
        raise ValueError(
            f"Only {len(train)} training states; need at least {minimum_training_states}"
        )
    if len(validation) < minimum_validation_states:
        raise ValueError(
            f"Only {len(validation)} validation states; need at least {minimum_validation_states}"
        )

    candidate = train.mean(axis=0)
    candidate[0] = 0.0
    candidate = np.maximum.accumulate(candidate)
    rng = np.random.default_rng(seed)
    bootstrap = np.asarray(
        [
            train[rng.integers(0, len(train), size=len(train))].mean(axis=0)
            for _ in range(bootstrap_samples)
        ]
    )
    confidence = {
        str(bank): {
            "mean": float(candidate[bank]),
            "p05": float(np.quantile(bootstrap[:, bank], 0.05)),
            "p95": float(np.quantile(bootstrap[:, bank], 0.95)),
        }
        for bank in range(maximum + 1)
    }

    candidate_errors = np.abs(validation[:, 1:] - candidate[None, 1:])
    zero_errors = validation[:, 1:]
    candidate_mae = float(candidate_errors.mean())
    zero_mae = float(zero_errors.mean())
    candidate_rmse = float(np.sqrt(np.mean(candidate_errors**2)))
    zero_rmse = float(np.sqrt(np.mean(zero_errors**2)))
    bank_metrics = {}
    for bank in range(1, maximum + 1):
        candidate_bank_error = np.abs(validation[:, bank] - candidate[bank])
        zero_bank_error = validation[:, bank]
        bank_metrics[str(bank)] = {
            "candidate_mae": float(candidate_bank_error.mean()),
            "zero_baseline_mae": float(zero_bank_error.mean()),
            "mae_improvement": float(zero_bank_error.mean() - candidate_bank_error.mean()),
            "validation_mean_opportunity": float(validation[:, bank].mean()),
        }
    train_max_mean = float(train[:, maximum].mean())
    validation_max_mean = float(validation[:, maximum].mean())
    distribution_gap = abs(train_max_mean - validation_max_mean)
    distribution_tolerance = max(1.5, 0.50 * max(validation_max_mean, 1e-9))
    checks = [
        {
            "name": "training coverage",
            "passed": len(train) >= minimum_training_states,
            "evidence": f"{len(train)} states across {', '.join(training_seasons)}",
        },
        {
            "name": "held-out coverage",
            "passed": len(validation) >= minimum_validation_states,
            "evidence": f"{len(validation)} states in {validation_season}",
        },
        {
            "name": "held-out MAE beats zero",
            "passed": candidate_mae < zero_mae,
            "evidence": f"candidate={candidate_mae:.3f}; zero={zero_mae:.3f}",
        },
        {
            "name": "held-out RMSE beats zero",
            "passed": candidate_rmse < zero_rmse,
            "evidence": f"candidate={candidate_rmse:.3f}; zero={zero_rmse:.3f}",
        },
        {
            "name": "no bank regresses against zero",
            "passed": all(
                row["candidate_mae"] <= row["zero_baseline_mae"]
                for row in bank_metrics.values()
            ),
            "evidence": "banks 1-5 checked separately",
        },
        {
            "name": "maximum-bank distribution remains stable",
            "passed": distribution_gap <= distribution_tolerance,
            "evidence": (
                f"train={train_max_mean:.3f}; validation={validation_max_mean:.3f}; "
                f"gap={distribution_gap:.3f}; tolerance={distribution_tolerance:.3f}"
            ),
        },
    ]
    promoted = all(bool(check["passed"]) for check in checks)
    candidate_curve = {str(bank): float(candidate[bank]) for bank in range(maximum + 1)}
    selected_curve = (
        candidate_curve
        if promoted
        else {str(bank): 0.0 for bank in range(maximum + 1)}
    )
    return {
        "version": VERSION,
        "method": (
            "Mean point-in-time option value of being able to make up to N free transfers, "
            "measured on squads selected from the preceding deadline only"
        ),
        "maximum_free_transfers": maximum,
        "training_seasons": list(training_seasons),
        "validation_season": validation_season,
        "training_states": len(train),
        "validation_states": len(validation),
        "candidate_curve": candidate_curve,
        "selected_curve": selected_curve,
        "marginal_candidate_value": {
            str(bank): float(candidate[bank] - candidate[bank - 1])
            for bank in range(1, maximum + 1)
        },
        "bootstrap_confidence": confidence,
        "held_out_metrics": {
            "candidate_mae": candidate_mae,
            "zero_baseline_mae": zero_mae,
            "candidate_rmse": candidate_rmse,
            "zero_baseline_rmse": zero_rmse,
            "mae_improvement_fraction": (
                (zero_mae - candidate_mae) / zero_mae if zero_mae > 0.0 else 0.0
            ),
            "rmse_improvement_fraction": (
                (zero_rmse - candidate_rmse) / zero_rmse if zero_rmse > 0.0 else 0.0
            ),
            "by_bank": bank_metrics,
        },
        "promotion_gate": {"promoted": promoted, "checks": checks},
    }


def _historical_state(
    previous_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    season: str,
    event: int,
    rules: SquadRules,
) -> ManagerState:
    previous_solution = _solve(previous_rows, [event - 1], rules=rules)
    selected = tuple(int(element) for element in previous_solution["selected"])
    previous_by_id = {int(row["element"]): row for row in previous_rows}
    current_by_id = {int(row["element"]): row for row in current_rows}
    missing = set(selected).difference(current_by_id)
    if missing:
        raise ValueError(f"Prior squad players missing at the next deadline: {sorted(missing)}")
    holdings = []
    for element in selected:
        previous = previous_by_id[element]
        current = current_by_id[element]
        purchase_price = round(float(previous["market_price"]))
        current_price = round(float(current["market_price"]))
        holdings.append(
            PlayerHolding(
                player_id=element,
                position=str(current["position"]),
                team_id=int(current["team_id"]),
                purchase_price=purchase_price,
                current_price=current_price,
                selling_price=calculated_selling_price(purchase_price, current_price),
            )
        )
    previous_lineup = previous_solution["lineups"][event - 1]
    purchase_spend = sum(round(float(previous_by_id[element]["market_price"])) for element in selected)
    return ManagerState(
        season=season,
        event=event,
        event_status=EventStatus.DEADLINE_OPEN,
        squad=tuple(holdings),
        bank=rules.budget - purchase_spend,
        free_transfers=rules.max_free_transfers,
        chips=default_chip_inventory(),
        lineup=Lineup(
            starters=tuple(int(element) for element in previous_lineup["starters"]),
            bench_order=tuple(int(element) for element in previous_lineup["bench_order"]),
            captain=int(previous_lineup["captain"]),
            vice_captain=int(previous_lineup["vice_captain"]),
        ),
    )


def build_historical_transfer_opportunities(
    *,
    forecast_path: Path = BACKTEST_FORECAST,
    rules: SquadRules | None = None,
    seasons: tuple[str, ...] = ("2023-24", "2024-25", "2025-26"),
    event_stride: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if event_stride < 1:
        raise ValueError("event_stride must be positive")
    rules = rules or load_rules()
    rows = pq.read_table(forecast_path).to_pylist()
    by_season_event: dict[tuple[str, int], list[dict[str, Any]]] = {}
    excluded_incomplete_rows = 0
    for row in rows:
        season = str(row["season"])
        if season not in seasons:
            continue
        required = (
            row.get("element"),
            row.get("event_number"),
            row.get("position"),
            row.get("team_id"),
            row.get("market_price"),
            row.get("expected_points"),
            row.get("p_play"),
        )
        if any(value is None for value in required):
            excluded_incomplete_rows += 1
            continue
        event = int(row["event_number"])
        enriched = dict(row)
        enriched["robust_points"] = float(row["expected_points"])
        enriched["can_select"] = True
        enriched["removed"] = False
        by_season_event.setdefault((season, event), []).append(enriched)

    observations: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    attempted = 0
    for season in seasons:
        available_events = sorted(
            event for candidate_season, event in by_season_event if candidate_season == season
        )
        selected_events = available_events[1::event_stride]
        for event in selected_events:
            attempted += 1
            previous_rows = by_season_event.get((season, event - 1))
            current_rows = by_season_event.get((season, event))
            if not previous_rows or not current_rows:
                skipped["missing adjacent forecast"] += 1
                continue
            try:
                state = _historical_state(
                    previous_rows,
                    current_rows,
                    season=season,
                    event=event,
                    rules=rules,
                )
                actions = generate_weekly_actions(
                    state,
                    current_rows,
                    rules,
                    events=(event,),
                    score_field="expected_points",
                    alternatives_per_transfer_count=1,
                    max_total_transfers=rules.max_free_transfers,
                    max_paid_transfers=0,
                )
            except (RuntimeError, ValueError) as exc:
                skipped[str(exc)] += 1
                continue
            by_count = {
                len(action.action.transfers): float(action.gross_horizon_utility)
                for action in actions
            }
            if set(by_count) != set(range(rules.max_free_transfers + 1)):
                skipped["not every exact transfer count was feasible"] += 1
                continue
            roll = by_count[0]
            cumulative = {}
            best = roll
            for bank in range(rules.max_free_transfers + 1):
                best = max(best, by_count[bank])
                cumulative[str(bank)] = float(best - roll)
            observations.append(
                {
                    "season": season,
                    "event": event,
                    "source_squad_event": event - 1,
                    "cumulative_value_by_bank": cumulative,
                    "exact_route_utility": {
                        str(count): utility for count, utility in sorted(by_count.items())
                    },
                }
            )
    return observations, {
        "attempted_states": attempted,
        "completed_states": len(observations),
        "skipped_states": attempted - len(observations),
        "skipped_reasons": dict(skipped),
        "event_stride": event_stride,
        "seasons": list(seasons),
        "excluded_incomplete_player_rows": excluded_incomplete_rows,
    }


def _render_report(result: dict[str, Any]) -> str:
    fit = result["fit"]
    gate = fit["promotion_gate"]
    lines = [
        "# Terminal free-transfer value calibration",
        "",
        f"Generated {result['created_at']} from `{result['source_artifacts']['forecast']}`.",
        "",
        "## Verdict",
        "",
        (
            "**Promoted for weekly terminal valuation.**"
            if gate["promoted"]
            else "**Not promoted; weekly decisions retain a zero terminal value.**"
        ),
        "",
        (
            "The curve estimates the option value of arriving at a future deadline with 0–5 free "
            "transfers. Each historical squad is selected from only the preceding deadline "
            "forecast; the opportunity is measured from the next point-in-time forecast. The "
            "2025/26 season is held out and realised future points are never used."
        ),
        "",
        "| Bank | Candidate value | Marginal value | 90% bootstrap interval |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for bank in range(fit["maximum_free_transfers"] + 1):
        confidence = fit["bootstrap_confidence"][str(bank)]
        marginal = 0.0 if bank == 0 else fit["marginal_candidate_value"][str(bank)]
        lines.append(
            f"| {bank} | {fit['candidate_curve'][str(bank)]:.3f} | {marginal:.3f} | "
            f"{confidence['p05']:.3f}–{confidence['p95']:.3f} |"
        )
    metrics = fit["held_out_metrics"]
    lines.extend(
        [
            "",
            "## Held-out calibration",
            "",
            f"- Candidate MAE: {metrics['candidate_mae']:.3f}",
            f"- Zero-value baseline MAE: {metrics['zero_baseline_mae']:.3f}",
            f"- Candidate RMSE: {metrics['candidate_rmse']:.3f}",
            f"- Zero-value baseline RMSE: {metrics['zero_baseline_rmse']:.3f}",
            "",
            "## Promotion checks",
            "",
        ]
    )
    for check in gate["checks"]:
        lines.append(
            f"- {'PASS' if check['passed'] else 'FAIL'} — {check['name']}: {check['evidence']}"
        )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            (
                "- This calibrates future flexibility under the forecast model; it is not a claim "
                "that observed managers used their transfers optimally."
            ),
            "- The runtime discounts the curve to the end of its fixed forecast horizon.",
            (
                "- Actual weekly decisions still compare roll and every generated route under "
                "shared residual and component simulations."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_transfer_value_calibration(
    *,
    forecast_path: Path = BACKTEST_FORECAST,
    output_path: Path = ARTIFACT,
    report_path: Path = REPORT,
    event_stride: int = 3,
) -> dict[str, Any]:
    rules = load_rules()
    observations, diagnostics = build_historical_transfer_opportunities(
        forecast_path=forecast_path,
        rules=rules,
        event_stride=event_stride,
    )
    fit = fit_terminal_free_transfer_curve(
        observations,
        maximum=rules.max_free_transfers,
    )
    result = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "fit": fit,
        "diagnostics": diagnostics,
        "observations": observations,
        "source_artifacts": {
            "forecast": str(forecast_path),
            "forecast_sha256": sha256_file(forecast_path),
            "runtime_rules_sha256": _rules_sha256(rules),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(result), encoding="utf-8")
    return result


def load_terminal_free_transfer_curve(
    *,
    path: Path = ARTIFACT,
    maximum: int = 5,
    rules: SquadRules | None = None,
) -> tuple[dict[int, float], dict[str, Any]]:
    zero = {bank: 0.0 for bank in range(maximum + 1)}
    if not path.is_file():
        return zero, {"status": "missing", "promoted": False, "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fit = payload["fit"]
        promoted = bool(fit["promotion_gate"]["promoted"])
        if int(fit["maximum_free_transfers"]) != maximum:
            raise ValueError("transfer-value artifact uses a different free-transfer cap")
        if rules is not None:
            recorded_rules_hash = payload["source_artifacts"]["runtime_rules_sha256"]
            if recorded_rules_hash != _rules_sha256(rules):
                raise ValueError("transfer-value artifact was calibrated under different rules")
        selected = {
            bank: float(fit["selected_curve"][str(bank)]) for bank in range(maximum + 1)
        }
        _curve_from_observation(
            {"cumulative_value_by_bank": {str(k): v for k, v in selected.items()}},
            maximum,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Transfer-value artifact is invalid: {path}") from exc
    return (
        selected if promoted else zero,
        {
            "status": "promoted" if promoted else "not_promoted",
            "promoted": promoted,
            "path": str(path),
            "sha256": sha256_file(path),
            "version": payload.get("version"),
            "created_at": payload.get("created_at"),
            "curve": selected if promoted else zero,
        },
    )
