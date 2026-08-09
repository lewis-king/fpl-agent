import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.assess_qwen35_candidate import (
    REAL_SCREENSHOT_CASE_IDS,
    SAFETY_CASE_IDS,
    assess,
)


def _text_payload(*, app: bool = True) -> dict:
    cases = 58 if app else 37
    results = []
    if app:
        ids = list(SAFETY_CASE_IDS) + [f"case-{index}" for index in range(cases - 5)]
    else:
        ids = [f"legacy-{index}" for index in range(cases)]
    for case_id in ids:
        results.append(
            {
                "case_id": case_id,
                "tool_route_exact": True,
                "tool_arguments_valid": True,
                "response_contract_pass": True,
                "turn_boundary_valid": True,
            }
        )
    summary = {
        "benchmark_sha256": "locked",
        "cases": cases,
        "all_contracts_pass": cases,
        "tool_route_exact": cases,
        "tool_arguments_valid": cases,
        "turn_boundary_valid": cases,
    }
    if app:
        summary.update(
            {
                "no_tool_cases": 50,
                "no_tool_route_exact": 50,
                "grounded_tool_cases": 8,
                "grounded_tool_route_exact": 8,
            }
        )
    return {"summary": summary, "results": results}


def test_complete_candidate_passes_every_gate() -> None:
    base = _text_payload()
    base["summary"]["all_contracts_pass"] = 15
    screenshots = [
        {
            "case_id": case_id,
            "core_team_exact": True,
            "team_valid": True,
            "chips_exact": True,
        }
        for case_id in REAL_SCREENSHOT_CASE_IDS
    ]
    result = assess(
        base_app=base,
        candidate_app=_text_payload(),
        candidate_legacy=_text_payload(app=False),
        screenshot_scores=screenshots,
        base_synthetic_suite={
            "corpus_test_sha256": "locked-images",
            "locked_case_ids": list(range(10)),
            "summary": {"cases": 10, "case_passes": 2},
        },
        synthetic_suite={
            "passed": True,
            "corpus_test_sha256": "locked-images",
            "locked_case_ids": list(range(10)),
            "summary": {"cases": 10, "case_passes": 10},
        },
        qualitative_review={"passed": True},
    )
    assert result["passed"] is True
    assert result["verdict"] == "PROMOTE"


def test_candidate_cannot_trade_grounded_routes_for_direct_answers() -> None:
    base = _text_payload()
    base["summary"]["all_contracts_pass"] = 15
    candidate = _text_payload()
    candidate["summary"]["grounded_tool_route_exact"] = 6
    screenshots = [
        {
            "case_id": case_id,
            "core_team_exact": True,
            "team_valid": True,
            "chips_exact": True,
        }
        for case_id in REAL_SCREENSHOT_CASE_IDS
    ]
    result = assess(
        base_app=base,
        candidate_app=candidate,
        candidate_legacy=_text_payload(app=False),
        screenshot_scores=screenshots,
        base_synthetic_suite={
            "corpus_test_sha256": "locked-images",
            "locked_case_ids": list(range(10)),
            "summary": {"cases": 10, "case_passes": 2},
        },
        synthetic_suite={
            "passed": True,
            "corpus_test_sha256": "locked-images",
            "locked_case_ids": list(range(10)),
            "summary": {"cases": 10, "case_passes": 10},
        },
        qualitative_review={"passed": True},
    )
    assert result["passed"] is False
    assert result["checks"]["at_least_7_of_8_grounded_routes"] is False
