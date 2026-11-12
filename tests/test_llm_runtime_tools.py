from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_llm.chat_runtime import (
    ChatRuntime,
    ChatSession,
    JsonlChatLogger,
    ModelTurn,
    ToolCall,
    ToolTrace,
)
from fplagent_llm.qwen_runtime import QwenChatModel
from fplagent_llm.runtime_tools import (
    CaptainComparisonService,
    LocalManagerRepository,
    RuntimeToolError,
    ToolExecution,
    build_default_tool_registry,
)

AS_OF = "2026-08-06T12:00:00+00:00"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "llm_runtime"
FIXTURE_DECISION = FIXTURE_ROOT / "decision.json"
FIXTURE_FORECASTS = FIXTURE_ROOT / "forecasts.parquet"
FIXTURE_COMPONENTS = FIXTURE_ROOT / "components.parquet"


def _repository(decision_path: Path = FIXTURE_DECISION) -> LocalManagerRepository:
    return LocalManagerRepository(decision_path)


def _registry():
    return build_default_tool_registry(
        decision_path=FIXTURE_DECISION,
        forecast_path=FIXTURE_FORECASTS,
        component_path=FIXTURE_COMPONENTS,
    )


class ScriptedModel:
    name = "scripted-test-model"

    def __init__(self, turns: Sequence[ModelTurn]) -> None:
        self.turns = list(turns)
        self.observed_messages: list[list[Mapping[str, Any]]] = []

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelTurn:
        assert [tool["function"]["name"] for tool in tools] == [
            "get_manager_state",
            "compare_captains",
        ]
        self.observed_messages.append(list(messages))
        return self.turns.pop(0)


def _call(name: str, arguments: Mapping[str, Any]) -> ToolCall:
    return ToolCall(id=f"model-{name}", name=name, arguments=arguments)


def test_local_manager_state_is_versioned_provisional_and_stale() -> None:
    state = _repository().get_state(1, AS_OF)
    assert state["schema_version"] == "manager-state-v1"
    assert state["manager_id"] == 1
    assert len(state["squad_player_ids"]) == 15
    assert len(state["squad"]["starters"]) == 11
    assert len(state["squad"]["bench"]) == 4
    assert state["squad"]["captain_player_id"] == 426
    assert state["squad"]["vice_captain_player_id"] == 229
    assert state["confirmed"] is False
    assert state["requires_confirmation"] is True
    assert state["stale"] is True
    assert state["unavailable_fields"] == ["free_transfers", "chips"]
    assert len(state["source_sha256"]) == 64


def test_local_manager_state_rejects_unknown_manager() -> None:
    with pytest.raises(RuntimeToolError, match="No local manager snapshot"):
        _repository().get_state(2, AS_OF)


def test_captain_comparison_returns_grounded_receipt() -> None:
    service = CaptainComparisonService(
        _repository(), FIXTURE_FORECASTS, FIXTURE_COMPONENTS
    )
    result = service.compare(
        {
            "manager_id": 1,
            "event": 1,
            "candidate_player_ids": [],
            "risk_policy": "robust",
            "as_of": AS_OF,
        }
    )
    assert result["schema_version"] == "captain-comparison-v1"
    assert result["captain"]["player_id"] == 426
    assert result["captain"]["name"] == "Bruno Fernandes"
    assert result["vice_captain"]["player_id"] == 229
    assert result["score_metric"] == "robust_points"
    assert result["score_edge"] == pytest.approx(0.8651)
    assert result["selection_scope"] == "best_legal_xi_from_full_squad"
    assert result["requested_comparison"] is None
    assert result["recommended_lineup"]["aligned_with_current_xi"] is True
    assert result["stored_receipt"]["aligned"] is True
    assert result["evidence_status"] == "stored_decision_receipt_aligned"
    assert result["requires_refresh"] is True
    assert result["requires_confirmation"] is True
    assert result["receipt_id"].startswith("captain-v1-")
    assert len(result["sources"]) == 3


def test_captain_comparison_keeps_sale_only_owned_player_in_squad(
    tmp_path: Path,
) -> None:
    forecasts = pq.read_table(FIXTURE_FORECASTS).to_pylist()
    owned_player = int(
        json.loads(FIXTURE_DECISION.read_text(encoding="utf-8"))["decision"]["squad"][
            "bench"
        ][0]["element"]
    )
    for row in forecasts:
        if int(row["element"]) == owned_player and int(row["event_number"]) == 1:
            row.update(
                {
                    "can_select": False,
                    "p_dnp": 1.0,
                    "p_1_59": 0.0,
                    "p_60_89": 0.0,
                    "p_90_or_more": 0.0,
                    "p_play": 0.0,
                    "expected_points": 0.0,
                    "robust_points": 0.0,
                }
            )
    forecast_path = tmp_path / "forecasts.parquet"
    pq.write_table(pa.Table.from_pylist(forecasts), forecast_path)

    result = CaptainComparisonService(
        _repository(), forecast_path, FIXTURE_COMPONENTS
    ).compare(
        {
            "manager_id": 1,
            "event": 1,
            "candidate_player_ids": [],
            "risk_policy": "robust",
            "as_of": AS_OF,
        }
    )

    assert result["schema_version"] == "captain-comparison-v1"
    assert owned_player not in result["recommended_lineup"]["starter_player_ids"]


def test_filtered_captain_comparison_cannot_redefine_full_xi_recommendation() -> None:
    service = CaptainComparisonService(
        _repository(), FIXTURE_FORECASTS, FIXTURE_COMPONENTS
    )
    result = service.compare(
        {
            "manager_id": 1,
            "event": 1,
            "candidate_player_ids": [55, 384],
            "risk_policy": "robust",
            "as_of": AS_OF,
        }
    )

    assert result["captain"]["name"] == "Bruno Fernandes"
    assert result["vice_captain"]["name"] == "Tarkowski"
    assert result["requested_comparison"]["winner"]["name"] == "Donnarumma"
    assert result["requested_comparison"]["runner_up"]["name"] == "Watkins"


def test_benched_player_can_be_promoted_before_captaincy_is_ranked(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_DECISION.read_text(encoding="utf-8"))
    squad = payload["decision"]["squad"]
    lineup = payload["decision"]["candidate"]["lineups"]["1"]
    bruno = next(row for row in squad["starters"] if int(row["element"]) == 426)
    szoboszlai = next(row for row in squad["bench"] if int(row["element"]) == 368)
    squad["starters"] = [
        szoboszlai if int(row["element"]) == 426 else row for row in squad["starters"]
    ]
    squad["bench"] = [
        bruno if int(row["element"]) == 368 else row for row in squad["bench"]
    ]
    for row in squad["starters"] + squad["bench"]:
        row["captain"] = int(row["element"]) == 55
        row["vice_captain"] = int(row["element"]) == 384
    lineup["starters"] = [368 if int(value) == 426 else value for value in lineup["starters"]]
    lineup["bench_order"] = [
        426 if int(value) == 368 else value for value in lineup["bench_order"]
    ]
    lineup["captain"] = 55
    lineup["vice_captain"] = 384
    decision_path = tmp_path / "bench-captain.json"
    decision_path.write_text(json.dumps(payload), encoding="utf-8")

    result = CaptainComparisonService(
        _repository(decision_path), FIXTURE_FORECASTS, FIXTURE_COMPONENTS
    ).compare(
        {
            "manager_id": 1,
            "event": 1,
            "risk_policy": "robust",
            "as_of": AS_OF,
        }
    )

    assert result["captain"]["name"] == "Bruno Fernandes"
    assert result["recommended_lineup"]["promoted_player_names"] == ["Bruno Fernandes"]
    assert result["recommended_lineup"]["benched_player_names"] == ["Szoboszlai"]
    assert result["recommended_lineup"]["aligned_with_current_xi"] is False


def test_captain_comparison_rejects_non_starter_and_missing_mini_league_context() -> None:
    service = CaptainComparisonService(
        _repository(), FIXTURE_FORECASTS, FIXTURE_COMPONENTS
    )
    with pytest.raises(RuntimeToolError, match="15-player squad"):
        service.compare(
            {
                "manager_id": 1,
                "event": 1,
                "candidate_player_ids": [426, 999999],
                "risk_policy": "robust",
                "as_of": AS_OF,
            }
        )
    with pytest.raises(RuntimeToolError, match="Mini-league captaincy"):
        service.compare(
            {
                "manager_id": 1,
                "event": 1,
                "candidate_player_ids": [],
                "risk_policy": "mini_league",
                "as_of": AS_OF,
            }
        )


def test_registry_rejects_invalid_arguments_before_execution() -> None:
    execution = _registry().execute(
        "get_manager_state", {"manager_id": "1", "as_of": AS_OF}
    )
    assert execution.ok is False
    assert execution.error_code == "invalid_arguments"
    assert execution.output is None


def test_chat_runtime_replays_tools_adds_refresh_guard_and_logs_privately(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                tool_calls=(
                    _call("get_manager_state", {"manager_id": 1, "as_of": AS_OF}),
                ),
            ),
            ModelTurn(
                content="",
                tool_calls=(
                    _call(
                        "compare_captains",
                        {
                            "manager_id": 1,
                            "event": 1,
                            "candidate_player_ids": [],
                            "risk_policy": "robust",
                            "as_of": AS_OF,
                        },
                    ),
                ),
            ),
            ModelTurn(
                content="Captain Bruno Fernandes and vice-captain Tarkowski.",
            ),
        ]
    )
    log_path = tmp_path / "events.jsonl"
    runtime = ChatRuntime(
        model,
        _registry(),
        logger=JsonlChatLogger(log_path),
    )
    session = ChatSession.create(
        manager_id=1,
        event=1,
        now=datetime(2026, 8, 6, 12, tzinfo=UTC),
        session_id="runtime-test",
    )
    result = runtime.chat(session, "Give me the GW1 decision recommendation.")

    assert [trace.name for trace in result.tool_traces] == [
        "get_manager_state",
        "compare_captains",
    ]
    assert result.safe_failure is False
    assert result.grounding_guard_applied is True
    assert "refresh live inputs" in result.response
    assert result.receipt_ids[0].startswith("captain-v1-")
    assert [message["role"] for message in session.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert json.loads(session.messages[3]["content"])["ok"] is True
    logged = json.loads(log_path.read_text(encoding="utf-8"))
    assert logged["session_id"] == "runtime-test"
    assert logged["tool_events"][1]["name"] == "compare_captains"
    assert "user_text" not in logged
    assert "response" not in logged
    assert len(logged["user_text_sha256"]) == 64


def test_chat_runtime_overrides_answer_after_failed_decision_tool() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                tool_calls=(
                    _call(
                        "compare_captains",
                        {
                            "manager_id": 1,
                            "event": 1,
                            "candidate_player_ids": [],
                            "risk_policy": "mini_league",
                            "as_of": AS_OF,
                        },
                    ),
                ),
            ),
            ModelTurn(content="Definitely captain Bruno."),
        ]
    )
    runtime = ChatRuntime(model, _registry())
    result = runtime.chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Who should I captain to chase my mini-league rival?",
    )
    assert result.safe_failure is True
    assert result.failure_code == "decision_tool_failed"
    assert result.grounding_guard_applied is True
    assert result.response.endswith("no recommendation was made.")
    assert "Definitely" not in result.response


def test_chat_guard_overrides_filtered_pair_as_an_open_captain_answer() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                tool_calls=(
                    _call(
                        "compare_captains",
                        {
                            "manager_id": 1,
                            "event": 1,
                            "candidate_player_ids": [55, 384],
                            "risk_policy": "robust",
                            "as_of": AS_OF,
                        },
                    ),
                ),
            ),
            ModelTurn(content="Watkins is the recommended captain."),
        ]
    )
    runtime = ChatRuntime(model, _registry())
    result = runtime.chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Give me the GW1 decision recommendation.",
    )

    assert result.grounding_guard_applied is True
    assert "**Bruno Fernandes is the captain recommendation" in result.response
    assert "Watkins is the recommended captain" not in result.response


def test_full_squad_audit_is_backed_by_all_15_and_ignores_invented_advice() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                tool_calls=(
                    _call("get_manager_state", {"manager_id": 1, "as_of": AS_OF}),
                ),
            ),
            ModelTurn(
                content=(
                    "Maguire is the weakest starter. Use Bench Boost and replace him with a "
                    "forward from the bench."
                )
            ),
        ]
    )
    result = ChatRuntime(model, _registry()).chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Give me a full squad audit of all 15, including bench cover.",
    )

    assert [trace.name for trace in result.tool_traces] == [
        "get_manager_state",
        "compare_captains",
    ]
    assert result.grounding_guard_applied is True
    assert result.safe_failure is False
    assert "Calvert-Lewin" in result.response
    assert "Szoboszlai" in result.response
    assert "backup goalkeeper" in result.response
    assert "Bench Boost" not in result.response
    assert "Maguire is the weakest" not in result.response


def test_player_by_player_review_is_complete_and_receipt_backed() -> None:
    model = ScriptedModel([])
    result = ChatRuntime(model, _registry()).chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Give me a player-by-player review of all 15 players.",
    )

    assert [trace.name for trace in result.tool_traces] == [
        "get_manager_state",
        "compare_captains",
    ]
    assert result.response.count("\n- **") == 15
    assert "**Bruno Fernandes (MID, Man Utd) — Captain.**" in result.response
    assert "**Tarkowski (DEF, Everton) — Vice-captain.**" in result.response
    assert "### Current bench" in result.response
    assert "Gibbs-" not in result.response[-10:]
    assert model.turns == []


def test_incomplete_model_generation_is_not_presented_as_a_finished_answer() -> None:
    model = ScriptedModel(
        [ModelTurn(content="This answer ends half-", generation_truncated=True)]
    )
    result = ChatRuntime(model, _registry()).chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Tell me something broad about FPL.",
    )

    assert result.safe_failure is True
    assert result.failure_code == "model_response_truncated"
    assert "generation limit" in result.response
    assert "half-" not in result.response


def test_named_captain_follow_up_is_automatically_grounded() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="Watkins has higher variance and is more prone to missing out."
            )
        ]
    )
    result = ChatRuntime(model, _registry()).chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Why is Bruno a better captain than Watkins, and what would change your mind?",
    )

    assert [trace.name for trace in result.tool_traces] == [
        "get_manager_state",
        "compare_captains",
    ]
    assert result.tool_traces[-1].arguments["candidate_player_ids"] == [426, 55]
    assert "Between **Bruno Fernandes** and **Watkins**" in result.response
    assert "**6.09** versus **4.45**" in result.response
    assert "Expected minutes" in result.response
    assert "What would change the call" in result.response
    assert "higher variance" not in result.response


def test_captain_follow_up_keeps_context_when_captain_word_is_omitted() -> None:
    model = ScriptedModel([])
    runtime = ChatRuntime(model, _registry())
    session = ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC))

    first = runtime.chat(session, "Who should I captain for GW1?")
    follow_up = runtime.chat(
        session,
        "Why is Bruno better than Watkins, and what would change your mind?",
    )

    assert first.duration_ms >= 0
    assert [trace.name for trace in follow_up.tool_traces] == [
        "get_manager_state",
        "compare_captains",
    ]
    assert "Between **Bruno Fernandes** and **Watkins**" in follow_up.response
    assert "What would change the call" in follow_up.response
    assert model.turns == []


def test_successful_captain_receipt_ends_model_loop_without_duplicate_call() -> None:
    model = ScriptedModel(
        [
            ModelTurn(
                content="",
                tool_calls=(
                    _call("get_manager_state", {"manager_id": 1, "as_of": AS_OF}),
                ),
            ),
            ModelTurn(
                content="",
                tool_calls=(
                    _call(
                        "compare_captains",
                        {
                            "manager_id": 1,
                            "event": 1,
                            "candidate_player_ids": [],
                            "risk_policy": "robust",
                            "as_of": AS_OF,
                        },
                    ),
                ),
            ),
            ModelTurn(
                content="This turn must remain unused.",
                tool_calls=(
                    _call(
                        "compare_captains",
                        {
                            "manager_id": 1,
                            "event": 1,
                            "candidate_player_ids": [],
                            "risk_policy": "robust",
                            "as_of": AS_OF,
                        },
                    ),
                ),
            ),
        ]
    )
    result = ChatRuntime(model, _registry()).chat(
        ChatSession.create(now=datetime(2026, 8, 6, 12, tzinfo=UTC)),
        "Give me the GW1 decision recommendation.",
    )

    assert [trace.name for trace in result.tool_traces].count("compare_captains") == 1
    assert len(model.turns) == 1


def test_chat_runtime_marks_successful_squad_change_as_provisional() -> None:
    response, applied, failure = ChatRuntime._apply_grounding_guard(
        "The workspace now shows the new legal squad.",
        [
            ToolTrace(
                call_id="call-optimize",
                name="optimize_squad",
                arguments={},
                execution=ToolExecution(
                    name="optimize_squad",
                    ok=True,
                    output={"requires_confirmation": True, "workspace_changed": True},
                    error_code=None,
                    error_message=None,
                    duration_ms=1.0,
                ),
            )
        ],
    )

    assert applied is True
    assert failure is None
    assert response.endswith("provisional until you review and confirm it.")


def test_qwen_turn_parser_preserves_tool_arguments_and_boundary() -> None:
    raw = (
        "<tool_call><function=get_manager_state>"
        "<parameter=manager_id>1</parameter>"
        f"<parameter=as_of>\"{AS_OF}\"</parameter>"
        "</function></tool_call>"
    )
    turn = QwenChatModel.parse_turn(raw)
    assert turn.content == ""
    assert turn.boundary_valid is True
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "get_manager_state"
    assert turn.tool_calls[0].arguments == {"manager_id": 1, "as_of": AS_OF}
