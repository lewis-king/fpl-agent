from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .chat_runtime import SYSTEM_PROMPT as RUNTIME_SYSTEM_PROMPT
from .tool_contracts import openai_tools

APP_TOOL_NAMES = {
    "get_manager_state",
    "compare_captains",
    "search_players",
    "optimize_squad",
}

DEFAULT_SEASON = "2026-27"
DEFAULT_EVENT = 1
DEFAULT_MANAGER_ID = 42
DEFAULT_NOW = "2026-08-06T12:00:00+00:00"


def contains_image(messages: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        isinstance(message.get("content"), list)
        and any(
            isinstance(part, Mapping) and part.get("type") == "image"
            for part in message["content"]
        )
        for message in messages
    )


def _tool_arguments(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        arguments
        for message in messages
        for call in message.get("tool_calls", [])
        if isinstance(call, Mapping)
        for function in [call.get("function")]
        if isinstance(function, Mapping)
        for arguments in [function.get("arguments")]
        if isinstance(arguments, Mapping)
    ]


def runtime_context(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    manager_id: Any = DEFAULT_MANAGER_ID
    event: Any = DEFAULT_EVENT
    season: Any = DEFAULT_SEASON
    now: Any = DEFAULT_NOW
    for arguments in _tool_arguments(messages):
        if "manager_id" in arguments:
            manager_id = arguments["manager_id"]
        if "event" in arguments:
            event = arguments["event"]
        elif "start_event" in arguments:
            event = arguments["start_event"]
        if "season" in arguments:
            season = arguments["season"]
        if "as_of" in arguments:
            now = arguments["as_of"]
    return {
        "season": str(season),
        "event": int(event),
        "manager_id": int(manager_id),
        "now": str(now),
    }


def runtime_system_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
    return RUNTIME_SYSTEM_PROMPT.format(**runtime_context(messages))


def build_app_training_formatter(processor: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Align every text SFT row with the exact web-app inference context.

    Qwen owns the textual tool preamble in its chat template, while FPLAgent owns the application
    policy that follows it. The multimodal collator cannot accept ``tools=`` directly, so derive
    the template prefix once and inject both pieces into the system message. Screenshot inference
    deliberately has neither chat tools nor the conversational runtime policy and is left intact.
    """

    tool_definitions = [
        tool
        for tool in openai_tools()
        if tool["function"]["name"] in APP_TOOL_NAMES
    ]
    marker = "__FPLAGENT_SYSTEM_CONTENT__"
    rendered = processor.apply_chat_template(
        [{"role": "system", "content": marker}],
        tools=tool_definitions,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    system_start = "<|im_start|>system\n"
    if system_start not in rendered or marker not in rendered:
        raise RuntimeError("could not derive Qwen application tool preamble")
    prefix = rendered.split(system_start, 1)[1].split(marker, 1)[0]
    if "# Tools" not in prefix or "<tools>" not in prefix:
        raise RuntimeError("derived Qwen tool preamble is missing its tool contract")

    def add_runtime_context(example: dict[str, Any]) -> dict[str, Any]:
        messages = example["messages"]
        if contains_image(messages):
            return example
        copied_messages = [dict(message) for message in messages]
        system = next(
            (message for message in copied_messages if message.get("role") == "system"),
            None,
        )
        if system is None or not isinstance(system.get("content"), str):
            raise ValueError("tool-aware text row requires a string system message")
        system["content"] = prefix + runtime_system_prompt(copied_messages)
        return {**example, "messages": copied_messages}

    return add_runtime_context
