from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fplagent_data.manager_snapshots import archive_manager_snapshot
from fplagent_engine.manager_state_store import derive_latest_manager_state
from fplagent_llm.runtime_tools import DEFAULT_DECISION
from fplagent_web.app import create_app
from fplagent_web.preseason import PreseasonSquadService
from fplagent_web.profile import ManagerProfileStore
from fplagent_web.workspace import WorkspaceBuilder


class FakeMcpGateway:
    url = "http://127.0.0.1:8021/mcp"

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.authenticated = False

    async def list_tools(self) -> list[str]:
        return [
            "begin_web_login",
            "poll_web_login",
            "get_auth_status",
            "get_manager_snapshot",
        ]

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name == "begin_web_login":
            return {
                "status": "pending",
                "request_id": "request-1",
                "login_url": "http://127.0.0.1:8020/auth/request-1",
            }
        if name == "poll_web_login":
            self.authenticated = True
            return {
                "status": "connected",
                "request_id": (arguments or {})["request_id"],
                "entry_id": self.snapshot["entry_id"],
                "first_name": "Lewis",
                "last_name": "Tester",
            }
        if name == "get_auth_status":
            return {
                "status": "connected" if self.authenticated else "not_authenticated",
                "entry_id": self.snapshot["entry_id"] if self.authenticated else None,
            }
        if name == "get_manager_snapshot":
            return self.snapshot
        raise AssertionError(f"unexpected tool: {name}")


def _snapshot() -> dict[str, Any]:
    published = json.loads(DEFAULT_DECISION.read_text(encoding="utf-8"))
    squad = published["decision"]["squad"]
    rows = squad["starters"] + squad["bench"]
    return {
        "status": "connected",
        "entry_id": 431892,
        "observed_at": "2026-08-06T10:00:00+00:00",
        "bank": 15,
        "squad_value": 985,
        "free_transfers": 1,
        "transfer_cost": 0,
        "chips": [],
        "picks": [
            {
                "element": int(player["element"]),
                "name": player["name"],
                "position": position,
                "is_captain": bool(player.get("captain")),
                "is_vice_captain": bool(player.get("vice_captain")),
                "purchase_price": round(float(player["price"]) * 10),
                "selling_price": round(float(player["price"]) * 10),
            }
            for position, player in enumerate(rows, start=1)
        ],
    }


def test_local_mcp_login_and_sync_adopt_authenticated_squad(tmp_path: Path) -> None:
    active_path = tmp_path / "active.json"
    profile_path = tmp_path / "profile.json"
    preseason = PreseasonSquadService(active_decision_path=active_path)
    profile = ManagerProfileStore(profile_path)
    gateway = FakeMcpGateway(_snapshot())
    workspace = WorkspaceBuilder(
        active_decision_path=active_path,
        profile_path=profile_path,
    )
    client = TestClient(
        create_app(
            workspace_factory=lambda: workspace,
            preseason_factory=lambda: preseason,
            profile_factory=lambda: profile,
            mcp_factory=lambda: gateway,
            manager_snapshot_archiver=lambda snapshot: archive_manager_snapshot(
                snapshot,
                snapshot_root=tmp_path / "manager-snapshots",
                manifest_root=tmp_path / "manifests",
            ),
            manager_state_deriver=lambda entry_id, event: derive_latest_manager_state(
                entry_id,
                event,
                snapshot_root=tmp_path / "manager-snapshots",
                snapshot_manifest_root=tmp_path / "manifests",
                state_root=tmp_path / "manager-states",
                state_manifest_root=tmp_path / "state-manifests",
            ),
            actionable_event_resolver=lambda: 1,
        )
    )

    connection = client.get("/api/v1/integrations/fpl")
    login = client.post("/api/v1/integrations/fpl/login")
    poll = client.get("/api/v1/integrations/fpl/login/request-1")
    authenticated_connection = client.get("/api/v1/integrations/fpl")
    sync = client.post("/api/v1/integrations/fpl/sync")
    current = client.get("/api/v1/workspace")

    assert connection.json()["status"] == "not_authenticated"
    assert login.json()["login_url"].startswith("http://127.0.0.1:8020/")
    assert poll.json()["status"] == "connected"
    assert authenticated_connection.json()["status"] == "connected"
    assert sync.json()["player_count"] == 15
    assert sync.json()["manager_state_status"] == "not_ready"
    assert sync.json()["manager_state_event"] == 1
    assert "weekly state is not ready" in sync.json()["manager_state_message"]
    assert current.json()["squad"]["source"] == "connected"
    assert current.json()["user"]["fpl_entry_id"] == 431892
    assert current.json()["user"]["sync_state"] == "mcp_connected"
    assert len(list((tmp_path / "manager-snapshots" / "431892").iterdir())) == 1
