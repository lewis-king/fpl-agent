from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fplagent_llm.chat_runtime import (
    DEFAULT_EVENT_LOG,
    ChatRuntime,
    ChatSession,
    JsonlChatLogger,
)
from fplagent_llm.qwen_runtime import QwenChatModel
from fplagent_llm.runtime_tools import (
    DEFAULT_COMPONENTS,
    DEFAULT_DECISION,
    DEFAULT_FORECASTS,
    build_default_tool_registry,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Run the local grounded FPLAgent chat loop")
    root.add_argument("--model", default="unsloth/Qwen3.5-4B")
    root.add_argument("--adapter", type=Path)
    root.add_argument("--manager-id", type=int, default=1)
    root.add_argument("--season", default="2026-27")
    root.add_argument("--event", type=int, default=1)
    root.add_argument("--prompt")
    root.add_argument("--max-new-tokens", type=int, default=512)
    root.add_argument("--max-tool-rounds", type=int, default=4)
    root.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    root.add_argument("--forecasts", type=Path, default=DEFAULT_FORECASTS)
    root.add_argument("--components", type=Path, default=DEFAULT_COMPONENTS)
    root.add_argument("--event-log", type=Path, default=DEFAULT_EVENT_LOG)
    root.add_argument("--log-content", action="store_true")
    root.add_argument("--json", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    tools = build_default_tool_registry(
        decision_path=args.decision,
        forecast_path=args.forecasts,
        component_path=args.components,
        manager_id=args.manager_id,
    )
    model = QwenChatModel.load(
        model_name=args.model,
        adapter=args.adapter,
        max_new_tokens=args.max_new_tokens,
    )
    runtime = ChatRuntime(
        model,
        tools,
        logger=JsonlChatLogger(args.event_log, include_content=args.log_content),
        max_tool_rounds=args.max_tool_rounds,
    )
    session = ChatSession.create(
        manager_id=args.manager_id,
        season=args.season,
        event=args.event,
        now=datetime.now(tz=UTC),
    )

    if args.prompt:
        result = runtime.chat(session, args.prompt)
        print(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
            if args.json
            else result.response
        )
        return

    print("FPLAgent local chat. Type /quit to exit.")
    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if prompt in {"/quit", "/exit"}:
            return
        if not prompt:
            continue
        result = runtime.chat(session, prompt)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(f"fplagent> {result.response}")


if __name__ == "__main__":
    main()
