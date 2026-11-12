from __future__ import annotations

from typing import Any

MIN_EXPECTED_MINUTES = 60.0
MIN_PLAY_PROBABILITY = 0.85
STARTER_MINUTES = {"GK": 70.0, "DEF": 60.0, "MID": 55.0, "FWD": 55.0}
STARTER_MIN_PLAY_PROBABILITY = 0.85
CAPTAIN_MIN_EXPECTED_MINUTES = 65.0
CAPTAIN_MIN_PLAY_PROBABILITY = 0.90
VICE_CAPTAIN_MIN_EXPECTED_MINUTES = 60.0
ACTIVE_BENCH_MIN_EXPECTED_MINUTES = 50.0
ACTIVE_BENCH_MIN_PLAY_PROBABILITY = 0.80
DEEP_OUTFIELD_BENCH_MIN_EXPECTED_MINUTES = 30.0
DEEP_OUTFIELD_BENCH_MIN_PLAY_PROBABILITY = 0.50
PREMIUM_PRICE_TENTHS = {
    "GK": 55.0,
    "DEF": 55.0,
    "MID": 70.0,
    "FWD": 70.0,
}


def expected_minutes(row: dict[str, Any]) -> float:
    if row.get("expected_minutes") is not None:
        return float(row["expected_minutes"])
    if not any(row.get(field) is not None for field in ("p_1_59", "p_60_89", "p_90_or_more")):
        return 75.0 * float(row.get("p_play", 1.0))
    return (
        28.0 * float(row.get("p_1_59") or 0.0)
        + 75.0 * float(row.get("p_60_89") or 0.0)
        + 90.0 * float(row.get("p_90_or_more") or 0.0)
    )


def player_capital_role_risk(
    element: int,
    forecast: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Identify premium capital whose current role is too weak for a GW1 purchase."""

    position = str(meta.get("position") or forecast.get("position") or "")
    threshold = PREMIUM_PRICE_TENTHS.get(position)
    if threshold is None:
        return None
    price = float(meta.get("market_price") or forecast.get("market_price") or 0.0)
    if price < threshold:
        return None
    minutes = expected_minutes(forecast)
    play_probability = float(forecast.get("p_play") or 0.0)
    consensus = str(forecast.get("live_participation_consensus") or "not_covered")
    reasons = []
    if minutes < MIN_EXPECTED_MINUTES:
        reasons.append("expected_minutes_below_60")
    if play_probability < MIN_PLAY_PROBABILITY:
        reasons.append("play_probability_below_85pct")
    if consensus in {"predicted_bench_consensus", "single_source_bench"}:
        reasons.append(consensus)
    if not reasons:
        return None
    return {
        "element": int(element),
        "player_name": str(meta.get("player_name") or forecast.get("player_name") or element),
        "position": position,
        "price": price / 10.0,
        "expected_minutes": minutes,
        "p_play": play_probability,
        "participation_consensus": consensus,
        "reasons": reasons,
    }


def candidate_capital_role_risks(
    candidate: dict[str, Any],
    forecasts: dict[int, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    risks = []
    for raw in candidate.get("selected") or []:
        element = int(raw)
        if element not in forecasts or element not in meta:
            continue
        risk = player_capital_role_risk(element, forecasts[element], meta[element])
        if risk is not None:
            risks.append(risk)
    return sorted(risks, key=lambda row: (-float(row["price"]), int(row["element"])))


def capital_role_risk_requires_publication_block(risk: dict[str, Any]) -> bool:
    """Separate a material role failure from a marginal capital-allocation warning.

    The premium-capital report deliberately uses a conservative 60-minute diagnostic floor.
    Applying that exact boundary as a publication veto creates a discontinuity: an otherwise
    starter-grade MID/FWD at 59.9 minutes can invalidate an entire candidate field while a player
    at 60.0 passes. Publication remains fail-closed for negative lineup evidence, sub-85% play
    probability, or minutes below the position's actionable starter floor. A premium player in
    the narrow gap between the starter floor and 60 minutes stays visible as a capital warning,
    but is compared by the simulations rather than excluded before synthesis.
    """

    consensus = str(risk.get("participation_consensus") or "not_covered")
    if consensus in {"predicted_bench_consensus", "single_source_bench"}:
        return True
    if float(risk.get("p_play") or 0.0) < MIN_PLAY_PROBABILITY:
        return True
    position = str(risk.get("position") or "")
    actionable_minutes_floor = STARTER_MINUTES.get(position, 55.0)
    return float(risk.get("expected_minutes") or 0.0) < actionable_minutes_floor


def player_action_role_risk(
    element: int,
    forecast: dict[str, Any],
    meta: dict[str, Any],
    *,
    action: str,
) -> dict[str, Any] | None:
    """Reject a player whose current role is too weak for the proposed action."""

    position = str(meta.get("position") or forecast.get("position") or "")
    minutes = expected_minutes(forecast)
    play_probability = float(forecast.get("p_play") or 0.0)
    consensus = str(forecast.get("live_participation_consensus") or "not_covered")
    reasons: list[str] = []
    if action in {"starter", "incoming"}:
        threshold = STARTER_MINUTES.get(position, 55.0)
        if minutes < threshold:
            reasons.append(f"expected_minutes_below_{threshold:g}")
        if play_probability < STARTER_MIN_PLAY_PROBABILITY:
            reasons.append("play_probability_below_85pct")
        if consensus in {"predicted_bench_consensus", "single_source_bench"}:
            reasons.append(consensus)
    elif action in {"captain", "vice_captain"}:
        # A captain needs a genuinely secure high-minute role. A vice-captain only becomes
        # active when the captain does not play, so the correct integrity requirement is a
        # starter-grade role for that position rather than a second arbitrary 60-minute cliff.
        # Expected armband value is still ranked by the lineup simulation.
        minutes_floor = (
            CAPTAIN_MIN_EXPECTED_MINUTES
            if action == "captain"
            else STARTER_MINUTES.get(position, VICE_CAPTAIN_MIN_EXPECTED_MINUTES)
        )
        if minutes < minutes_floor:
            reasons.append(
                "captain_expected_minutes_below_65"
                if action == "captain"
                else f"vice_expected_minutes_below_{minutes_floor:g}"
            )
        probability_floor = (
            CAPTAIN_MIN_PLAY_PROBABILITY if action == "captain" else STARTER_MIN_PLAY_PROBABILITY
        )
        if play_probability < probability_floor:
            reasons.append(
                "captain_play_probability_below_90pct"
                if action == "captain"
                else "vice_play_probability_below_85pct"
            )
    elif action in {"bench_1", "bench_2"}:
        if position != "GK" and minutes < ACTIVE_BENCH_MIN_EXPECTED_MINUTES:
            reasons.append("active_bench_expected_minutes_below_50")
        if position != "GK" and play_probability < ACTIVE_BENCH_MIN_PLAY_PROBABILITY:
            reasons.append("active_bench_play_probability_below_80pct")
        if position != "GK" and consensus in {
            "predicted_bench_consensus",
            "single_source_bench",
        }:
            reasons.append(consensus)
    elif action == "deep_outfield_bench":
        if minutes < DEEP_OUTFIELD_BENCH_MIN_EXPECTED_MINUTES:
            reasons.append("deep_bench_expected_minutes_below_30")
        if play_probability < DEEP_OUTFIELD_BENCH_MIN_PLAY_PROBABILITY:
            reasons.append("deep_bench_play_probability_below_50pct")
    if not reasons:
        return None
    return {
        "element": int(element),
        "player_name": str(meta.get("player_name") or forecast.get("player_name") or element),
        "position": position,
        "price": float(meta.get("market_price") or forecast.get("market_price") or 0.0) / 10.0,
        "expected_minutes": minutes,
        "p_play": play_probability,
        "participation_consensus": consensus,
        "action": action,
        "reasons": reasons,
    }


def candidate_publication_role_risks(
    candidate: dict[str, Any],
    forecasts: dict[int, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    *,
    event: int = 1,
) -> list[dict[str, Any]]:
    """Return every hard role-integrity failure in a candidate's actionable GW lineup."""

    lineup = (candidate.get("lineups") or {}).get(str(event)) or (
        candidate.get("lineups") or {}
    ).get(event)
    if not isinstance(lineup, dict):
        return [
            {
                "element": -1,
                "player_name": "candidate lineup",
                "position": "",
                "price": 0.0,
                "expected_minutes": 0.0,
                "p_play": 0.0,
                "participation_consensus": "missing",
                "action": "lineup",
                "reasons": ["actionable_lineup_missing"],
            }
        ]
    checks: list[tuple[int, str]] = [
        *((int(element), "starter") for element in lineup.get("starters") or []),
        (int(lineup.get("captain") or -1), "captain"),
        (int(lineup.get("vice_captain") or -1), "vice_captain"),
    ]
    outfield_bench_index = 0
    for raw in lineup.get("bench_order") or []:
        element = int(raw)
        position = str((meta.get(element) or {}).get("position") or "")
        if position == "GK":
            continue
        outfield_bench_index += 1
        action = (
            f"bench_{outfield_bench_index}" if outfield_bench_index <= 2 else "deep_outfield_bench"
        )
        checks.append((element, action))
    risks = []
    seen: set[tuple[int, str]] = set()
    for element, action in checks:
        if (element, action) in seen or element not in forecasts or element not in meta:
            continue
        seen.add((element, action))
        risk = player_action_role_risk(
            element,
            forecasts[element],
            meta[element],
            action=action,
        )
        if risk is not None:
            risks.append(risk)
    risks.extend(
        risk
        for risk in candidate_capital_role_risks(candidate, forecasts, meta)
        if capital_role_risk_requires_publication_block(risk)
    )
    unique: dict[tuple[int, str], dict[str, Any]] = {}
    for risk in risks:
        key = (int(risk["element"]), str(risk.get("action") or "premium_capital"))
        unique[key] = risk
    return sorted(
        unique.values(),
        key=lambda row: (
            str(row.get("action") or "premium_capital"),
            -float(row.get("price") or 0.0),
            int(row["element"]),
        ),
    )
