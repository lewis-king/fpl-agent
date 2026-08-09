from __future__ import annotations

from types import SimpleNamespace

from fplagent_llm.text_evaluation import (
    first_generated_turn,
    parse_tool_calls,
    score_result,
)


def test_parse_qwen35_tool_call() -> None:
    calls = parse_tool_calls(
        """<tool_call>
<function=get_fixture_horizon>
<parameter=team_ids>
[1]
</parameter>
<parameter=start_event>
1
</parameter>
<parameter=horizon>
6
</parameter>
<parameter=as_of>
2026-08-04T12:00:00+00:00
</parameter>
</function>
</tool_call>"""
    )
    assert calls[0]["function"] == {
        "name": "get_fixture_horizon",
        "arguments": {
            "team_ids": [1],
            "start_event": 1,
            "horizon": 6,
            "as_of": "2026-08-04T12:00:00+00:00",
        },
    }


def test_score_result_checks_route_and_phrase_contract() -> None:
    case = SimpleNamespace(
        expected_tools=("search_players",),
        response_must_contain=("confidence",),
        response_must_not_contain=("guaranteed",),
    )
    result = score_result(case, ["search_players"], "Confidence is high, not certain.", True)
    assert result["tool_route_exact"] is True
    assert result["response_contract_pass"] is True


def test_first_generated_turn_flags_role_leakage() -> None:
    first, valid = first_generated_turn("A useful answer.\nuser\nInvented follow-up")
    assert first == "A useful answer."
    assert valid is False
    assert first_generated_turn("A useful answer.") == ("A useful answer.", True)
