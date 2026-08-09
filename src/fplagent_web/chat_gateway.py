from __future__ import annotations

import os
from typing import Protocol

import httpx

from .models import ChatRequest, ChatResponse


class ChatGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChatGateway(Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse: ...


class LocalQwenGateway:
    def __init__(self, base_url: str | None = None, *, timeout_seconds: float = 180.0) -> None:
        self.base_url = (base_url or os.environ.get("FPLAGENT_LLM_URL", "http://127.0.0.1:8011")).rstrip(
            "/"
        )
        self.timeout_seconds = timeout_seconds

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat",
                    json={
                        "message": request.message,
                        "session_id": request.session_id,
                        "manager_id": request.manager_id,
                        "event": request.event,
                        "season": "2026-27",
                    },
                )
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ChatGatewayError(
                "model_sidecar_offline",
                "Start the local Qwen sidecar with "
                "`llm/.venv/bin/python llm/serve_chat_qwen35.py`.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ChatGatewayError(
                "model_timeout",
                "The local model did not finish the answer in time.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ChatGatewayError(
                "model_request_failed",
                f"The local model service rejected the request ({exc.response.status_code}).",
            ) from exc
        payload = response.json()
        try:
            return ChatResponse.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise ChatGatewayError(
                "invalid_model_response",
                "The local model service returned an invalid response.",
            ) from exc
