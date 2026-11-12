"""Matched outcome evidence for policies frozen before their real deadlines.

No hindsight selection, recomputed roles or pretend continuous counterfactual
season. One-step policy comparisons share the same manager state at each event.
"""

from __future__ import annotations

WEIGHTS = (0.0, 0.1, 0.25, 0.5)


def summarize_policy_evidence(scores: list[dict]) -> dict:
    events = [int(s["event"]) for s in scores if "event" in s]
    if len(events) != len(set(events)):
        raise ValueError("Only one pre-deadline decision may be scored per event")
    risk, continuation, missing = [], [], []
    for score in sorted(scores, key=lambda s: s.get("event", -1)):
        if "event" not in score:
            continue
        event = int(score["event"])
        comparisons = (score.get("allocation_scores") or {}).get("comparisons", [])
        by_weight = {}
        for row in comparisons:
            if row.get("pool") != "original" or row.get("status") != "scored_shadow":
                continue
            weight = float(row["worst_case_weight"])
            if weight in by_weight:
                raise ValueError("Duplicate risk-weight observation")
            by_weight[weight] = row
        # All alternatives must use identical events, not whichever weeks happen
        # to make an arm look good. Original and expanded search are not pooled.
        if all(w in by_weight for w in WEIGHTS):
            base = by_weight[0.25]
            risk.append({
                "event": event,
                "baseline_action_id": base["action_id"],
                "net_points": {str(w): by_weight[w]["realized_net_points"] for w in WEIGHTS},
                "delta_to_025": {
                    str(w): by_weight[w]["realized_net_points"] - base["realized_net_points"]
                    for w in WEIGHTS
                },
                "changed_action": {
                    str(w): by_weight[w]["action_id"] != base["action_id"] for w in WEIGHTS
                },
            })
        else:
            missing.append({"event": event, "comparison": "matched_risk_grid"})
        for key in ("next_deadline_recourse", "shared_world_continuation"):
            row = (score.get("challenger_policy_scores") or {}).get(key, {})
            if row.get("status") == "scored_shadow":
                continuation.append({"event": event, "policy": key,
                                     "delta": row["realized_delta_to_champion"],
                                     "action_id": row["action_id"]})
            else:
                missing.append({"event": event, "comparison": key})
    return {
        "version": "frozen_policy_evidence_v1",
        "decision_authority": False,
        "risk": {
            "matched_events": [r["event"] for r in risk],
            "comparisons": risk,
            "total_paired_delta": {
                str(w): sum(r["delta_to_025"][str(w)] for r in risk) for w in WEIGHTS
            },
            "changed_actions": {
                str(w): sum(r["changed_action"][str(w)] for r in risk) for w in WEIGHTS
            },
        },
        "continuation": {
            key: {"events": [r["event"] for r in continuation if r["policy"] == key],
                  "total_paired_delta": sum(r["delta"] for r in continuation if r["policy"] == key),
                  "comparisons": [r for r in continuation if r["policy"] == key]}
            for key in ("next_deadline_recourse", "shared_world_continuation")
        },
        "missing": missing,
        "promotion": "retain_current_policy",
        "limitations": [
            "Paired first-action outcomes, not a carried-forward counterfactual season.",
            "Original fixed candidate/configuration pool; does not tune the configuration objective.",
            "Few dependent events and multiple hypotheses cannot establish a better risk coefficient.",
            "Future chip timing and future-transfer outcomes are not validated by first-action scores.",
        ],
    }
