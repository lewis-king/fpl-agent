"""Explicit, code-reviewed deployment decisions for the points-first release.

This is not a knob that lets an experiment grant itself authority. Rejected
versions may continue collecting frozen measurements; activating a replacement
requires a new implementation/review. Existing forecast and chip gates remain
in force. The engine implementation fingerprint includes this module.
"""

from __future__ import annotations

from copy import deepcopy

VERSION = "points_first_release_20261021_v5"
REPORT = "reports/scout-product-audit-and-gw7-review-2026-10-21.md"

DECISIONS = (
    {
        "key": "round_availability_integrity",
        "decision": "promote",
        "basis": "dated_input_and_zero_value_correctness",
        "reason": "Use next-round official availability for the actionable deadline, not hardcoded preseason events or previous-round probability. Enforce official zero independently of lineup feeds; preserve zero component role ratios and block contradictory publication.",
        "evidence": "Fresh GW8 comparison found 18 officially unavailable players with nonzero forecasts; rebuilt direct/component forecasts have zero such violations. Returning players are no longer excluded by last-round flags. See reports/forecast-diagnosis-and-corrections-2026-10-21.md.",
        "scope": "General live-input correction, not a points-uplift or calibrated return-date claim. No Scout training data, changed optimizer risk weights or new chip policy.",
    },
    {
        "key": "availability_training_refit",
        "decision": "reject",
        "basis": "retain_current_learned_weights_pending_stronger_evidence",
        "reason": "Paired chronological input-refit replay scored 0/0/+30 points across 2023/24–2025/26; only the latest fold materially exercised the feature. Latest-season block interval includes zero and aggregate MAE did not improve.",
        "scope": "Promising research, not evidence no improvement is possible. Corrected live-round handling is released independently. Historical field rollover and quote coverage remain proxy limitations.",
    },
    {
        "key": "gate_search_policy",
        "decision": "reject",
        "basis": "failed_preregistered_two_fold_screen",
        "reason": "Gate/search factorial: wider incumbent +26/-5, narrow mean-points +12/-3, wider mean-points +12/-21 in 2024/25 and 2025/26 GW1-10. Removing only the configuration world veto scored 0/0. Do not deploy these replacements on this evidence.",
        "scope": "Bounded development folds, not proof the incumbent is optimal. Live search was already broader than the narrow historical control. Keep the improved replay coverage and independent ledger audit.",
    },
    {
        "key": "scout_private_benchmark",
        "decision": "reject",
        "basis": "external_measurement_not_forecast_authority",
        "reason": "Enable private authorized captures and finalized-outcome scoring, not automatic use of Scout forecasts in decisions. No matched prospective lift has been established.",
        "scope": "Reject decision/training authority only. Timestamp/identity/missingness checks, private bounded storage and optional weekly capture are active engineering improvements.",
    },
    {
        "key": "configuration_optimisation",
        "decision": "promote",
        "basis": "scoring_objective_consistency_with_independent_validation",
        "reason": "Search XI, bench and C/VC in the same simulated worlds used to compare roster routes, including exact BB/TC and FH restoration.",
        "evidence": "CPU/CUDA exhaustive scoring parity, legal state/receipt regressions, and an untouched per-run paired validation gate on the frozen selected configuration.",
        "scope": "No wider-roster research, forecast or weight promotion. Failed validation retains the entire original selection. No historical or prospective points uplift claimed.",
    },
    {
        "key": "admissible_selection",
        "decision": "promote",
        "basis": "correctness",
        "reason": "Test all routes; rejected routes cannot set the risk reference for playable routes.",
        "evidence": "Fail-before/pass-after invariance regression; frozen GW2/GW3 selector outcomes remain 133 points; saved GW4 move unchanged.",
        "scope": "Safety gates and the 0.25 risk coefficient are unchanged; no measured points uplift claimed.",
    },
    {
        "key": "held_club_overflow",
        "decision": "promote",
        "basis": "rule_correctness",
        "reason": "Accept authenticated existing club overflow, require repair on a fantasy transfer, restore it after Free Hit.",
        "evidence": "Rule regressions and 76 historical events / 16 chip uses; no relaxation for a newly built squad.",
    },
    {
        "key": "bench_boost_triple_captain",
        "decision": "promote",
        "basis": "retain_validated_policy",
        "reason": "Keep the existing expanding-window calibrated policy eligible, subject to its live per-chip gates.",
        "evidence": "chip_strategy_v2: forward actual uplifts 34/17 versus forecast-selected comparators 17/21; existing historical screen passed.",
        "scope": "Does not grant authority to the older team_chip_replay_v1 or claim optimal eight-chip season timing.",
    },
    {
        "key": "chip_calendar_constraints",
        "decision": "promote",
        "basis": "rule_and_opportunity_accounting_correctness",
        "reason": "A chip cannot retain value after its half expires, and remaining unseen deadlines cannot accommodate more than one chip each.",
        "evidence": "Fail-before/pass-after GW19/GW38 boundary and poisoned-post-expiry regressions; capacity-aware calendar equals exhaustive small-state enumeration.",
        "scope": "Applies to retain and forced-current-chip calendars. Does not refit thresholds, grant WC/FH timing authority, or claim measured points uplift.",
    },
    {
        "key": "exact_chip_opportunities",
        "decision": "reject",
        "basis": "matching_timing_calibration_required",
        "reason": "Exact shared-path BB/TC measurement is captured automatically, but swapping it into a proxy-trained retained-value policy requires a matched refit and chronological timing replay.",
        "scope": "Keep diagnostic collection. BB excludes points already received through autosubs; TC includes vice fallback. Neither a simulated uplift nor calendar sensitivity is a new chip recommendation.",
    },
    {
        "key": "prospective_full_pool",
        "decision": "promote",
        "basis": "measurement_correctness",
        "reason": "Freeze all current forecasts and rejected alternatives, then score checked outcomes without inventing missing zeros.",
        "evidence": "Full-pool, legal autosub/captain/hit, missingness and backward-compatible receipt regressions.",
    },
    {
        "key": "transfer_continuation",
        "decision": "reject",
        "basis": "failed_historical_screen",
        "reason": "The deterministic continuation variant gained 58 points in 2024/25 but lost 2 in 2025/26, failing its predeclared positive-both-folds screen.",
        "scope": "Opening ten events, zero-terminal-FT ablation; not a claim that all adaptive planning is ineffective.",
    },
    {
        "key": "stateful_policy_research",
        "decision": "reject",
        "basis": "failed_historical_screen",
        "reason": "Guarded future-hold v2 gained 36 net points in 2024/25 but lost 1 in 2025/26 in the completed three-world GW1-10 replay. It fails the predeclared positive-both-folds screen; the residual-only ablation was +37/-8.",
        "scope": "Separate carried-forward rosters, costs and FTs; bounded future-child search, no chip timing or future news oracle. Historical architecture test, not a complete production replication or pristine holdout.",
    },
    {
        "key": "joint_wildcard_free_hit",
        "decision": "reject",
        "basis": "mechanics_do_not_validate_timing",
        "reason": "The 76-event calendar audit proves state/scoring transitions, not when to spend WC/FH; remaining chip inventory is not validated against a matched control.",
        "scope": "Reject new timing authority, not the legal chip mechanics or existing BB/TC policy.",
    },
    {
        "key": "role_shift_research",
        "decision": "reject",
        "basis": "failed_historical_screen",
        "reason": "83,243 player-events: latest decision-focus log loss 0.300656 versus champion 0.300581 fails the fixed screen despite a small Brier improvement.",
        "scope": "No post-hoc threshold relaxation; current minutes/appearance forecasts are unchanged.",
    },
    {
        "key": "allocation_research",
        "decision": "reject",
        "basis": "no_demonstrated_net_points_lift",
        "reason": "Protected premium-sale/reinvestment search changed neither season's total in the three-world replay (0/0). The saved-GW7 nine-family challenger gained only 0.03334 simulated points with an independent MC95 lower bound of -0.00240.",
        "scope": "Do not impose a bench-spend preference or promote the expanded pool. Keep automatic legal one/two-transfer capital-release proposals and frozen outcome capture; neither test proves the larger live search policy superior.",
    },
    {
        "key": "risk_weight_retuning",
        "decision": "reject",
        "basis": "no_evidence_for_replacement",
        "reason": "Applying each coefficient consistently to configurations and routes, 0/0.10/0.50 scored -15/-15/-9 against 0.25 in 2024/25 and -1/-5/0 in 2025/26. None passes the predeclared two-fold screen.",
        "scope": "Retain 0.25, not a claim of season-optimality. Controls use three prefix-fitted worlds and nonzero prior-season FT values; bounded archives do not replicate all live evidence.",
    },
    {
        "key": "score_shape_policy",
        "decision": "reject",
        "basis": "failed_historical_screen",
        "reason": "Residual score-shape remapping gained 21 net points in 2024/25 and 0 in 2025/26, failing positive lift in both folds. Better average marginal calibration alone does not establish better captain/bench decisions.",
        "scope": "Reject the new simulation-shape policy, not existing calibrated marginal-PMF reporting. Appearance paths and component worlds are unchanged; no joint-tail or DGW-calibration claim.",
    },
)


def attach_policy_release(result: dict) -> None:
    """Annotate every receipt and fail closed on accidental research authority.

    Existing chip/forecast validators still make their own event-level decisions.
    Measurement status (ready/incomplete) is separate from deployment status.
    """
    diagnostics = result.get("diagnostics", {})
    for decision in DECISIONS:
        if decision["decision"] != "reject":
            continue
        diagnostic = diagnostics.get(decision["key"])
        if diagnostic is None:
            continue
        if diagnostic.get("decision_authority") is not False:
            raise ValueError(f"Rejected experiment {decision['key']} cannot acquire decision authority")
        diagnostic["deployment_review"] = {
            "release": VERSION,
            "decision": "reject",
            "reason": decision["reason"],
            "capture_policy": "measurement_only; no automatic promotion",
        }
    strategy = result.get("chip_strategy", {})
    chip = strategy.get("operational_recommendation")
    if chip in {"wildcard", "free_hit"}:
        timing = (strategy.get("squad_timing") or {}).get("verdict") or {}
        authorised = bool(strategy.get("expiry_forced")) or (
            timing.get("play_now") is True if chip == "wildcard"
            else (strategy.get("policy") or {}).get("free_hit_timing")
            == "joint calendar and uncertainty gates"
        )
        if not authorised:
            raise ValueError(
                f"{chip} was recommended without live timing or expiry authority"
            )
    result["policy_release"] = {
        "version": VERSION,
        "report": REPORT,
        "decisions": deepcopy(list(DECISIONS)),
        "automatic_promotion": False,
        "interpretation": "Deployment decisions for these versions are concluded, not pending. Measurement capture is not decision authority.",
    }
