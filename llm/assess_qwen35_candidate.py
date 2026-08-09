from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

APP_CASES = 58
APP_NO_TOOL_CASES = 50
APP_TOOL_CASES = 8
APP_MIN_CONTRACTS = 40
APP_MIN_LIFT_OVER_BASE = 20
APP_MIN_TOOL_ROUTES = 7
LEGACY_CASES = 37
LEGACY_MIN_ROUTES = 21
LEGACY_MIN_CONTRACTS = 6
SAFETY_CASE_IDS = {
    "app-general-008",
    "app-safe-001",
    "app-safe-002",
    "app-safe-003",
    "app-safe-004",
}
REAL_SCREENSHOT_CASE_IDS = {"fpl-team-001", "fpl-team-desktop-001"}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Apply the locked FPLAgent LoRA promotion gate")
    root.add_argument("--base-app", type=Path, required=True)
    root.add_argument("--candidate-app", type=Path, required=True)
    root.add_argument("--candidate-legacy", type=Path, required=True)
    root.add_argument("--screenshot-score", type=Path, action="append", default=[])
    root.add_argument(
        "--screenshot-suite",
        type=Path,
        help="A suite result whose real_results are accepted as real screenshot scores.",
    )
    root.add_argument("--base-synthetic-suite", type=Path, required=True)
    root.add_argument("--synthetic-suite", type=Path, required=True)
    root.add_argument("--qualitative-review", type=Path, required=True)
    root.add_argument("--output", type=Path)
    return root


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _full_contract(row: dict[str, Any]) -> bool:
    return all(
        bool(row.get(field))
        for field in (
            "tool_route_exact",
            "tool_arguments_valid",
            "response_contract_pass",
            "turn_boundary_valid",
        )
    )


def assess(
    *,
    base_app: dict[str, Any],
    candidate_app: dict[str, Any],
    candidate_legacy: dict[str, Any],
    screenshot_scores: list[dict[str, Any]],
    base_synthetic_suite: dict[str, Any],
    synthetic_suite: dict[str, Any],
    qualitative_review: dict[str, Any],
) -> dict[str, Any]:
    base_summary = base_app["summary"]
    app_summary = candidate_app["summary"]
    legacy_summary = candidate_legacy["summary"]
    app_results = {str(row["case_id"]): row for row in candidate_app["results"]}
    missing_safety = SAFETY_CASE_IDS - set(app_results)
    if missing_safety:
        raise ValueError(f"candidate app evaluation is missing safety cases: {missing_safety}")

    screenshot_by_case = {str(row["case_id"]): row for row in screenshot_scores}
    missing_screenshots = REAL_SCREENSHOT_CASE_IDS - set(screenshot_by_case)
    if missing_screenshots:
        raise ValueError(f"missing real screenshot scores: {missing_screenshots}")
    real_screenshot_pass = all(
        bool(screenshot_by_case[case_id].get(field))
        for case_id in REAL_SCREENSHOT_CASE_IDS
        for field in ("core_team_exact", "team_valid", "chips_exact")
    )
    base_synthetic_summary = base_synthetic_suite.get("summary", {})
    synthetic_summary = synthetic_suite.get("summary", {})
    synthetic_cases = int(synthetic_summary.get("cases", -1))
    base_synthetic_cases = int(base_synthetic_summary.get("cases", -2))
    synthetic_passes = int(synthetic_summary.get("case_passes", -1))
    base_synthetic_passes = int(base_synthetic_summary.get("case_passes", -1))
    synthetic_identity_matches = (
        synthetic_suite.get("corpus_test_sha256")
        == base_synthetic_suite.get("corpus_test_sha256")
        and synthetic_suite.get("locked_case_ids")
        == base_synthetic_suite.get("locked_case_ids")
        and synthetic_cases == base_synthetic_cases
    )
    synthetic_beats_base = (
        synthetic_passes == synthetic_cases
        and (
            base_synthetic_passes == base_synthetic_cases == synthetic_cases
            or synthetic_passes - base_synthetic_passes >= 2
        )
    )

    checks = {
        "app_benchmark_identity_matches_base": (
            app_summary.get("benchmark_sha256") == base_summary.get("benchmark_sha256")
        ),
        "app_case_count_exact": int(app_summary.get("cases", -1)) == APP_CASES,
        "app_contracts_at_least_40": (
            int(app_summary.get("all_contracts_pass", -1)) >= APP_MIN_CONTRACTS
        ),
        "app_contract_lift_at_least_20": (
            int(app_summary.get("all_contracts_pass", -1))
            - int(base_summary.get("all_contracts_pass", -1))
            >= APP_MIN_LIFT_OVER_BASE
        ),
        "all_direct_routes_tool_free": (
            int(app_summary.get("no_tool_cases", -1)) == APP_NO_TOOL_CASES
            and int(app_summary.get("no_tool_route_exact", -1)) == APP_NO_TOOL_CASES
        ),
        "at_least_7_of_8_grounded_routes": (
            int(app_summary.get("grounded_tool_cases", -1)) == APP_TOOL_CASES
            and int(app_summary.get("grounded_tool_route_exact", -1)) >= APP_MIN_TOOL_ROUTES
        ),
        "all_app_arguments_valid": (
            int(app_summary.get("tool_arguments_valid", -1)) == APP_CASES
        ),
        "all_app_boundaries_clean": (
            int(app_summary.get("turn_boundary_valid", -1)) == APP_CASES
        ),
        "all_locked_safety_contracts_pass": all(
            _full_contract(app_results[case_id]) for case_id in SAFETY_CASE_IDS
        ),
        "legacy_case_count_exact": int(legacy_summary.get("cases", -1)) == LEGACY_CASES,
        "legacy_routing_at_least_v3": (
            int(legacy_summary.get("tool_route_exact", -1)) >= LEGACY_MIN_ROUTES
        ),
        "legacy_contracts_no_worse_than_base_v3": (
            int(legacy_summary.get("all_contracts_pass", -1)) >= LEGACY_MIN_CONTRACTS
        ),
        "real_screenshots_exact_and_valid": real_screenshot_pass,
        "synthetic_suite_identity_matches_base": synthetic_identity_matches,
        "held_out_synthetic_suite_passes": (
            bool(synthetic_suite.get("passed", False)) and synthetic_beats_base
        ),
        "qualitative_ab_review_passes": bool(qualitative_review.get("passed", False)),
    }
    passed = all(checks.values())
    return {
        "gate_version": "fplagent-lora-promotion-v2",
        "verdict": "PROMOTE" if passed else "REJECT",
        "passed": passed,
        "checks": checks,
        "metrics": {
            "base_app_contracts": int(base_summary["all_contracts_pass"]),
            "candidate_app_contracts": int(app_summary["all_contracts_pass"]),
            "candidate_app_route_exact": int(app_summary["tool_route_exact"]),
            "candidate_app_no_tool_route_exact": int(app_summary["no_tool_route_exact"]),
            "candidate_app_grounded_route_exact": int(
                app_summary["grounded_tool_route_exact"]
            ),
            "candidate_legacy_contracts": int(legacy_summary["all_contracts_pass"]),
            "candidate_legacy_route_exact": int(legacy_summary["tool_route_exact"]),
            "base_synthetic_passes": base_synthetic_passes,
            "synthetic_suite": synthetic_suite.get("summary", {}),
        },
    }


def main() -> None:
    args = parser().parse_args()
    screenshot_scores = [_load(path) for path in args.screenshot_score]
    if args.screenshot_suite:
        suite_payload = _load(args.screenshot_suite)
        suite_real_results = suite_payload.get("real_results", [])
        if not isinstance(suite_real_results, list):
            raise TypeError("screenshot suite real_results must be a list")
        screenshot_scores.extend(suite_real_results)
    payload = assess(
        base_app=_load(args.base_app),
        candidate_app=_load(args.candidate_app),
        candidate_legacy=_load(args.candidate_legacy),
        screenshot_scores=screenshot_scores,
        base_synthetic_suite=_load(args.base_synthetic_suite),
        synthetic_suite=_load(args.synthetic_suite),
        qualitative_review=_load(args.qualitative_review),
    )
    payload["artifacts"] = {
        name: {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in {
            "base_app": args.base_app,
            "candidate_app": args.candidate_app,
            "candidate_legacy": args.candidate_legacy,
            "base_synthetic_suite": args.base_synthetic_suite,
            "synthetic_suite": args.synthetic_suite,
            "qualitative_review": args.qualitative_review,
            **(
                {"screenshot_suite": args.screenshot_suite}
                if args.screenshot_suite is not None
                else {}
            ),
        }.items()
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
