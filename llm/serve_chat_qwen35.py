from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fplagent_llm.chat_runtime import (
    DEFAULT_EVENT_LOG,
    ChatRuntime,
    ChatSession,
    JsonlChatLogger,
)
from fplagent_llm.qwen_runtime import QwenChatModel
from fplagent_llm.runtime_tools import DEFAULT_DECISION, build_default_tool_registry
from fplagent_web.preseason import DEFAULT_ACTIVE_DECISION, PreseasonSquadService


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = None
    manager_id: int = Field(default=1, ge=1)
    season: str = "2026-27"
    event: int = Field(default=1, ge=1)


def create_app(runtime: ChatRuntime, model_name: str) -> FastAPI:
    app = FastAPI(title="FPLAgent local Qwen sidecar", version="0.1.0")
    sessions: dict[str, ChatSession] = {}
    generation_lock = asyncio.Lock()

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ready",
            "model": model_name,
            "sessions": len(sessions),
            "device": "cuda",
        }

    @app.post("/v1/chat")
    async def chat(request: Request) -> dict[str, object]:
        if request.session_id:
            session = sessions.get(request.session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="chat session not found")
            if session.manager_id != request.manager_id or session.event != request.event:
                raise HTTPException(status_code=409, detail="chat session context changed")
        else:
            session = ChatSession.create(
                manager_id=request.manager_id,
                season=request.season,
                event=request.event,
            )
            sessions[session.session_id] = session
        async with generation_lock:
            result = await asyncio.to_thread(runtime.chat, session, request.message)
        return {
            "session_id": result.session_id,
            "response": result.response,
            "receipt_ids": list(result.receipt_ids),
            "tool_names": [trace.name for trace in result.tool_traces],
            "safe_failure": result.safe_failure,
            "failure_code": result.failure_code,
            "grounding_guard_applied": result.grounding_guard_applied,
            "model": model_name,
            "duration_ms": result.duration_ms,
        }

    return app


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Keep local Qwen loaded for FPLAgent web chat")
    root.add_argument("--model", default="unsloth/Qwen3.5-4B")
    root.add_argument("--adapter", type=Path)
    root.add_argument("--host", default="127.0.0.1")
    root.add_argument("--port", type=int, default=8011)
    root.add_argument("--max-new-tokens", type=int, default=512)
    root.add_argument("--max-tool-rounds", type=int, default=6)
    root.add_argument("--event-log", type=Path, default=DEFAULT_EVENT_LOG)
    root.add_argument("--log-content", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    model = QwenChatModel.load(
        model_name=args.model,
        adapter=args.adapter,
        max_new_tokens=args.max_new_tokens,
    )
    preseason = PreseasonSquadService()
    tools = build_default_tool_registry(
        decision_path=DEFAULT_ACTIVE_DECISION,
        fallback_decision_path=DEFAULT_DECISION,
    )
    tools.register("search_players", preseason.handle_search_players)
    tools.register("optimize_squad", preseason.handle_optimize_squad)
    runtime = ChatRuntime(
        model,
        tools,
        logger=JsonlChatLogger(args.event_log, include_content=args.log_content),
        max_tool_rounds=args.max_tool_rounds,
    )
    app = create_app(runtime, model.name)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
