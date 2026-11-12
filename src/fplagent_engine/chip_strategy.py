from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file

from .features import TRAINING_FEATURES
from .models import BACKTEST_FORECAST
from .paths import DATA, MODEL_DATA, REPORTS, ROOT
from .rules import SquadRules, load_rules
from .season_state import ChipStatus, ChipType, ManagerState
from .squad_chip_replay import _load_schedule
from .team_chip_replay import build_team_chip_opportunity_path
from .transfer_value import load_terminal_free_transfer_curve
from .weekly_actions import EvaluatedAction

VERSION = 2
SEASONS = ("2023-24", "2024-25", "2025-26")
HISTORICAL_HALF_LIFE_SEASONS = 1.25
OUTPUT_ROOT = MODEL_DATA / "chip_strategy_v2"
CALIBRATION = OUTPUT_ROOT / "retained-value.json"
REPORT = REPORTS / "chip-strategy-v2.md"
ELITE_CHIP_HISTORY = DATA / "processed" / "supporting" / "soong_chips.parquet"

TEAM_CHIPS = (ChipType.BENCH_BOOST.value, ChipType.TRIPLE_CAPTAIN.value)
SQUAD_CHIPS = (ChipType.WILDCARD.value, ChipType.FREE_HIT.value)
ALL_CHIPS = (*TEAM_CHIPS, *SQUAD_CHIPS)


def _season_weight(season: str, *, newest: str = SEASONS[-1]) -> float:
    age = int(newest[:4]) - int(season[:4])
    return 0.5 ** (age / HISTORICAL_HALF_LIFE_SEASONS)


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _normalised_season_weights(seasons: Sequence[str]) -> dict[str, float]:
    raw = {season: _season_weight(season, newest=max(seasons)) for season in seasons}
    total = sum(raw.values())
    return {season: value / total for season, value in raw.items()}


def _weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    if not values or len(values) != len(weights):
        raise ValueError("weighted quantile requires aligned non-empty values and weights")
    if not 0.0 <= q <= 1.0:
        raise ValueError("weighted quantile q must be in [0, 1]")
    ordered = sorted(zip(values, weights, strict=True), key=lambda row: row[0])
    total = sum(max(float(weight), 0.0) for _, weight in ordered)
    if total <= 0.0:
        raise ValueError("weighted quantile weights must contain positive mass")
    threshold = q * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += max(float(weight), 0.0)
        if cumulative >= threshold:
            return float(value)
    return float(ordered[-1][0])


def _remaining_bin(events_remaining: int) -> str:
    if events_remaining <= 3:
        return "expiry_0_3"
    if events_remaining <= 6:
        return "late_4_6"
    if events_remaining <= 12:
        return "middle_7_12"
    return "early_13_18"


def _half_bounds(event: int) -> tuple[int, int, int]:
    if event <= 19:
        return 1, 1, 19
    return 2, 20, 38


def _load_historical_rows(
    seasons: Sequence[str] = SEASONS,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    season_set = set(seasons)
    minutes = {
        (str(row["season"]), int(row["event_number"]), int(row["element"])): float(
            row["target_minutes"]
        )
        for row in pq.read_table(TRAINING_FEATURES).to_pylist()
        if str(row["season"]) in season_set
    }
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in pq.read_table(BACKTEST_FORECAST).to_pylist():
        season = str(raw["season"])
        if season not in season_set:
            continue
        event = int(raw["event_number"])
        element = int(raw["element"])
        key = (season, event, element)
        if raw.get("market_price") is None or key not in minutes:
            continue
        expected = float(raw["expected_points"])
        grouped.setdefault((season, event), []).append(
            {
                **raw,
                "market_price": round(float(raw["market_price"])),
                "target_points": float(raw["target_points"]),
                "target_minutes": minutes[key],
                "expected_points": expected,
                "robust_points": expected,
                "p_play": float(raw.get("p_play", 1.0)),
                "can_select": True,
                "removed": False,
            }
        )
    for season in seasons:
        available = sorted(event for candidate, event in grouped if candidate == season)
        if available != list(range(1, 39)):
            raise ValueError(
                f"chip calibration requires complete events 1-38 for {season}: {available}"
            )
    return grouped


def _historical_rows_semantic_sha256(
    grouped: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
) -> str:
    """Hash only calibration-relevant historical values, not mutable Parquet bytes.

    ``TRAINING_FEATURES`` also contains the rolling live-season feature matrix and is
    rewritten on a normal deadline refresh. Binding a long-lived calibration to that
    whole file makes an unrelated live row disable chip advice. The compact rows below
    are the complete inputs actually consumed by the historical chip replay.
    """

    digest = hashlib.sha256()
    fields = (
        "element",
        "player_name",
        "position",
        "team_id",
        "market_price",
        "target_points",
        "target_minutes",
        "expected_points",
        "p_play",
        "can_select",
        "removed",
    )
    for (season, event), rows in sorted(grouped.items()):
        for row in sorted(rows, key=lambda candidate: int(candidate["element"])):
            payload = [season, int(event), *(row.get(field) for field in fields)]
            digest.update(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _retained_rows(paths: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        season = str(path["season"])
        opportunities = path["opportunities"]
        for opportunity in opportunities:
            event = int(opportunity["event"])
            half, _, half_end = _half_bounds(event)
            for chip in TEAM_CHIPS:
                later = [
                    float(row["forecast_uplifts"][chip])
                    for row in opportunities
                    if event < int(row["event"]) <= half_end
                ]
                rows.append(
                    {
                        "season": season,
                        "event": event,
                        "half": half,
                        "chip": chip,
                        "events_remaining": half_end - event,
                        "remaining_bin": _remaining_bin(half_end - event),
                        "current_forecast_uplift": float(
                            opportunity["forecast_uplifts"][chip]
                        ),
                        "current_actual_uplift": float(opportunity["actual_uplifts"][chip]),
                        "best_later_forecast_uplift": max(later, default=0.0),
                    }
                )
    return rows


def _retained_table(
    rows: Sequence[dict[str, Any]], seasons: Sequence[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    season_weights = _normalised_season_weights(seasons)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for chip in TEAM_CHIPS:
        result[chip] = {}
        chip_rows = [row for row in rows if row["chip"] == chip]
        exact: dict[str, dict[str, Any]] = {}
        for events_remaining in range(19):
            sample = [
                row
                for row in chip_rows
                if int(row["events_remaining"]) == events_remaining
            ]
            values = [float(row["best_later_forecast_uplift"]) for row in sample]
            weights = [season_weights[str(row["season"])] for row in sample]
            exact[str(events_remaining)] = {
                "samples": len(sample),
                "p25": _weighted_quantile(values, weights, 0.25),
                "p50": _weighted_quantile(values, weights, 0.50),
                "p75": _weighted_quantile(values, weights, 0.75),
                "p90": _weighted_quantile(values, weights, 0.90),
            }
        result[chip]["by_events_remaining"] = exact
        for remaining_bin in (
            "early_13_18",
            "middle_7_12",
            "late_4_6",
            "expiry_0_3",
        ):
            sample = [row for row in chip_rows if row["remaining_bin"] == remaining_bin]
            values = [float(row["best_later_forecast_uplift"]) for row in sample]
            weights = [season_weights[str(row["season"])] for row in sample]
            result[chip][remaining_bin] = {
                "samples": len(sample),
                "seasons": sorted({str(row["season"]) for row in sample}),
                "p25": _weighted_quantile(values, weights, 0.25),
                "p50": _weighted_quantile(values, weights, 0.50),
                "p75": _weighted_quantile(values, weights, 0.75),
                "p90": _weighted_quantile(values, weights, 0.90),
            }
    return result


def _lookup_retained(
    table: Mapping[str, Any], chip: str, event: int, *, quantile: str = "p50"
) -> float:
    _, _, half_end = _half_bounds(event)
    events_remaining = half_end - event
    exact = table[chip].get("by_events_remaining") or {}
    if str(events_remaining) in exact:
        return float(exact[str(events_remaining)][quantile])
    remaining_bin = _remaining_bin(events_remaining)
    return float(table[chip][remaining_bin][quantile])


def _score_timing_policy(
    path: Mapping[str, Any],
    table: Mapping[str, Any],
    *,
    safety_quantile: str = "p50",
) -> dict[str, Any]:
    used: set[tuple[int, str]] = set()
    selected: dict[int, str] = {}
    events = list(path["opportunities"])
    for opportunity in events:
        event = int(opportunity["event"])
        half, _, half_end = _half_bounds(event)
        remaining_chips = [
            chip for chip in TEAM_CHIPS if (half, chip) not in used
        ]
        if not remaining_chips:
            continue
        events_left_including_current = half_end - event + 1
        candidates = []
        for chip in remaining_chips:
            current = float(opportunity["forecast_uplifts"][chip])
            retained = _lookup_retained(table, chip, event, quantile=safety_quantile)
            forced = events_left_including_current <= len(remaining_chips)
            if current >= retained or forced:
                candidates.append((current - retained, current, chip))
        if not candidates:
            continue
        _, _, chip = max(candidates)
        selected[event] = chip
        used.add((half, chip))
    chip_events = []
    for opportunity in events:
        event = int(opportunity["event"])
        chip = selected.get(event)
        if chip is None:
            continue
        chip_events.append(
            {
                "event": event,
                "half": _half_bounds(event)[0],
                "chip": chip,
                "forecast_uplift": float(opportunity["forecast_uplifts"][chip]),
                "actual_uplift": float(opportunity["actual_uplifts"][chip]),
            }
        )
    return {
        "season": path["season"],
        "chip_events": chip_events,
        "forecast_uplift": sum(row["forecast_uplift"] for row in chip_events),
        "actual_uplift": sum(row["actual_uplift"] for row in chip_events),
    }


def _score_forecast_oracle(path: Mapping[str, Any]) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for _, half_start, half_end in ((1, 1, 19), (2, 20, 38)):
        opportunities = [
            row
            for row in path["opportunities"]
            if half_start <= int(row["event"]) <= half_end
        ]
        choices: list[tuple[float, int, int]] = []
        for bb in opportunities:
            for tc in opportunities:
                if int(bb["event"]) == int(tc["event"]):
                    continue
                choices.append(
                    (
                        float(bb["forecast_uplifts"][ChipType.BENCH_BOOST.value])
                        + float(tc["forecast_uplifts"][ChipType.TRIPLE_CAPTAIN.value]),
                        int(bb["event"]),
                        int(tc["event"]),
                    )
                )
        _, bb_event, tc_event = max(choices)
        by_event = {int(row["event"]): row for row in opportunities}
        for chip, event in (
            (ChipType.BENCH_BOOST.value, bb_event),
            (ChipType.TRIPLE_CAPTAIN.value, tc_event),
        ):
            selected.append(
                {
                    "event": event,
                    "chip": chip,
                    "forecast_uplift": float(by_event[event]["forecast_uplifts"][chip]),
                    "actual_uplift": float(by_event[event]["actual_uplifts"][chip]),
                }
            )
    return {
        "season": path["season"],
        "chip_events": sorted(selected, key=lambda row: row["event"]),
        "forecast_uplift": sum(row["forecast_uplift"] for row in selected),
        "actual_uplift": sum(row["actual_uplift"] for row in selected),
    }


def _historical_gate(paths: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_season = {str(path["season"]): path for path in paths}
    if len(by_season) != len(paths) or set(by_season) != set(SEASONS):
        raise ValueError("Chip validation requires exactly one path for each recent season")
    if any(len(path["opportunities"]) != 38 or
           {int(row["event"]) for row in path["opportunities"]} != set(range(1, 39))
           for path in paths):
        raise ValueError("Chip validation requires all 38 distinct events in each season")
    folds = []
    for test_season in SEASONS:
        train = sorted(
            [path for path in paths if str(path["season"]) < test_season],
            key=lambda path: str(path["season"]),
        )
        if not train:
            continue  # First season initializes the policy; it is not a holdout.
        table = _retained_table(_retained_rows(train), [str(path["season"]) for path in train])
        policy = _score_timing_policy(by_season[test_season], table)
        oracle = _score_forecast_oracle(by_season[test_season])
        folds.append(
            {
                "test_season": test_season,
                "train_seasons": [str(path["season"]) for path in train],
                "policy": policy,
                "forecast_oracle": oracle,
                "actual_regret_to_forecast_oracle": (
                    policy["actual_uplift"] - oracle["actual_uplift"]
                ),
                "forecast_opportunity_efficiency": (
                    policy["forecast_uplift"] / oracle["forecast_uplift"]
                    if oracle["forecast_uplift"] > 0.0
                    else 0.0
                ),
            }
        )
    untouched = next(row for row in folds if row["test_season"] == SEASONS[-1])
    all_policy_positive = all(row["policy"]["actual_uplift"] > 0.0 for row in folds)
    all_inventory_complete = all(len(row["policy"]["chip_events"]) == 4 for row in folds)
    untouched_oracle = float(untouched["forecast_oracle"]["actual_uplift"])
    untouched_ratio = (
        float(untouched["policy"]["actual_uplift"]) / untouched_oracle
        if untouched_oracle > 0.0
        else 0.0
    )
    checks = {
        "three_recent_complete_seasons": len(paths) == 3,
        "strictly_forward_two_holdouts": len(folds) == 2 and all(
            season < fold["test_season"]
            for fold in folds for season in fold["train_seasons"]
        ),
        "rolling_origin_policy_positive_each_season": all_policy_positive,
        "one_of_each_team_chip_used_per_half": all_inventory_complete,
        "every_holdout_captures_at_least_85_percent_of_forecast_oracle": all(
            float(row["forecast_opportunity_efficiency"]) >= 0.85 for row in folds
        ),
        "untouched_2025_26_at_least_75_percent_of_forecast_oracle_actual": (
            untouched_ratio >= 0.75
        ),
    }
    return {
        "validation_scheme": "expanding_window_v1",
        "training_only_seasons": [SEASONS[0]],
        "passed": all(checks.values()),
        "checks": checks,
        "folds": folds,
        "untouched_test_season": SEASONS[-1],
        "untouched_actual_efficiency_vs_forecast_oracle": untouched_ratio,
    }


def _render_report(result: Mapping[str, Any]) -> str:
    weights = result["recency"]["season_weights"]
    gate = result["historical_gate"]
    return "\n".join(
        [
            "# Joint chip strategy v2",
            "",
            f"Generated: {result['created_at']}",
            "",
            f"Historical BB/TC timing gate: **{'PASS' if gate['passed'] else 'REJECT'}**.",
            "",
            "## What changed",
            "",
            "- Chip choice is one event-allocation problem, so two chips can never occupy the same GW.",
            "- A current uplift is compared with the learned value of the best later opportunity before expiry.",
            "- Retained value decays by weeks remaining and reaches zero at expiry instead of requiring a full live forecast to GW19/GW38.",
            "- Recent seasons dominate calibration; older relevant seasons stabilize the tails.",
            "- WC/FH remain outcome-conservative because event-level causal counterfactuals are not yet identified reliably.",
            "",
            "## Recency weights",
            "",
            *(f"- {season}: {float(weight):.1%}" for season, weight in weights.items()),
            "",
            "## Rolling-origin evidence",
            "",
            "Expanding-window validation: each test season uses only earlier seasons. The first season is training-only.",
            "",
            *(
                f"- {fold['test_season']}: policy {fold['policy']['actual_uplift']:.1f} actual chip points; "
                f"forecast-oracle {fold['forecast_oracle']['actual_uplift']:.1f}; "
                f"regret {fold['actual_regret_to_forecast_oracle']:+.1f}."
                for fold in gate["folds"]
            ),
            "",
            (
                "The oracle is an offline comparator selected using deadline forecasts, not "
                "realised points. It is never available to the live policy."
            ),
            "",
        ]
    )


def _elite_manager_sanity_check(path: Path = ELITE_CHIP_HISTORY) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "unavailable", "decision_authority": False}
    rows = pq.read_table(path).to_pylist()
    aliases = {"bboost": "bench_boost", "3xc": "triple_captain", "freehit": "free_hit"}
    by_chip: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        chip = aliases.get(str(row["chip"]), str(row["chip"]))
        by_chip[chip].append(int(row["event"]))
    return {
        "status": "descriptive_only",
        "decision_authority": False,
        "seasons": sorted({str(row["season"]) for row in rows}),
        "managers": len({int(row["manager_id"]) for row in rows}),
        "uses": len(rows),
        "events_by_chip": {chip: sorted(events) for chip, events in sorted(by_chip.items())},
        "interpretation": (
            "Observed strong-manager timing is a behavioural sanity check, not a causal label or "
            "a substitute for point-in-time policy replay."
        ),
        "artifact": _portable_path(path),
        "artifact_sha256": sha256_file(path),
    }


def build_chip_strategy_calibration(
    *,
    rules: SquadRules | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    active_rules = rules or load_rules()
    grouped = _load_historical_rows()
    schedule = _load_schedule()
    terminal_curve, terminal_receipt = load_terminal_free_transfer_curve(
        maximum=active_rules.max_free_transfers,
        rules=active_rules,
    )
    paths = [
        build_team_chip_opportunity_path(
            season=season,
            grouped=grouped,
            schedule_rows=schedule,
            rules=active_rules,
            terminal_curve=terminal_curve,
        )
        for season in SEASONS
    ]
    retained_rows = _retained_rows(paths)
    retained_table = _retained_table(retained_rows, SEASONS)
    historical_gate = _historical_gate(paths)
    season_weights = _normalised_season_weights(SEASONS)
    elite_sanity = _elite_manager_sanity_check()
    result: dict[str, Any] = {
        "version": VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "status": "promoted_team_chips" if historical_gate["passed"] else "shadow",
        "historical_gate": historical_gate,
        "opportunity_paths": paths,
        "authority_by_chip": {
            ChipType.BENCH_BOOST.value: historical_gate["passed"],
            ChipType.TRIPLE_CAPTAIN.value: historical_gate["passed"],
            ChipType.WILDCARD.value: False,
            ChipType.FREE_HIT.value: False,
        },
        "retained_value": retained_table,
        "squad_chip_priors": {
            ChipType.WILDCARD.value: {
                "p50": 6.0,
                "p75": 8.0,
                "source": "exact historical threshold replay; event-level outcome gate rejected",
            },
            ChipType.FREE_HIT.value: {
                "p50": 6.0,
                "p75": 8.0,
                "source": "exact historical threshold replay; event-level outcome gate rejected",
            },
        },
        "recency": {
            "seasons": list(SEASONS),
            "half_life_seasons": HISTORICAL_HALF_LIFE_SEASONS,
            "season_weights": season_weights,
            "pandemic_seasons_excluded": True,
            "reason": (
                "The current rule regime and football environment are closer to recent seasons; "
                "older seasons stabilize only through the chosen half-life."
            ),
        },
        "elite_manager_timing_sanity": elite_sanity,
        "mechanics": {
            "chips_per_half": 4,
            "one_chip_per_event": True,
            "first_half_expiry_event": 19,
            "second_half_starts_event": 20,
            "free_hit_consecutive_block": True,
            "current_two_inventory_rule_applied_counterfactually": True,
        },
        "artifacts": {
            "backtest_forecast": _portable_path(BACKTEST_FORECAST),
            "training_features": _portable_path(TRAINING_FEATURES),
            "historical_rows_semantic_sha256": _historical_rows_semantic_sha256(grouped),
            **(
                {
                    "elite_chip_history": elite_sanity["artifact"],
                    "elite_chip_history_sha256": elite_sanity["artifact_sha256"],
                }
                if elite_sanity.get("artifact")
                else {}
            ),
        },
        "terminal_free_transfer_value": terminal_receipt,
        "limitations": [
            "2025/26 shares the two-of-each half-season structure; it is applied counterfactually to 2023/24 and 2024/25.",
            "Wildcard and Free Hit have exact live branches but no promoted event-level causal retained-value model.",
            "Prospective 2026/27 receipts remain necessary to establish superiority under current rules.",
        ],
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = CALIBRATION.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(CALIBRATION)
    REPORT.write_text(_render_report(result), encoding="utf-8")
    return result


def load_chip_strategy_calibration(path: Path = CALIBRATION) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if int(result.get("version", 0)) != VERSION:
        raise ValueError("chip strategy calibration has an unsupported contract")
    gate = result.get("historical_gate") or {}
    folds = gate.get("folds") or []
    forward_verified = (
        gate.get("validation_scheme") == "expanding_window_v1"
        and len(folds) == len(SEASONS) - 1
        and {fold.get("test_season") for fold in folds} == set(SEASONS[1:])
        and all(
            fold.get("train_seasons") == [s for s in SEASONS if s < fold["test_season"]]
            for fold in folds
        )
        and gate.get("passed") is True
    )
    if not forward_verified:
        # Preserve portable old receipts for inspection, but never turn an
        # incorrectly labelled historical test into live chip authority.
        result["authority_by_chip"] = {chip.value: False for chip in ChipType}
        result["status"] = "shadow"
        result["validation_warning"] = "Forward-only historical validation is absent or failed"
    verified_sources = []
    unavailable_sources = []
    artifacts = result.get("artifacts", {})
    historical_source_names = ("backtest_forecast", "training_features")
    expected_historical = artifacts.get("historical_rows_semantic_sha256")
    historical_paths = []
    for name in historical_source_names:
        artifact = artifacts.get(name)
        if artifact is None:
            continue
        artifact_path = Path(str(artifact))
        if not artifact_path.is_absolute():
            artifact_path = ROOT / artifact_path
        historical_paths.append((name, artifact_path))
    if expected_historical and historical_paths:
        missing = [name for name, artifact_path in historical_paths if not artifact_path.is_file()]
        if missing:
            unavailable_sources.extend(missing)
        else:
            observed_historical = _historical_rows_semantic_sha256(_load_historical_rows())
            if observed_historical != expected_historical:
                raise ValueError("chip strategy calibration input changed: historical_rows")
            verified_sources.extend(name for name, _ in historical_paths)
    for name, artifact in artifacts.items():
        if name.endswith("_sha256"):
            continue
        if name in historical_source_names and expected_historical:
            continue
        expected = result["artifacts"].get(f"{name}_sha256")
        artifact_path = Path(str(artifact))
        if not artifact_path.is_absolute():
            artifact_path = ROOT / artifact_path
        if not artifact_path.is_file():
            unavailable_sources.append(name)
            continue
        if not expected:
            unavailable_sources.append(name)
            continue
        if expected and sha256_file(artifact_path) != expected:
            raise ValueError(f"chip strategy calibration input changed: {name}")
        verified_sources.append(name)
    return {
        **result,
        "source_verification": {
            "verified": verified_sources,
            "unavailable": unavailable_sources,
            "policy": (
                "Available calibration inputs must match their frozen hashes; portable runtime "
                "deployments may use the committed calibration without the large source tables."
            ),
        },
        "receipt_path": str(path),
        "receipt_sha256": sha256_file(path),
    }


def _available_chips(state: ManagerState) -> list[str]:
    half = 1 if state.event <= 19 else 2
    return sorted(
        slot.chip.value
        for slot in state.chips
        if slot.half == half and slot.status == ChipStatus.AVAILABLE
    )


def _event_team_chip_uplifts(
    action: EvaluatedAction,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_event_id = {
        (int(row["event_number"]), int(row["element"])): row for row in rows
    }
    opportunities = []
    for event_lineup in action.lineups:
        event = int(event_lineup.event)
        try:
            tc = float(by_event_id[(event, event_lineup.lineup.captain)]["expected_points"])
            bb = 0.92 * sum(
                float(by_event_id[(event, element)]["expected_points"])
                for element in event_lineup.lineup.bench_order
            )
        except KeyError:
            continue
        opportunities.extend(
            [
                {
                    "event": event,
                    "chip": ChipType.TRIPLE_CAPTAIN.value,
                    "projected_uplift": tc,
                    "source": "evaluated route captain forecast",
                },
                {
                    "event": event,
                    "chip": ChipType.BENCH_BOOST.value,
                    "projected_uplift": bb,
                    "source": "evaluated route bench forecast with autosub displacement",
                },
            ]
        )
    return opportunities


def _optimise_calendar(
    opportunities: Sequence[Mapping[str, Any]],
    available: Sequence[str],
    terminal_values: Mapping[str, float],
    *,
    excluded_event: int | None = None,
    excluded_chip: str | None = None,
    terminal_slots: int | None = None,
) -> dict[str, Any]:
    if terminal_slots is not None and (type(terminal_slots) is not int or terminal_slots < 0):
        raise ValueError("Unseen chip-calendar capacity must be a nonnegative integer")
    available_set = set(available)
    rows = [
        row
        for row in opportunities
        if str(row["chip"]) in available_set
        and (excluded_event is None or int(row["event"]) != excluded_event)
        and (excluded_chip is None or str(row["chip"]) != excluded_chip)
    ]
    events = sorted({int(row["event"]) for row in rows})
    by_event: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_event[int(row["event"])].append(row)
    states: dict[frozenset[str], tuple[float, list[dict[str, Any]]]] = {
        frozenset(): (0.0, [])
    }
    for event in events:
        updated = dict(states)
        for used, (value, path) in states.items():
            for row in by_event[event]:
                chip = str(row["chip"])
                if chip in used:
                    continue
                candidate = (
                    value + float(row["projected_uplift"]),
                    [*path, dict(row)],
                )
                key = frozenset({*used, chip})
                if key not in updated or candidate[0] > updated[key][0]:
                    updated[key] = candidate
        states = updated
    scored = []
    for used, (visible_value, path) in states.items():
        remaining_values = sorted(
            (float(terminal_values.get(chip, 0.0)) for chip in available_set
             if chip not in used and chip != excluded_chip), reverse=True)
        # One chip per GW applies beyond the visible forecast horizon too.
        # Independent chip priors cannot buy more uses than unseen deadlines.
        terminal = sum(remaining_values if terminal_slots is None
                       else remaining_values[:terminal_slots])
        scored.append((visible_value + terminal, visible_value, terminal, path))
    total, visible, terminal, path = max(scored, key=lambda row: row[0])
    return {
        "total_option_value": total,
        "visible_value": visible,
        "terminal_value": terminal,
        "allocations": path,
        "terminal_slots": terminal_slots,
    }


def _current_chip_candidates(
    team_shadow: Mapping[str, Any],
    squad_shadow: Mapping[str, Any],
    *,
    selected_action_id: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in team_shadow.get("candidates", []):
        joint_comparison = bool(row.get("comparison_ordinary_action_id"))
        if not joint_comparison and str(row.get("parent_action_id")) != selected_action_id:
            continue
        chip = str(row.get("chip"))
        scenario_rows = row.get("scenario_metrics") or {}
        raw = [float(value["mean_current_chip_uplift"]) for value in scenario_rows.values()]
        if not raw:
            continue
        if joint_comparison:
            candidate = {
                "chip": chip,
                "action_id": row.get("action_id"),
                "parent_action_id": row.get("parent_action_id"),
                "projected_uplift": float(row["weighted_delta_to_comparison_ordinary"]),
                "worst_model_world_uplift": float(row["worst_delta_to_comparison_ordinary"]),
                "paired_95ci_low": float(row["delta_to_comparison_95ci_low"]),
                "source": "shared-world joint transfer-and-team-chip simulation",
            }
        else:
            retained = float(row.get("retained_chip_proxy_value") or 0.0)
            candidate = {
                "chip": chip,
                "action_id": row.get("action_id"),
                "parent_action_id": row.get("parent_action_id"),
                "projected_uplift": float(row["weighted_mean_net_value"]) + retained,
                "worst_model_world_uplift": float(row["worst_scenario_net_value"])
                + retained,
                "paired_95ci_low": min(
                    float(value["net_value_95ci_low"]) + retained
                    for value in scenario_rows.values()
                ),
                "source": "shared-world team-chip simulation",
            }
        if chip not in result or candidate["projected_uplift"] > result[chip]["projected_uplift"]:
            result[chip] = candidate
    for row in squad_shadow.get("candidates", []):
        chip = str(row.get("chip"))
        scenario_rows = row.get("scenario_metrics") or {}
        raw = [float(value["mean_raw_delta_to_best_ordinary"]) for value in scenario_rows.values()]
        if not raw:
            continue
        candidate = {
            "chip": chip,
            "action_id": row.get("action_id"),
            "projected_uplift": float(row["weighted_raw_delta_to_best_ordinary"]),
            "worst_model_world_uplift": min(raw),
            "paired_95ci_low": min(
                float(value["raw_delta_95ci_low"]) for value in scenario_rows.values()
            ),
            "source": "shared-world exact squad-chip simulation",
        }
        if chip not in result or candidate["projected_uplift"] > result[chip]["projected_uplift"]:
            result[chip] = candidate
    return result


def synthesize_joint_chip_strategy(
    *,
    state: ManagerState,
    selected_action: EvaluatedAction,
    forecast_rows: Sequence[Mapping[str, Any]],
    team_shadow: Mapping[str, Any],
    squad_shadow: Mapping[str, Any],
    schedule_receipt: Mapping[str, Any],
    calibration: Mapping[str, Any],
    chip_actions: Sequence[EvaluatedAction] = (),
    squad_chip_actions: Sequence[EvaluatedAction] = (),
    squad_timing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = state.event
    _, _, half_end = _half_bounds(event)
    available = _available_chips(state)
    weeks_left = half_end - event + 1
    # One chip per Gameweek: once the chips left fill every remaining week,
    # holding any of them guarantees one expires unused.
    expiry_binding = bool(available) and len(available) >= weeks_left
    timing_verdict = (squad_timing or {}).get("verdict") or None
    chip_calendar = (squad_timing or {}).get("chip_calendar") or {}
    current = _current_chip_candidates(
        team_shadow,
        squad_shadow,
        selected_action_id=selected_action.action_id,
    )
    current_schedule = next(
        (
            row
            for row in schedule_receipt.get("event_summaries", [])
            if int(row["event"]) == event
        ),
        {},
    )
    future_opportunities = [
        row
        for row in _event_team_chip_uplifts(selected_action, forecast_rows)
        if event < int(row["event"]) <= half_end
    ]
    schedule_watch = [
        {
            "event": int(row["event"]),
            "blank_team_count": len(row.get("blank_teams") or []),
            "double_team_count": len(row.get("double_teams") or []),
            "at_risk_team_count": len(row.get("at_risk_teams") or []),
        }
        for row in schedule_receipt.get("event_summaries", [])
        if event < int(row["event"]) <= half_end
        and (row.get("blank_teams") or row.get("double_teams") or row.get("at_risk_teams"))
    ]
    terminal_event = max(
        [event, *(int(row["event"]) for row in future_opportunities)],
    )
    terminal_values: dict[str, float] = {}
    for chip in available:
        if terminal_event >= half_end:
            terminal_values[chip] = 0.0
        elif chip in TEAM_CHIPS:
            terminal_values[chip] = _lookup_retained(
                calibration["retained_value"], chip, terminal_event, quantile="p50"
            )
        else:
            prior = calibration["squad_chip_priors"][chip]
            events_remaining = half_end - terminal_event
            terminal_values[chip] = float(prior["p50"]) * max(events_remaining, 0) / 18.0
    no_current = _optimise_calendar(
        future_opportunities,
        available,
        terminal_values,
        terminal_slots=max(half_end - terminal_event, 0),
    )
    authorities = calibration.get("authority_by_chip") or {}
    candidates = []
    forced_actions = {
        action.action_id: action for action in (*chip_actions, *squad_chip_actions)
    }
    for chip in available:
        if chip not in current:
            continue
        row = current[chip]
        forced_action = forced_actions.get(str(row.get("action_id")))
        forced_future_opportunities = [
            opportunity
            for opportunity in _event_team_chip_uplifts(
                forced_action or selected_action,
                forecast_rows,
            )
            if event < int(opportunity["event"]) <= half_end
        ]
        retained_calendar = _optimise_calendar(
            forced_future_opportunities,
            available,
            terminal_values,
            excluded_event=event,
            excluded_chip=chip,
            terminal_slots=max(half_end - terminal_event, 0),
        )
        forced_total = float(row["projected_uplift"]) + float(
            retained_calendar["total_option_value"]
        )
        net = forced_total - float(no_current["total_option_value"])
        joint_ci_low = float(row["paired_95ci_low"]) + float(
            retained_calendar["total_option_value"]
        ) - float(no_current["total_option_value"])
        schedule_safe = not current_schedule.get("at_risk_teams")
        if chip == ChipType.WILDCARD.value:
            # Historical WC timing replays were inconclusive, so the blanket
            # authority stays off. The live full-half planner decides the week
            # instead: play now only when now beats every later Wildcard week.
            timing_ok = bool(timing_verdict and timing_verdict.get("play_now"))
            authority_check = {
                "name": "full-half timing: now is the best Wildcard week",
                "passed": timing_ok,
                "evidence": (
                    "no live Wildcard timing receipt for this squad and Gameweek"
                    if not timing_verdict
                    else (
                        f"planner best week GW{timing_verdict['best_wildcard_event']}; "
                        f"now minus best later={timing_verdict.get('now_minus_best_later')}"
                    )
                ),
            }
        elif chip == ChipType.FREE_HIT.value:
            # Free Hit value is one week; the joint calendar, every-world and
            # paired-uncertainty gates above already price holding it.
            authority_check = {
                "name": "single-week squad chip priced by joint calendar",
                "passed": True,
                "evidence": "Free Hit timing uses the joint calendar and uncertainty gates",
            }
        else:
            authority_check = {
                "name": "historical outcome authority",
                "passed": bool(authorities.get(chip)),
                "evidence": (
                    "rolling-origin recent-season gate passed"
                    if authorities.get(chip)
                    else "exact branch remains advisory pending reliable outcome calibration"
                ),
            }
        retained_edge_check = {
            "name": "positive joint retained-value edge",
            "passed": net > 0.0,
            "evidence": f"current route versus best retain calendar={net:+.2f} points",
        }
        reversal_check = {
            "name": "no model-world reversal",
            "passed": float(row["worst_model_world_uplift"]) > 0.0,
            "evidence": (
                f"worst shared simulation world={float(row['worst_model_world_uplift']):+.2f}"
            ),
        }
        uncertainty_check = {
            "name": "paired uncertainty excludes retention",
            "passed": joint_ci_low > 0.0,
            "evidence": f"joint paired 95% lower bound={joint_ci_low:+.2f} points",
        }
        schedule_check = {
            "name": "current schedule fit",
            "passed": schedule_safe,
            "evidence": (
                "current fixture allocation is confirmed and chip-appropriate"
                if schedule_safe
                else "current fixture allocation is unresolved"
            ),
        }
        calendar_now = (chip_calendar.get("now") or {}).get(chip)
        if chip != ChipType.WILDCARD.value and calendar_now is not None:
            # The full-half calendar prices every later week for this chip, so
            # it replaces the visible-horizon retention and authority checks.
            is_week = chip_calendar.get("play_now_chip") == chip
            checks = [
                reversal_check,
                schedule_check,
                {
                    "name": "full-half calendar: now is this chip's week",
                    "passed": is_week,
                    "evidence": (
                        f"gain now={float(calendar_now['gain_now']):+.2f}; edge over the best "
                        f"later week={float(calendar_now['edge_over_waiting']):+.2f} against "
                        f"{float(calendar_now['required_waiting_margin']):.1f} needed"
                    ),
                },
            ]
        elif chip == ChipType.WILDCARD.value and timing_verdict:
            # The timing verdict already carries a waiting margin and a paired
            # holdout separation across the whole half.
            checks = [reversal_check, schedule_check, authority_check]
        else:
            checks = [
                retained_edge_check,
                reversal_check,
                uncertainty_check,
                schedule_check,
                authority_check,
            ]
        candidates.append(
            {
                **row,
                "joint_net_value": net,
                "joint_net_95ci_low": joint_ci_low,
                "forced_current_total_option_value": forced_total,
                "retain_total_option_value": no_current["total_option_value"],
                "calendar_after_play": retained_calendar,
                "checks": checks,
                "operational_gate_passed": all(check["passed"] for check in checks),
            }
        )
    candidates.sort(key=lambda row: (-float(row["joint_net_value"]), str(row["chip"])))
    promoted = next(
        (row for row in candidates if row["operational_gate_passed"]),
        None,
    )
    expiry_forced = False
    if promoted is None and expiry_binding and candidates:
        # Use-it-or-lose-it: the best-valued chip now beats a guaranteed zero.
        promoted = candidates[0]
        expiry_forced = True
    recommendation = str(promoted["chip"]) if promoted else "no_chip"
    leader = candidates[0] if candidates else None
    deadline_plan = _chip_deadline_plan(
        available=available,
        event=event,
        half_end=half_end,
        promoted_chip=recommendation if promoted else None,
        retention_calendar={
            "allocations": [
                *(
                    row for row in chip_calendar.get("allocations") or []
                    if int(row["event"]) > event
                ),
                *(no_current.get("allocations") or []),
            ]
        },
        timing_verdict=timing_verdict,
    )
    expected_gain = {
        (str(row["chip"]), int(row["event"])): float(row["expected_gain"])
        for row in chip_calendar.get("allocations") or []
    }
    for plan_row in deadline_plan:
        plan_row["expected_gain"] = expected_gain.get(
            (plan_row["chip"], plan_row["planned_event"])
        )
    visible_calendar = sorted(
        [*future_opportunities, *schedule_watch],
        key=lambda row: (int(row["event"]), str(row.get("chip") or "schedule")),
    )
    return {
        "version": "joint_chip_strategy_v2",
        "status": "play_chip" if promoted else "retain_chips",
        "decision_event": event,
        "half": 1 if event <= 19 else 2,
        "half_expiry_event": half_end,
        "events_until_expiry": half_end - event,
        "available_chips": available,
        "operational_recommendation": recommendation,
        "recommended_action_id": promoted.get("action_id") if promoted else None,
        "headline": (
            f"Play {recommendation.replace('_', ' ').title()}"
            if promoted
            else "Retain all chips this Gameweek"
        ),
        "reason": (
            (
                f"{len(available)} chips left and {weeks_left} Gameweeks before the GW{half_end} "
                f"expiry: play {recommendation.replace('_', ' ').title()} now so no chip is lost."
            )
            if expiry_forced
            else f"{recommendation.replace('_', ' ').title()} clears the joint calendar, scenario and timing gates."
            if promoted
            else (
                "No current chip beats the best collision-aware retain calendar with its "
                "timing evidence."
            )
        ),
        "expiry_forced": expiry_forced,
        "expiry_binding": expiry_binding,
        "weeks_left_in_half": weeks_left,
        "deadline_plan": deadline_plan,
        "squad_timing": (
            {
                "version": squad_timing.get("version"),
                "created_at": squad_timing.get("created_at"),
                "verdict": timing_verdict,
                "chip_calendar": chip_calendar or None,
            }
            if squad_timing
            else None
        ),
        "expiry_unresolved": bool(expiry_binding and not candidates),
        "shadow_preference": (
            {"chip": leader["chip"], "joint_net_value": leader["joint_net_value"]}
            if leader
            else None
        ),
        "retention_calendar": no_current,
        "visible_calendar": visible_calendar,
        "schedule_watch": schedule_watch,
        "candidates": candidates,
        "calibration": {
            "status": calibration.get("status"),
            "historical_gate": calibration.get("historical_gate"),
            "authority_by_chip": authorities,
            "recency": calibration.get("recency"),
            "source_verification": calibration.get("source_verification"),
            "receipt_path": calibration.get("receipt_path"),
            "receipt_sha256": calibration.get("receipt_sha256"),
        },
        "policy": {
            "objective": "maximum expected net FPL points through chip-half expiry",
            "one_chip_per_event": True,
            "half_expiry_enforced_in_all_calendars": True,
            "unseen_calendar_capacity_enforced": True,
            "terminal_retained_value": True,
            "future_schedule_missing_is_not_no_exception": True,
            "team_chips_can_receive_historical_authority": True,
            "squad_chips_remain_advisory": False,
            "wildcard_timing": "live full-half planner picks the week",
            "free_hit_timing": "joint calendar and uncertainty gates",
            "one_week_chip_timing": (
                "live full-half calendar picks the week" if chip_calendar.get("now") is not None
                else "visible-horizon retention gates"
            ),
            "use_before_expiry_guaranteed": True,
        },
    }


def _chip_deadline_plan(
    *,
    available: Sequence[str],
    event: int,
    half_end: int,
    promoted_chip: str | None,
    retention_calendar: Mapping[str, Any],
    timing_verdict: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Planned week and latest safe week for every unused chip this half.

    Planned weeks are estimates refreshed every Gameweek, not bookings. The
    latest safe week is a hard bound: with k chips still held after it, the
    expiry rule fires at ``half_end - k + 1`` at the latest.
    """
    planned: dict[str, int] = {}
    if promoted_chip:
        planned[promoted_chip] = event
    if (
        timing_verdict
        and ChipType.WILDCARD.value in available
        and ChipType.WILDCARD.value not in planned
    ):
        week = int(timing_verdict["best_wildcard_event"])
        if week not in planned.values() and event < week <= half_end:
            planned[ChipType.WILDCARD.value] = week
    for row in retention_calendar.get("allocations") or []:
        chip = str(row["chip"])
        if chip in available and chip not in planned and int(row["event"]) not in planned.values():
            planned[chip] = int(row["event"])
    remaining = sorted(available)
    # Fill unplanned chips into the latest free weeks so the plan is always
    # feasible: one chip per week, every chip before expiry.
    taken = set(planned.values())
    for chip in remaining:
        if chip in planned:
            continue
        week = next((w for w in range(half_end, event - 1, -1) if w not in taken), None)
        if week is None:
            continue
        planned[chip] = week
        taken.add(week)
    remaining = [chip for chip in remaining if chip in planned]
    order = sorted(remaining, key=lambda c: planned[c])
    rows = []
    for index, chip in enumerate(sorted(remaining, key=lambda c: -planned[c])):
        latest_safe = half_end - index
        rows.append(
            {
                "chip": chip,
                "planned_event": planned[chip],
                "latest_safe_event": latest_safe,
                "play_now": chip == promoted_chip,
            }
        )
    return sorted(rows, key=lambda r: order.index(r["chip"]))
