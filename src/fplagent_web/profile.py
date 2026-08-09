from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_llm.paths import ROOT

from .models import ManagerProfileRequest, ManagerProfileView

DEFAULT_PROFILE_PATH = ROOT / "data" / "web" / "state" / "local-manager-profile.json"


class ManagerProfileStore:
    def __init__(self, path: Path = DEFAULT_PROFILE_PATH) -> None:
        self.path = path

    def get(self) -> ManagerProfileView:
        payload = self._read()
        return ManagerProfileView(
            display_name=str(payload.get("display_name") or "Lewis"),
            fpl_entry_id=(
                int(payload["fpl_entry_id"]) if payload.get("fpl_entry_id") is not None else None
            ),
            sync_state=str(payload.get("sync_state") or "not_connected"),
            last_synced_at=(
                str(payload["last_synced_at"]) if payload.get("last_synced_at") else None
            ),
            message=(
                "Authenticated MCP sync is connected for this local session."
                if payload.get("sync_state") == "mcp_connected"
                else "FPL entry ID saved locally. Authenticated MCP sync is not connected yet."
                if payload.get("fpl_entry_id")
                else "Add the numeric FPL entry ID shown in the URL of your FPL points page."
            ),
        )

    def save(self, request: ManagerProfileRequest) -> ManagerProfileView:
        payload = {
            "schema_version": "local-manager-profile-v1",
            "display_name": request.display_name.strip(),
            "fpl_entry_id": request.fpl_entry_id,
            "sync_state": "id_saved",
            "last_synced_at": None,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)
        return self.get()

    def mark_connected(
        self,
        *,
        entry_id: int,
        display_name: str | None = None,
        observed_at: str | None = None,
    ) -> ManagerProfileView:
        current = self._read()
        payload = {
            "schema_version": "local-manager-profile-v1",
            "display_name": display_name or current.get("display_name") or "Lewis",
            "fpl_entry_id": entry_id,
            "sync_state": "mcp_connected",
            "last_synced_at": observed_at or datetime.now(tz=UTC).isoformat(),
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)
        return self.get()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
