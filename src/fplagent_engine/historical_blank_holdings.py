"""Explicitly reconstruct absent held-player forecasts; certify blank labels separately.

Some legacy training tables omit player-events with no match. A carried holding
must not disappear from a policy replay. Forecasts below are labelled prior-rate
reconstructions, not original OOF predictions. Final fixture data supplies ONLY
the scoring label and cannot influence forecast values, prices or availability.
"""

from datetime import datetime

from .horizon_decay_replay import _fixture_multiplier, _prior_neutral_rate, _schedule_at_origin


def complete_blank_holdings(
    state, rows, outcomes, inputs, coefficients, *, catalog_rows, final_fixtures
):
    event, season = state.event, state.season
    current = {int(r["element"]) for r in rows if r["event_number"] == event}
    missing = [h for h in state.squad if h.player_id not in current]
    if not missing:
        return rows, outcomes, []
    rows, outcomes = list(rows), list(outcomes)
    schedule, snapshot_event = _schedule_at_origin(
        season=season,
        origin_event=event,
        fixture_by_snapshot=inputs["fixture_by_snapshot"],
        available_snapshots=inputs["available_snapshots"],
    )
    events = sorted({r["event_number"] for r in rows})
    repairs = []
    for holding in missing:
        eligible = [
            r
            for r in catalog_rows
            if str(r["season"]) == season
            and int(r["id"]) == holding.player_id
            and r.get("decision_event") is not None
            and int(r["decision_event"]) <= event
        ]
        if not eligible:
            raise ValueError(f"No as-of catalog for missing holding {holding.player_id}")
        snapshot = max(eligible, key=lambda r: (int(r["decision_event"]), str(r["observed_at"])))
        observed = datetime.fromisoformat(str(snapshot["observed_at"]))
        deadline = snapshot["deadline_at"]
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
        if observed.tzinfo is None or deadline.tzinfo is None or observed > deadline:
            raise ValueError("Catalog row was observed after its declared deadline")
        prior = [
            r
            for (s, e), rs in inputs["forecast_by_event"].items()
            if s == season and e < event
            for r in rs
            if int(r["element"]) == holding.player_id
        ]
        if not prior:
            raise ValueError("Missing holding has no earlier forecast; do not invent a skill rate")
        base = max(prior, key=lambda r: int(r["event_number"]))
        team = int(snapshot["team"])
        neutral = _prior_neutral_rate(
            season=season,
            element=holding.player_id,
            origin_event=event,
            position=holding.position,
            forecast_by_event=inputs["forecast_by_event"],
            feature_by_key=inputs["feature_by_key"],
            coefficients=coefficients,
        )
        for future in events:
            context = schedule.get(
                (future, team),
                {"fixture_count": 0.0, "home_fraction": 0.0, "fixture_difficulty": 3.0},
            )
            xp = neutral * _fixture_multiplier(
                holding.position,
                context["fixture_count"],
                context["home_fraction"],
                context["fixture_difficulty"],
                coefficients,
            )
            rows.append(
                {
                    **{k: v for k, v in base.items() if not k.startswith(("target_", "realized_"))},
                    "event_number": future,
                    "market_price": int(snapshot["now_cost"]),
                    "team_id": team,
                    "expected_points": xp,
                    "robust_points": xp,
                    "p_play": float(base["p_play"]) if context["fixture_count"] else 0.0,
                    **context,
                    "can_select": snapshot.get("can_select") is not False,
                    "removed": bool(snapshot.get("removed")),
                    "forecast_origin_event": event,
                    "forecast_lead": future - event,
                    "fixture_snapshot_event": snapshot_event,
                    "forecast_reconstruction": "prior_neutral_rate_with_asof_schedule",
                }
            )
        # This independent label certificate is intentionally AFTER constructing
        # the forecasts. Never infer a blank simply from an absent player row.
        completed = [f for f in final_fixtures if str(f["season"]) == season]
        teams = {int(f[k]) for f in completed for k in ("team_h", "team_a")}
        if (
            len(completed) != 380
            or len({f["id"] for f in completed}) != 380
            or len(teams) != 20
            or not all(f["finished"] for f in completed)
        ):
            raise ValueError("Blank labels require a complete final 380-match season certificate")
        if team not in teams or any(
            f.get("event") == event and team in (int(f["team_h"]), int(f["team_a"]))
            for f in completed
        ):
            raise ValueError("Missing player outcome is not a certified team blank")
        outcomes.append(
            {
                "element": holding.player_id,
                "position": holding.position,
                "target_points": 0,
                "target_minutes": 0.0,
                "outcome_source": "complete_final_fixture_grid_confirmed_blank",
            }
        )
        repairs.append(
            {
                "player_id": holding.player_id,
                "event": event,
                "catalog_snapshot_event": int(snapshot["decision_event"]),
                "catalog_age_events": event - int(snapshot["decision_event"]),
                "current_event_catalog_available": int(snapshot["decision_event"]) == event,
                "catalog_sha": snapshot["snapshot_sha"],
                "prior_forecast_event": int(base["event_number"]),
                "forecast_method": "prior_neutral_rate_with_asof_schedule",
                "actual_blank_certified": True,
            }
        )
    return rows, outcomes, repairs
