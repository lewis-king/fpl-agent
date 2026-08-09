from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Prepare a deterministic blind FPLAgent A/B review")
    root.add_argument("--base", type=Path, required=True)
    root.add_argument("--candidate", type=Path, required=True)
    root.add_argument(
        "--rubric",
        type=Path,
        default=Path("config/llm/benchmarks/qualitative_ab_v1.json"),
    )
    root.add_argument("--output", type=Path, required=True)
    root.add_argument("--key-output", type=Path, required=True)
    return root


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise TypeError("evaluation payload is missing results")
    return {str(row["case_id"]): row for row in rows}


def prepare(
    *,
    base: dict[str, Any],
    candidate: dict[str, Any],
    rubric: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    base_rows = _results(base)
    candidate_rows = _results(candidate)
    cases = []
    key = {}
    dimensions = list(rubric["dimensions"])
    for case_id in rubric["case_ids"]:
        if case_id not in base_rows or case_id not in candidate_rows:
            raise ValueError(f"missing qualitative case {case_id}")
        base_response = str(base_rows[case_id].get("final_response", ""))
        candidate_response = str(candidate_rows[case_id].get("final_response", ""))
        candidate_is_a = int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 2 == 0
        key[case_id] = "A" if candidate_is_a else "B"
        responses = (
            {"A": candidate_response, "B": base_response}
            if candidate_is_a
            else {"A": base_response, "B": candidate_response}
        )
        cases.append(
            {
                "case_id": case_id,
                "prompt": str(candidate_rows[case_id].get("prompt", "")),
                "responses": responses,
                "scores": {
                    label: {dimension: None for dimension in dimensions}
                    for label in ("A", "B")
                },
                "preference": None,
                "safety_failure": {"A": False, "B": False},
                "grounding_failure": {"A": False, "B": False},
                "notes": "",
            }
        )
    review = {
        "benchmark": rubric["benchmark"],
        "instructions": rubric["instructions"],
        "dimensions": rubric["dimensions"],
        "gate": rubric["gate"],
        "cases": cases,
    }
    return review, key


def main() -> None:
    args = parser().parse_args()
    review, key = prepare(
        base=_load(args.base),
        candidate=_load(args.candidate),
        rubric=_load(args.rubric),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.key_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(review, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.key_output.write_text(
        json.dumps(key, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"cases": len(review["cases"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
