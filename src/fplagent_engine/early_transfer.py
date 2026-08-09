from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.market_telemetry import (
    CURRENT_FEATURE_RECEIPT,
    CURRENT_FEATURES,
    PRICE_OUTCOME_RECEIPT,
)

from .season_state import ManagerState, calculated_selling_price

MAXIMUM_FEATURE_AGE = timedelta(minutes=45)


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("early-transfer timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _load_features(
    feature_path: Path, receipt_path: Path, *, as_of: datetime
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "ready":
        raise ValueError("market feature receipt is not ready")
    if receipt.get("output_sha256") != sha256_file(feature_path):
        raise ValueError("market feature bytes no longer match their receipt")
    feature_at = _aware(str(receipt["feature_at"]))
    age = as_of - feature_at
    if age < timedelta(0):
        raise ValueError("market features were observed after the decision time")
    if age > MAXIMUM_FEATURE_AGE:
        raise ValueError(
            f"market features are {age.total_seconds() / 60:.1f} minutes old"
        )
    rows = pq.read_table(feature_path).to_pylist()
    by_element = {int(row["element"]): row for row in rows}
    if len(by_element) != len(rows):
        raise ValueError("market feature artifact contains duplicate players")
    return by_element, receipt


def _next_uk_midnight(as_of: datetime) -> datetime:
    london = ZoneInfo("Europe/London")
    local = as_of.astimezone(london)
    return (local + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).astimezone(UTC)


def _selling_loss_after_fall(purchase_price: int, current_price: int) -> int:
    if current_price <= 1:
        return 0
    current = calculated_selling_price(purchase_price, current_price)
    fallen = calculated_selling_price(purchase_price, current_price - 1)
    return max(0, current - fallen)


def evaluate_early_transfer_shadow(
    state: ManagerState,
    selected_action: Any,
    *,
    deadline_at: str | datetime,
    as_of: str | datetime,
    selection_stable: bool,
    feature_path: Path = CURRENT_FEATURES,
    feature_receipt_path: Path = CURRENT_FEATURE_RECEIPT,
    outcome_receipt_path: Path = PRICE_OUTCOME_RECEIPT,
) -> dict[str, Any]:
    """Evaluate affordability risk without authorising an early transfer."""
    transfers = tuple(selected_action.action.transfers)
    base = {
        "decision_authority": False,
        "operational_recommendation": "wait",
        "action_id": str(selected_action.action_id),
        "route_type": str(selected_action.route_type),
        "transfer_count": len(transfers),
    }
    if not transfers:
        return {
            **base,
            "status": "not_applicable",
            "reason": "The selected route makes no transfer, so execution timing is irrelevant.",
        }
    checked = _aware(as_of)
    deadline = _aware(deadline_at)
    if checked >= deadline:
        return {**base, "status": "not_ready", "reason": "The FPL deadline has passed."}
    try:
        features, feature_receipt = _load_features(
            feature_path,
            feature_receipt_path,
            as_of=checked,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {**base, "status": "not_ready", "reason": str(error)}

    next_midnight = _next_uk_midnight(checked)
    price_change_before_deadline = next_midnight < deadline
    holdings = {holding.player_id: holding for holding in state.squad}
    transfer_rows = []
    total_stress_cost = 0
    missing = []
    incoming_information_clear = True
    for transfer in transfers:
        outgoing_id = int(transfer.outgoing_player_id)
        incoming_id = int(transfer.incoming.player_id)
        outgoing_feature = features.get(outgoing_id)
        incoming_feature = features.get(incoming_id)
        holding = holdings.get(outgoing_id)
        if outgoing_feature is None or incoming_feature is None or holding is None:
            missing.extend(
                element
                for element, value in (
                    (outgoing_id, outgoing_feature),
                    (incoming_id, incoming_feature),
                )
                if value is None
            )
            continue
        incoming_progress = float(incoming_feature["price_change_percent"])
        outgoing_progress = float(outgoing_feature["price_change_percent"])
        incoming_rise = price_change_before_deadline and incoming_progress >= 100.0
        outgoing_fall = price_change_before_deadline and outgoing_progress <= -100.0
        incoming_cost = 1 if incoming_rise else 0
        outgoing_cost = (
            _selling_loss_after_fall(holding.purchase_price, holding.current_price)
            if outgoing_fall
            else 0
        )
        total_stress_cost += incoming_cost + outgoing_cost
        incoming_clear = (
            str(incoming_feature.get("status") or "") == "a"
            and incoming_feature.get("chance_this_round") in (None, 100)
            and not str(incoming_feature.get("news") or "").strip()
        )
        incoming_information_clear &= incoming_clear
        transfer_rows.append(
            {
                "outgoing_player_id": outgoing_id,
                "incoming_player_id": incoming_id,
                "outgoing_progress_percent": outgoing_progress,
                "incoming_progress_percent": incoming_progress,
                "outgoing_net_transfer_velocity_per_hour": float(
                    outgoing_feature["net_transfer_velocity_per_hour"]
                ),
                "incoming_net_transfer_velocity_per_hour": float(
                    incoming_feature["net_transfer_velocity_per_hour"]
                ),
                "incoming_expected_to_rise_at_next_update": incoming_rise,
                "outgoing_expected_to_fall_at_next_update": outgoing_fall,
                "incoming_price_stress_cost": incoming_cost,
                "outgoing_sale_stress_cost": outgoing_cost,
                "incoming_information_clear": incoming_clear,
            }
        )
    if missing:
        return {
            **base,
            "status": "not_ready",
            "reason": f"Market features are missing players: {sorted(set(missing))}",
        }

    current_bank = int(selected_action.outcome.gameweek.bank)
    stress_bank = current_bank - total_stress_cost
    route_blocked = stress_bank < 0
    shadow_preference = (
        "move_now_candidate"
        if route_blocked and selection_stable and incoming_information_clear
        else "wait"
    )
    calibration = None
    if outcome_receipt_path.is_file():
        try:
            calibration = json.loads(outcome_receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            calibration = None
    calibration_passed = bool(
        calibration and (calibration.get("calibration_gate") or {}).get("passed")
    )
    return {
        **base,
        "status": "ready_shadow",
        "shadow_preference": shadow_preference,
        "selection_stable": selection_stable,
        "incoming_information_clear": incoming_information_clear,
        "checked_at": checked.isoformat(),
        "deadline_at": deadline.isoformat(),
        "next_price_change_at": next_midnight.isoformat(),
        "price_change_before_deadline": price_change_before_deadline,
        "bank_after_transfer_now": current_bank,
        "threshold_stress_cost": total_stress_cost,
        "bank_after_threshold_stress": stress_bank,
        "route_blocked_by_threshold_stress": route_blocked,
        "transfers": transfer_rows,
        "official_indicator_calibration_passed": calibration_passed,
        "prospective_outcome_nights": (
            int(calibration.get("outcome_nights", 0)) if calibration else 0
        ),
        "feature_artifact": str(feature_path),
        "feature_artifact_sha256": feature_receipt["output_sha256"],
        "feature_receipt": str(feature_receipt_path),
        "feature_receipt_sha256": sha256_file(feature_receipt_path),
        "promotion_policy": (
            "The official progress indicator and route affordability are evidence only. "
            "Operational advice remains wait until prospective threshold calibration and a "
            "net-points timing replay quantify the cost of information lost by moving early."
        ),
    }
