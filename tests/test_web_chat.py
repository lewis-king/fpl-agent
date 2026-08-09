from __future__ import annotations

from fastapi.testclient import TestClient

from fplagent_web.app import create_app
from fplagent_web.models import ChatRequest, ChatResponse


class FakeChatGateway:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        assert request.message == "Who should I captain?"
        return ChatResponse(
            session_id="session-1",
            response="Captain Bruno Fernandes, provisionally.",
            receipt_ids=["captain-v1-test"],
            tool_names=["get_manager_state", "compare_captains"],
            safe_failure=False,
            model="test-model",
        )


def test_chat_api_proxies_typed_grounded_response() -> None:
    gateway = FakeChatGateway()
    client = TestClient(create_app(chat_factory=lambda: gateway))

    response = client.post(
        "/api/v1/chat",
        json={"message": "Who should I captain?", "manager_id": 1, "event": 1},
    )

    assert response.status_code == 200
    assert response.json()["receipt_ids"] == ["captain-v1-test"]
    assert response.json()["tool_names"] == ["get_manager_state", "compare_captains"]
