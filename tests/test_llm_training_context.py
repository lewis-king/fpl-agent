from __future__ import annotations

from typing import Any

from fplagent_llm.chat_runtime import SYSTEM_PROMPT as RUNTIME_SYSTEM_PROMPT
from fplagent_llm.training_context import build_app_training_formatter, runtime_context


class FakeProcessor:
    def apply_chat_template(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        assert kwargs["tools"]
        assert kwargs["tokenize"] is False
        marker = messages[0]["content"]
        return (
            "<|im_start|>system\n# Tools\n\n<tools>\n{}\n</tools>\n\n"
            f"{marker}<|im_end|>\n"
        )


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_0",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def test_direct_training_row_uses_exact_runtime_policy_after_tool_preamble() -> None:
    formatter = build_app_training_formatter(FakeProcessor())
    source = {
        "messages": [
            {"role": "system", "content": "obsolete short training prompt"},
            {"role": "user", "content": "Hi there"},
            {"role": "assistant", "content": "Hi!"},
        ]
    }

    formatted = formatter(source)
    expected_policy = RUNTIME_SYSTEM_PROMPT.format(
        season="2026-27",
        event=1,
        manager_id=42,
        now="2026-08-06T12:00:00+00:00",
    )
    system = formatted["messages"][0]["content"]
    assert system.startswith("# Tools\n\n<tools>")
    assert system.endswith(expected_policy)
    assert "obsolete short training prompt" not in system
    assert source["messages"][0]["content"] == "obsolete short training prompt"


def test_tool_training_row_derives_runtime_identity_from_arguments() -> None:
    messages = [
        {"role": "system", "content": "old"},
        {"role": "user", "content": "Rebuild my current team"},
        _tool_call(
            "optimize_squad",
            {
                "manager_id": 1234,
                "start_event": 7,
                "as_of": "2026-09-30T17:00:00+00:00",
                "constraints": {},
            },
        ),
    ]

    assert runtime_context(messages) == {
        "season": "2026-27",
        "event": 7,
        "manager_id": 1234,
        "now": "2026-09-30T17:00:00+00:00",
    }


def test_screenshot_row_keeps_vision_inference_context() -> None:
    formatter = build_app_training_formatter(FakeProcessor())
    source = {
        "messages": [
            {"role": "system", "content": "screenshot extraction policy"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "path": "team.png"},
                    {"type": "text", "text": "Extract this team"},
                ],
            },
            {"role": "assistant", "content": "{}"},
        ]
    }

    assert formatter(source) is source
    assert source["messages"][0]["content"] == "screenshot extraction policy"
