from __future__ import annotations

import json
import re
from typing import Any

TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=([^>]+)>(.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
PARAMETER_RE = re.compile(
    r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>",
    re.DOTALL,
)


def _decode_parameter(value: str) -> Any:
    stripped = value.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return stripped


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, match in enumerate(TOOL_CALL_RE.finditer(text)):
        arguments = {
            key.strip(): _decode_parameter(value)
            for key, value in PARAMETER_RE.findall(match.group(2))
        }
        calls.append(
            {
                "id": f"eval_call_{index}",
                "type": "function",
                "function": {
                    "name": match.group(1).strip(),
                    "arguments": arguments,
                },
            }
        )
    return calls


def first_generated_turn(raw: str) -> tuple[str, bool]:
    """Isolate one assistant turn and report role-boundary leakage."""
    boundary = re.search(r"\n(?:user|assistant)\n", raw)
    if boundary is None:
        return raw.strip(), True
    return raw[: boundary.start()].strip(), False


def score_result(
    case: Any,
    observed_tools: list[str],
    final_response: str,
    schema_valid: bool,
) -> dict[str, Any]:
    folded = final_response.casefold()
    missing = [item for item in case.response_must_contain if item.casefold() not in folded]
    forbidden = [item for item in case.response_must_not_contain if item.casefold() in folded]
    return {
        "tool_route_exact": observed_tools == list(case.expected_tools),
        "tool_arguments_valid": schema_valid,
        "missing_required_phrases": missing,
        "present_forbidden_phrases": forbidden,
        "response_contract_pass": not missing and not forbidden,
    }
