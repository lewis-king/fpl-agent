"""Exact shared-path BB/TC opportunity measurement; no new timing authority.

The deployed retained-chip model was fitted with forecast proxies. Replacing its
inputs without refitting that model would silently change the timing policy.
This audit freezes the exact opportunities and the discrepancy automatically.
"""

from __future__ import annotations

import numpy as np

from .chip_strategy import (
    _available_chips,
    _event_team_chip_uplifts,
    _lookup_retained,
    _optimise_calendar,
)
from .exact_configuration import fused_score_candidates
from .weekly_simulation import _candidate_payload


def exact_opportunities(action, worlds, weights, events):
    if (set(worlds) != set(weights) or set(weights) != {"residual", "component_anchored", "component_raw"}
            or not np.isclose(sum(weights.values()), 1)
            or any(not np.isfinite(w) or w < 0 for w in weights.values())):
        raise ValueError("Chip opportunity worlds/weights must match")
    if action.action.chip is not None or action.planned_chips:
        raise ValueError("Opportunity comparator must be an ordinary, unchipped route")
    if tuple(r.event for r in action.lineups) != events:
        raise ValueError("Chip opportunity horizon mismatch")
    draws = {}
    for name, world in worlds.items():
        points, played = world["points"], world["played"]
        if (points.shape != played.shape or points.shape[1:] != (len(events), len(world["player_ids"]))
                or len(points) < 2 or not np.isfinite(points).all()):
            raise ValueError("Invalid chip opportunity paths")
        if np.any(points[~played] != 0):
            raise ValueError("Nonappearance paths must score zero")
        normal = fused_score_candidates([_candidate_payload(action)], world["player_ids"],
                                         events, points, played, world["player_meta"])[:, 0, :]
        index = {p: i for i, p in enumerate(world["player_ids"])}
        values = {}
        for e, event in enumerate(events):
            lineup = action.lineups[e].lineup
            captain, vice = index[lineup.captain], index[lineup.vice_captain]
            fallback = np.where(played[:, e, captain], points[:, e, captain],
                                np.where(played[:, e, vice], points[:, e, vice], 0)).astype(float)
            squad = dict(action.event_squads).get(event, action.selected_player_ids)
            # BB adds the players who otherwise did not score, not a fixed
            # percentage of the named bench. Normal scoring already autosubs.
            boost = points[:, e, [index[p] for p in squad]].sum(axis=1) + fallback - normal[:, e]
            values[(event, "bench_boost")] = boost
            values[(event, "triple_captain")] = fallback
        draws[name] = values
    output = []
    for key in next(iter(draws.values())):
        means = {n: float(v[key].mean()) for n, v in draws.items()}
        # Raw and anchored are paired, not independent uncertainty samples.
        residual = weights["residual"] * draws["residual"][key]
        components = (weights["component_anchored"] * draws["component_anchored"][key]
                      + weights["component_raw"] * draws["component_raw"][key])
        se = float(np.sqrt(residual.var(ddof=1) / len(residual)
                           + components.var(ddof=1) / len(components)))
        output.append({"event": key[0], "chip": key[1],
                       "projected_uplift": sum(weights[n] * v for n, v in means.items()),
                       "world_means": means, "sampling_standard_error": se,
                       "source": "exact shared-path autosubs and captain/vice fallback",
                       "uncertainty_scope": "Monte Carlo integration only, not forecast confidence"})
    return output


def audit_chip_opportunities(state, action, rows, worlds, weights, events, calibration):
    exact = exact_opportunities(action, worlds, weights, events)
    proxy = _event_team_chip_uplifts(action, rows)
    by_key = {(r["event"], r["chip"]): r for r in proxy}
    comparisons = [{**r, "forecast_proxy": by_key[(r["event"], r["chip"])]["projected_uplift"],
                    "delta_to_proxy": r["projected_uplift"] - by_key[(r["event"], r["chip"])]["projected_uplift"]}
                   for r in exact]
    end = 19 if state.event <= 19 else 38
    available = [c for c in _available_chips(state) if c in {"bench_boost", "triple_captain"}]
    terminal = {c: _lookup_retained(calibration["retained_value"], c, min(events[-1], end), quantile="p50")
                if events[-1] < end else 0. for c in available}
    calendars = {name: _optimise_calendar([r for r in opportunities if r["event"] <= end],
                                         available, terminal, terminal_slots=max(end - events[-1], 0))
                 for name, opportunities in (("proxy", proxy), ("exact", exact))}
    return {"version": "exact_chip_opportunity_audit_v1", "status": "ready_diagnostic",
            "decision_authority": False, "action_id": action.action_id, "opportunities": comparisons,
            "calendars": calendars, "terminal_values": terminal,
            "remaining_half_end": end, "available_team_chips": available,
            "operational_recommendation": None,
            "release_requirement": "Refit retained values using matching exact opportunity paths and pass paired chronological net-points timing replay; do not splice exact uplifts into proxy-trained thresholds.",
            "limitations": ["Calendar sensitivity only: same frozen ordinary route, no future news oracle.",
                            "WC/FH and future transfers are separately evaluated stateful branches.",
                            "A forecast-proxy difference is not observed points uplift."]}
