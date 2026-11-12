from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import CONSENSUS, RECEIPT

MAX_EVIDENCE_AGE = timedelta(hours=12)
SHORT_MINUTES = 28.0
MEDIUM_MINUTES = 75.0
BENCH_ROLE_PERSISTENCE = {1: 0.55, 2: 0.25}
TWO_SOURCE_START_ODDS_MULTIPLIER = 10.0
SINGLE_SOURCE_START_ODDS_MULTIPLIER = 2.5
TWO_SOURCE_START_DURATION_WEIGHT = 0.65
SINGLE_SOURCE_START_DURATION_WEIGHT = 0.30
TWO_SOURCE_BENCH_WEIGHT = 0.75
SINGLE_SOURCE_BENCH_WEIGHT = 0.35
TWO_SOURCE_BENCH_PLAY_CEILING = 0.60
SINGLE_SOURCE_BENCH_PLAY_CEILING = 0.72
TWO_SOURCE_REPEAT_EXCLUSION_PLAY_CEILING = 0.30
SINGLE_SOURCE_REPEAT_EXCLUSION_PLAY_CEILING = 0.45
TWO_SOURCE_BENCH_CONDITIONAL_MINUTES = 30.0
SINGLE_SOURCE_BENCH_CONDITIONAL_MINUTES = 34.0
MAX_TWO_SOURCE_START_MINUTE_UPLIFT = 36.0
MAX_SINGLE_SOURCE_START_MINUTE_UPLIFT = 18.0
DURABLE_ROLE_MIN_APPEARANCE_RATE = 0.70
DURABLE_ROLE_MIN_START_RATE = 0.60
DURABLE_ROLE_MIN_HISTORY_MINUTES = 60.0
DURABLE_ROLE_MAX_PLAY_PROBABILITY = 0.95
DURABLE_ROLE_BASE_UNCERTAINTY = 0.10
DURABLE_ROLE_HORIZON_UNCERTAINTY = 0.02
START_HISTORY_FIELDS = (
    ("form10_minutes", 0.20),
    ("form38_minutes", 0.15),
)


def current_participation_inputs(
    *,
    receipt_path: Path = RECEIPT,
    consensus_path: Path = CONSENSUS,
) -> dict[str, str | None]:
    """Hash the live role evidence so forecast caching cannot hide a lineup change."""

    return {
        "participation_policy_implementation_sha256": sha256_file(Path(__file__)),
        "participation_receipt_sha256": (
            sha256_file(receipt_path) if receipt_path.is_file() else None
        ),
        "participation_consensus_sha256": (
            sha256_file(consensus_path) if consensus_path.is_file() else None
        ),
    }


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("participation timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _probabilities(row: dict[str, Any]) -> tuple[float, float, float, float]:
    values = tuple(
        max(float(row.get(field) or 0.0), 0.0)
        for field in ("p_dnp", "p_1_59", "p_60_89", "p_90_or_more")
    )
    total = sum(values)
    if total <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(value / total for value in values)  # type: ignore[return-value]


def _blend(
    incumbent: tuple[float, float, float, float],
    target: tuple[float, float, float, float],
    weight: float,
) -> tuple[float, float, float, float]:
    values = tuple(
        (1.0 - weight) * current + weight * proposed
        for current, proposed in zip(incumbent, target, strict=True)
    )
    total = sum(values)
    return tuple(value / total for value in values)  # type: ignore[return-value]


def _cap_play_probability(
    probabilities: tuple[float, float, float, float], chance: float
) -> tuple[float, float, float, float]:
    cap = min(max(chance, 0.0), 1.0)
    play = sum(probabilities[1:])
    if play <= cap or play <= 0.0:
        return probabilities
    scale = cap / play
    return (
        1.0 - cap,
        probabilities[1] * scale,
        probabilities[2] * scale,
        probabilities[3] * scale,
    )


def _recent_usage_minutes(row: dict[str, Any], *, position: str) -> float | None:
    """Estimate minutes conditional on appearing without manufacturing a duration floor."""

    values: list[tuple[float, float]] = []
    last_minutes = float(row.get("last_minutes") or 0.0)
    if last_minutes > 0.0:
        values.append((min(last_minutes, 90.0), 0.25))
    form5_minutes = float(row.get("form5_minutes") or 0.0)
    appearance_rate5 = float(row.get("appearance_rate5") or 0.0)
    if form5_minutes > 0.0 and appearance_rate5 > 0.05:
        values.append((min(form5_minutes / appearance_rate5, 90.0), 0.40))
    for field, weight in START_HISTORY_FIELDS:
        raw = row.get(field)
        if raw is None or float(raw) <= 0.0:
            continue
        values.append((min(float(raw), 90.0), weight))
    if not values:
        return None
    return sum(value * weight for value, weight in values) / sum(weight for _, weight in values)


def _posterior_play_probability(
    prior: float,
    *,
    odds_multiplier: float,
    ceiling: float,
) -> float:
    bounded = min(max(prior, 0.005), 0.995)
    odds = bounded / (1.0 - bounded)
    posterior = odds * odds_multiplier / (1.0 + odds * odds_multiplier)
    return min(max(posterior, prior), ceiling)


def _conditional_distribution_for_minutes(
    expected_minutes: float,
) -> tuple[float, float, float]:
    """Return short/medium/full conditional mass with the requested mean duration."""

    desired = min(max(expected_minutes, SHORT_MINUTES), 90.0)
    if desired <= MEDIUM_MINUTES:
        short = (MEDIUM_MINUTES - desired) / (MEDIUM_MINUTES - SHORT_MINUTES)
        return short, 1.0 - short, 0.0
    full = (desired - MEDIUM_MINUTES) / (90.0 - MEDIUM_MINUTES)
    return 0.0, 1.0 - full, full


def _bounded_start_distribution(
    incumbent: tuple[float, float, float, float],
    row: dict[str, Any],
    *,
    position: str,
    source_count: int,
    official_clear: bool,
) -> tuple[float, float, float, float]:
    """Update start probability while retaining player-specific conditional duration."""

    prior_play = sum(incumbent[1:])
    prior_minutes = _expected_minutes(incumbent)
    prior_conditional_minutes = prior_minutes / max(prior_play, 0.005)
    usage = _recent_usage_minutes(row, position=position)
    if source_count >= 2:
        multiplier = TWO_SOURCE_START_ODDS_MULTIPLIER
        duration_weight = TWO_SOURCE_START_DURATION_WEIGHT
        maximum_uplift = MAX_TWO_SOURCE_START_MINUTE_UPLIFT
        play_ceiling = 0.975 if official_clear else 0.95
    else:
        multiplier = SINGLE_SOURCE_START_ODDS_MULTIPLIER
        duration_weight = SINGLE_SOURCE_START_DURATION_WEIGHT
        maximum_uplift = MAX_SINGLE_SOURCE_START_MINUTE_UPLIFT
        play_ceiling = 0.94 if official_clear else 0.90
    posterior_play = _posterior_play_probability(
        prior_play,
        odds_multiplier=multiplier,
        ceiling=play_ceiling,
    )
    if not official_clear:
        posterior_play = min(
            posterior_play,
            float(row["availability_chance"] if row.get("availability_chance") is not None else 100.0) / 100.0,
        )

    if position == "GK":
        usage_target = min(max(usage or prior_conditional_minutes, 82.0), 90.0)
    else:
        # A predicted start supports a real starting role, but not a generic 72-minute floor.
        # Fifty-five conditional minutes is enough to represent an early-substitution starter;
        # established player usage can move the target higher on its own evidence.
        usage_target = min(max(usage or prior_conditional_minutes, 55.0), 88.0)
    desired_conditional_minutes = (
        1.0 - duration_weight
    ) * prior_conditional_minutes + duration_weight * usage_target
    desired_total_minutes = min(
        posterior_play * desired_conditional_minutes,
        prior_minutes + maximum_uplift,
    )
    desired_conditional_minutes = desired_total_minutes / max(posterior_play, 0.005)
    short, medium, full = _conditional_distribution_for_minutes(desired_conditional_minutes)
    return (
        1.0 - posterior_play,
        posterior_play * short,
        posterior_play * medium,
        posterior_play * full,
    )


def _bounded_bench_distribution(
    incumbent: tuple[float, float, float, float],
    row: dict[str, Any],
    *,
    source_count: int,
) -> tuple[float, float, float, float]:
    """Translate a predicted bench into a one-sided, cameo-shaped role update.

    A predicted bench is evidence about starting status, not proof of a DNP.  The
    previous static target could nevertheless *increase* the play probability of
    a player whose incumbent model already recognised a weak role.  This target
    can only retain or reduce incumbent play probability and moves conditional
    duration toward a substitute appearance.  A player who also logged zero
    minutes in the latest match receives a stronger, still-bounded role-shock cap.
    """

    prior_play = sum(incumbent[1:])
    repeated_exclusion = float(row.get("last_minutes") or 0.0) <= 0.0
    if source_count >= 2:
        ceiling = (
            TWO_SOURCE_REPEAT_EXCLUSION_PLAY_CEILING
            if repeated_exclusion
            else TWO_SOURCE_BENCH_PLAY_CEILING
        )
        conditional_minutes = TWO_SOURCE_BENCH_CONDITIONAL_MINUTES
    else:
        ceiling = (
            SINGLE_SOURCE_REPEAT_EXCLUSION_PLAY_CEILING
            if repeated_exclusion
            else SINGLE_SOURCE_BENCH_PLAY_CEILING
        )
        conditional_minutes = SINGLE_SOURCE_BENCH_CONDITIONAL_MINUTES
    target_play = min(prior_play, ceiling)
    short, medium, full = _conditional_distribution_for_minutes(conditional_minutes)
    return (
        1.0 - target_play,
        target_play * short,
        target_play * medium,
        target_play * full,
    )


def _durable_role_distribution(
    evidence: dict[str, Any],
    row: dict[str, Any],
    incumbent: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float, float], float, float] | None:
    """Return a future role prior supported independently by historical usage.

    A current predicted start is useful evidence that an established role still
    exists, but it is not itself a prediction of a future lineup.  The target
    below therefore comes only from point-in-time historical appearance and
    minutes fields.  ``min(form10, form38) / 90`` is deliberately conservative:
    both the recent and longer windows must support the role, and average
    minutes divided by 90 is a lower bound on the historical play rate.
    """

    if (
        str(evidence.get("consensus") or "") != "predicted_start_consensus"
        or str(evidence.get("official_status") or "") != "clear"
    ):
        return None
    appearance_rate = float(row.get("appearance_rate5") or 0.0)
    start_rate = float(row.get("start_rate5") or 0.0)
    form10 = float(row.get("form10_minutes") or 0.0)
    form38 = float(row.get("form38_minutes") or 0.0)
    if (
        appearance_rate < DURABLE_ROLE_MIN_APPEARANCE_RATE
        or start_rate < DURABLE_ROLE_MIN_START_RATE
        or min(form10, form38) < DURABLE_ROLE_MIN_HISTORY_MINUTES
    ):
        return None

    current_play = sum(incumbent[1:])
    role_play = min(
        max(min(form10, form38) / 90.0, current_play),
        DURABLE_ROLE_MAX_PLAY_PROBABILITY,
    )
    availability_cap = float(
        row["availability_chance"] if row.get("availability_chance") is not None else 100.0
    ) / 100.0
    role_play = min(role_play, availability_cap)
    current_minutes = _expected_minutes(incumbent)
    current_conditional = current_minutes / max(current_play, 0.005)
    usage = _recent_usage_minutes(row, position=str(row["position"]))
    role_conditional = min(max(usage or current_conditional, current_conditional), 88.0)
    short, medium, full = _conditional_distribution_for_minutes(role_conditional)
    target = (
        1.0 - role_play,
        role_play * short,
        role_play * medium,
        role_play * full,
    )
    target_minutes = _expected_minutes(target)
    if target_minutes <= current_minutes + 1e-9:
        return None
    return target, role_play, target_minutes


def _target_distribution(
    evidence: dict[str, Any], row: dict[str, Any]
) -> tuple[tuple[float, float, float, float] | None, float, str]:
    position = str(row["position"])
    official = str(evidence.get("official_status") or "")
    consensus = str(evidence.get("consensus") or "")
    if official == "unavailable":
        return (1.0, 0.0, 0.0, 0.0), 1.0, "official_unavailable"

    is_keeper = position == "GK"
    if consensus == "predicted_start_consensus":
        target = _bounded_start_distribution(
            _probabilities(row),
            row,
            position=position,
            source_count=2,
            official_clear=official == "clear",
        )
        weight = 1.0
        reason = "two_source_start"
    elif consensus == "predicted_bench_consensus":
        target = (
            (0.96, 0.01, 0.01, 0.02)
            if is_keeper
            else _bounded_bench_distribution(_probabilities(row), row, source_count=2)
        )
        weight = TWO_SOURCE_BENCH_WEIGHT if official == "clear" else 0.55
        reason = "two_source_bench"
    elif consensus == "single_source_start":
        target = _bounded_start_distribution(
            _probabilities(row),
            row,
            position=position,
            source_count=1,
            official_clear=official == "clear",
        )
        weight = 1.0
        reason = "single_source_start"
    elif consensus == "single_source_bench":
        target = (
            (0.85, 0.02, 0.04, 0.09)
            if is_keeper
            else _bounded_bench_distribution(_probabilities(row), row, source_count=1)
        )
        weight = SINGLE_SOURCE_BENCH_WEIGHT
        reason = "single_source_bench"
    else:
        return None, 0.0, consensus or "no_consensus"

    chance = float(evidence.get("official_chance") or 0.0) / 100.0
    if official != "clear" and chance < 1.0:
        target = _cap_play_probability(target, chance)
    return target, weight, reason


def _expected_minutes(probabilities: tuple[float, float, float, float]) -> float:
    return (
        probabilities[1] * SHORT_MINUTES
        + probabilities[2] * MEDIUM_MINUTES
        + probabilities[3] * 90.0
    )


def _appearance_points(probabilities: tuple[float, float, float, float]) -> float:
    return probabilities[1] + 2.0 * (probabilities[2] + probabilities[3])


def _load_evidence(
    receipt_path: Path, consensus_path: Path, *, as_of: datetime
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not bool(receipt.get("decision_eligible")):
        raise ValueError("participation evidence is not decision eligible")
    observed = _aware(str(receipt["observed_at"]))
    deadline = _aware(str(receipt["deadline_time"]))
    age = as_of - observed
    if age < timedelta(0) or age > MAX_EVIDENCE_AGE or as_of >= deadline:
        raise ValueError("participation evidence is stale or outside its decision window")
    outputs = receipt.get("outputs") or {}
    if outputs.get("consensus_sha256") != sha256_file(consensus_path):
        raise ValueError("participation consensus no longer matches its receipt")
    captured = sum(
        source.get("status") == "captured" and source.get("decision_eligible")
        for source in (receipt.get("sources") or {}).values()
    )
    rows = pq.read_table(consensus_path).to_pylist()
    if captured < 1:
        raise ValueError("one decision-eligible predicted-lineup source is required")
    if captured < 2:
        authority = receipt.get("authority") or {}
        bounded_override = bool(authority.get("operator_override_active")) and str(
            authority.get("predicted_lineup_consensus") or ""
        ).startswith("bounded_production_operator_override")
        if not bounded_override:
            raise ValueError(
                "two decision-eligible predicted-lineup sources are required without "
                "the bounded single-source operator policy"
            )
        rows = [
            row
            for row in rows
            if bool(row.get("production_adjustment_authorized"))
            and str(row.get("consensus") or "").startswith("single_source_")
        ]
        if not rows:
            raise ValueError("bounded single-source evidence has no authorised player rows")
    receipt = {**receipt, "runtime_eligible_source_count": captured}
    return {int(row["element"]): row for row in rows}, receipt


def apply_current_participation_policy(
    forecast_rows: list[dict[str, Any]],
    *,
    receipt_path: Path = RECEIPT,
    consensus_path: Path = CONSENSUS,
    as_of: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply official + two-source role evidence to every covered player.

    The policy changes the complete minute distribution and then rescales only the
    non-appearance part of xP by the expected-minute ratio. The incumbent forecast
    remains on each row for audit and downside simulation.
    """

    inactive = {
        "status": "inactive",
        "decision_authority": False,
        "applied_rows": 0,
    }
    try:
        evidence, receipt = _load_evidence(
            receipt_path,
            consensus_path,
            as_of=(as_of or datetime.now(UTC)),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pa.ArrowException) as error:
        output = []
        for raw in forecast_rows:
            row = dict(raw)
            row.update(
                {
                    "live_participation_applied": False,
                    "live_participation_consensus": None,
                    "live_participation_weight": 0.0,
                    "live_participation_expected_minutes": None,
                    "live_participation_conditional_minutes": None,
                    "live_participation_expected_points": None,
                    "live_role_minutes_ratio": 1.0,
                    "live_participation_persistence_offset": None,
                    "live_participation_role_prior_applied": False,
                    "live_participation_role_prior_probability": None,
                    "live_participation_role_prior_minutes": None,
                }
            )
            output.append(row)
        return output, {**inactive, "reason": f"{type(error).__name__}: {error}"}

    output = []
    applied = []
    persistence_applied = 0
    durable_role_applied = 0
    consensus_counts: dict[str, int] = {}
    for raw in forecast_rows:
        row = dict(raw)
        item = evidence.get(int(row["element"]))
        current = _probabilities(row)
        proposed = None
        weight = 0.0
        reason = "not_covered"
        persistence_offset = None
        role_prior_probability = None
        role_prior_minutes = None
        event_offset = None
        if item is not None:
            event_offset = int(row["event_number"]) - int(item["event"])
            consensus = str(item.get("consensus") or "")
            if event_offset == 0:
                proposed, weight, reason = _target_distribution(item, row)
            elif event_offset in BENCH_ROLE_PERSISTENCE and consensus in {
                "predicted_bench_consensus",
                "single_source_bench",
            }:
                proposed, weight, reason = _target_distribution(item, row)
                weight *= BENCH_ROLE_PERSISTENCE[event_offset]
                reason = f"{reason}_persistence_gw{event_offset + 1}"
                persistence_offset = event_offset
            elif event_offset > 0 and consensus == "predicted_start_consensus":
                durable = _durable_role_distribution(item, row, current)
                if durable is not None:
                    proposed, role_prior_probability, role_prior_minutes = durable
                    weight = 1.0
                    reason = "durable_role_prior"
                    persistence_offset = event_offset
        if proposed is None or weight <= 0.0:
            uncertainty = float(row.get("epistemic_uncertainty") or 0.0)
            if (
                item is not None
                and event_offset == 0
                and str(item.get("consensus")) == "source_disagreement"
            ):
                uncertainty += 0.35
                row["epistemic_uncertainty"] = uncertainty
                row["robust_points"] = float(row["expected_points"]) - 0.15 * uncertainty
            row.update(
                {
                    "live_participation_applied": False,
                    "live_participation_consensus": (
                        str(item.get("consensus")) if item is not None else None
                    ),
                    "live_participation_weight": 0.0,
                    "live_participation_expected_minutes": None,
                    "live_participation_conditional_minutes": None,
                    "live_participation_expected_points": None,
                    "live_role_minutes_ratio": 1.0,
                    "live_participation_persistence_offset": None,
                    "live_participation_role_prior_applied": False,
                    "live_participation_role_prior_probability": role_prior_probability,
                    "live_participation_role_prior_minutes": role_prior_minutes,
                }
            )
            output.append(row)
            continue

        adjusted = _blend(current, proposed, weight)
        old_minutes = _expected_minutes(current)
        proposed_minutes = _expected_minutes(adjusted)
        if (
            ("_start" in reason or reason == "durable_role_prior")
            and proposed_minutes < old_minutes
            or "_bench" in reason
            and proposed_minutes > old_minutes
        ):
            adjusted = current
        new_minutes = _expected_minutes(adjusted)
        officially_unavailable = reason == "official_unavailable"
        # The 35% lower bound protects against overreacting to an ordinary
        # predicted-bench signal. It must never manufacture residual attacking
        # output for a player whom official FPL says cannot play.
        minute_ratio = (
            0.0
            if officially_unavailable
            else min(max(new_minutes / max(old_minutes, 5.0), 0.35), 2.0)
        )
        old_xp = float(row["expected_points"])
        old_appearance = _appearance_points(current)
        new_appearance = _appearance_points(adjusted)
        nonappearance = old_xp - old_appearance
        new_xp = (
            0.0
            if officially_unavailable
            else max(new_appearance + nonappearance * minute_ratio, 0.0)
        )
        old_robust = float(row.get("robust_points") or old_xp)
        uncertainty = float(row.get("epistemic_uncertainty") or 0.0)
        if reason.startswith("two_source_bench"):
            uncertainty += 0.15
        if reason == "durable_role_prior":
            uncertainty += DURABLE_ROLE_BASE_UNCERTAINTY + (
                DURABLE_ROLE_HORIZON_UNCERTAINTY * min(int(event_offset or 0), 7)
            )
        uncertainty = (
            0.0
            if officially_unavailable
            else uncertainty + 0.05 * abs(new_xp - old_xp)
        )
        p_play = sum(adjusted[1:])
        row.update(
            {
                "incumbent_expected_points_before_live_participation": old_xp,
                "incumbent_robust_points_before_live_participation": old_robust,
                "incumbent_p_play_before_live_participation": sum(current[1:]),
                "incumbent_expected_minutes_before_live_participation": old_minutes,
                "p_dnp": adjusted[0],
                "p_1_59": adjusted[1],
                "p_60_89": adjusted[2],
                "p_90_or_more": adjusted[3],
                "p_play": p_play,
                "conditional_points_if_playing": new_xp / max(p_play, 0.005),
                "expected_points": new_xp,
                "epistemic_uncertainty": uncertainty,
                "robust_points": new_xp - 0.15 * uncertainty,
                "live_participation_applied": True,
                "live_participation_consensus": str(item["consensus"]),
                "live_participation_reason": reason,
                "live_participation_weight": weight,
                "live_participation_expected_minutes": new_minutes,
                "live_participation_conditional_minutes": (new_minutes / max(p_play, 0.005)),
                "live_participation_recent_usage_minutes": _recent_usage_minutes(
                    row,
                    position=str(row["position"]),
                ),
                "live_participation_expected_points": new_xp,
                "live_role_minutes_ratio": minute_ratio,
                "live_participation_sources": list(item["predicted_start_sources"]),
                "live_participation_not_start_sources": list(item["predicted_not_start_sources"]),
                "live_participation_persistence_offset": persistence_offset,
                "live_participation_role_prior_applied": reason == "durable_role_prior",
                "live_participation_role_prior_probability": role_prior_probability,
                "live_participation_role_prior_minutes": role_prior_minutes,
            }
        )
        applied.append(new_xp - old_xp)
        persistence_applied += persistence_offset is not None
        durable_role_applied += reason == "durable_role_prior"
        name = str(item["consensus"])
        consensus_counts[name] = consensus_counts.get(name, 0) + 1
        output.append(row)

    eligible_source_count = int(receipt.get("runtime_eligible_source_count") or 0)
    policy = (
        "bounded_official_single_source_operator_v1"
        if eligible_source_count == 1
        else "bounded_official_two_source_ensemble_v2_durable_role"
    )
    return output, {
        "status": "applied",
        "decision_authority": True,
        "policy": policy,
        "eligible_source_count": eligible_source_count,
        "applied_rows": len(applied),
        "persistence_applied_rows": persistence_applied,
        "durable_role_prior_applied_rows": durable_role_applied,
        "consensus_counts": consensus_counts,
        "mean_expected_points_shift": sum(applied) / len(applied) if applied else 0.0,
        "maximum_absolute_expected_points_shift": max(map(abs, applied), default=0.0),
        "receipt": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "consensus": str(consensus_path),
        "consensus_sha256": sha256_file(consensus_path),
        "evidence_observed_at": receipt["observed_at"],
        "evidence_deadline": receipt["deadline_time"],
        "historical_calibration": "prospective_pending_bounded_deployment",
    }
