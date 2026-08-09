import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.prepare_qualitative_ab import prepare
from llm.score_qualitative_ab import score


def _evaluation(case_ids: list[str], prefix: str) -> dict:
    return {
        "results": [
            {"case_id": case_id, "prompt": f"Prompt {case_id}", "final_response": prefix}
            for case_id in case_ids
        ]
    }


def test_blind_review_requires_a_material_candidate_win() -> None:
    case_ids = [f"case-{index}" for index in range(14)]
    rubric = {
        "benchmark": "test",
        "case_ids": case_ids,
        "dimensions": {f"dimension-{index}": "rubric" for index in range(4)},
        "gate": {
            "minimum_candidate_preferred_cases": 10,
            "minimum_candidate_score_lift": 8,
            "maximum_candidate_safety_failures": 0,
            "maximum_candidate_grounding_failures": 0,
        },
        "instructions": "blind",
    }
    review, key = prepare(
        base=_evaluation(case_ids, "base"),
        candidate=_evaluation(case_ids, "candidate"),
        rubric=rubric,
    )
    for row in review["cases"]:
        candidate_label = key[row["case_id"]]
        base_label = "B" if candidate_label == "A" else "A"
        row["scores"][candidate_label] = {dimension: 2 for dimension in rubric["dimensions"]}
        row["scores"][base_label] = {dimension: 1 for dimension in rubric["dimensions"]}
        row["preference"] = candidate_label
    result = score(review, key)
    assert result["passed"] is True
    assert result["candidate_preferred"] == 14
    assert result["score_lift"] == 56
