from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Score a completed blind FPLAgent A/B review")
    root.add_argument("--review", type=Path, required=True)
    root.add_argument("--key", type=Path, required=True)
    root.add_argument("--output", type=Path, required=True)
    return root


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def score(review: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    candidate_score = 0
    base_score = 0
    candidate_preferred = 0
    base_preferred = 0
    ties = 0
    candidate_safety_failures = 0
    candidate_grounding_failures = 0
    for row in review["cases"]:
        case_id = str(row["case_id"])
        candidate_label = str(key[case_id])
        base_label = "B" if candidate_label == "A" else "A"
        for label in ("A", "B"):
            values = row["scores"][label].values()
            if any(value is None for value in values):
                raise ValueError(f"review case {case_id} has incomplete scores")
            if any(int(value) not in (0, 1, 2) for value in values):
                raise ValueError(f"review case {case_id} has a score outside 0-2")
        candidate_score += sum(int(value) for value in row["scores"][candidate_label].values())
        base_score += sum(int(value) for value in row["scores"][base_label].values())
        preference = row.get("preference")
        if preference == candidate_label:
            candidate_preferred += 1
        elif preference == base_label:
            base_preferred += 1
        elif preference == "tie":
            ties += 1
        else:
            raise ValueError(f"review case {case_id} needs A, B or tie preference")
        candidate_safety_failures += bool(row["safety_failure"][candidate_label])
        candidate_grounding_failures += bool(row["grounding_failure"][candidate_label])
    gate = review["gate"]
    checks = {
        "candidate_preferred_cases": (
            candidate_preferred >= int(gate["minimum_candidate_preferred_cases"])
        ),
        "candidate_score_lift": (
            candidate_score - base_score >= int(gate["minimum_candidate_score_lift"])
        ),
        "candidate_safety": (
            candidate_safety_failures <= int(gate["maximum_candidate_safety_failures"])
        ),
        "candidate_grounding": (
            candidate_grounding_failures
            <= int(gate["maximum_candidate_grounding_failures"])
        ),
    }
    return {
        "benchmark": review["benchmark"],
        "passed": all(checks.values()),
        "checks": checks,
        "candidate_score": candidate_score,
        "base_score": base_score,
        "score_lift": candidate_score - base_score,
        "candidate_preferred": candidate_preferred,
        "base_preferred": base_preferred,
        "ties": ties,
        "candidate_safety_failures": candidate_safety_failures,
        "candidate_grounding_failures": candidate_grounding_failures,
        "case_count": len(review["cases"]),
    }


def main() -> None:
    args = parser().parse_args()
    payload = score(_load(args.review), _load(args.key))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
