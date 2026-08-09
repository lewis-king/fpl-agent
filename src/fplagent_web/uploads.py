from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fplagent_llm.contracts import (
    ImportedPlayer,
    ScreenshotTeamProposal,
    validate_resolved_team,
)
from fplagent_llm.paths import ROOT
from fplagent_llm.screenshot_import import (
    derive_formation,
    load_current_catalog,
    resolve_proposal,
)

from .models import UploadAccepted, UploadStatus

DEFAULT_UPLOAD_ROOT = ROOT / "data" / "web" / "uploads"
DEFAULT_DATABASE = ROOT / "data" / "fpl_history.duckdb"
DEFAULT_VISION_PYTHON = ROOT / "llm" / ".venv" / "bin" / "python"
DEFAULT_VISION_SCRIPT = ROOT / "llm" / "evaluate_screenshot.py"
DEFAULT_VISION_ADAPTER = ROOT / "llm" / "outputs" / "qwen35-4b-fpl-lora-v3" / "adapter"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class UploadStoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sniff_image(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise UploadStoreError(
        "unsupported_image",
        "Upload a JPEG, PNG or WebP screenshot.",
    )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_deadline(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class UploadStore:
    def __init__(
        self,
        root: Path = DEFAULT_UPLOAD_ROOT,
        *,
        database_path: Path = DEFAULT_DATABASE,
        vision_python: Path = DEFAULT_VISION_PYTHON,
        vision_script: Path = DEFAULT_VISION_SCRIPT,
        vision_adapter: Path | None = DEFAULT_VISION_ADAPTER,
    ) -> None:
        self.root = root
        self.database_path = database_path
        self.vision_python = vision_python
        self.vision_script = vision_script
        self.vision_adapter = vision_adapter

    def create(self, filename: str, data: bytes) -> UploadAccepted:
        if not data:
            raise UploadStoreError("empty_upload", "The screenshot file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise UploadStoreError("upload_too_large", "The screenshot must be 10 MB or smaller.")
        suffix, media_type = _sniff_image(data)
        upload_id = uuid.uuid4().hex
        directory = self.root / upload_id
        directory.mkdir(parents=True, exist_ok=False)
        image_path = directory / f"source{suffix}"
        image_path.write_bytes(data)
        created_at = _utc_now()
        payload = {
            "upload_id": upload_id,
            "status": "uploaded",
            "filename": Path(filename).name or f"team{suffix}",
            "media_type": media_type,
            "size_bytes": len(data),
            "image_sha256": hashlib.sha256(data).hexdigest(),
            "created_at": created_at,
            "updated_at": created_at,
            "result": None,
            "error": None,
            "image_path": image_path.name,
        }
        self._write(upload_id, payload)
        return UploadAccepted(
            upload_id=upload_id,
            filename=payload["filename"],
            media_type=media_type,
            size_bytes=len(data),
            image_sha256=payload["image_sha256"],
            preview_url=f"/api/v1/uploads/{upload_id}/image",
            analysis_url=f"/api/v1/uploads/{upload_id}/analyse",
        )

    def get(self, upload_id: str) -> UploadStatus:
        return self._status(self._read(upload_id))

    def image_path(self, upload_id: str) -> Path:
        payload = self._read(upload_id)
        path = self.root / upload_id / str(payload["image_path"])
        if not path.exists():
            raise UploadStoreError("upload_missing", "The uploaded image is unavailable.")
        return path

    def start_analysis(self, upload_id: str) -> tuple[UploadStatus, bool]:
        payload = self._read(upload_id)
        if payload["status"] == "analysing":
            return self._status(payload), False
        if payload["status"] not in {"uploaded", "failed"}:
            raise UploadStoreError(
                "invalid_upload_state",
                f"Analysis cannot start while the upload is {payload['status']}.",
            )
        for path, label in (
            (self.vision_python, "isolated vision Python"),
            (self.vision_script, "vision extraction script"),
        ):
            if not path.exists():
                raise UploadStoreError("vision_worker_missing", f"The {label} is unavailable.")
        payload.update(status="analysing", error=None, updated_at=_utc_now())
        self._write(upload_id, payload)
        return self._status(payload), True

    def run_analysis(self, upload_id: str) -> None:
        payload = self._read(upload_id)
        image_path = self.image_path(upload_id)
        output_path = self.root / upload_id / "vision-result.json"
        command = [
            str(self.vision_python),
            str(self.vision_script),
            "--image",
            str(image_path),
            "--output",
            str(output_path),
        ]
        if self.vision_adapter is not None and self.vision_adapter.exists():
            command.extend(["--adapter", str(self.vision_adapter)])
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=420,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout)[-2_000:].strip()
                raise RuntimeError(detail or "vision extraction exited unsuccessfully")
            raw = json.loads(output_path.read_text(encoding="utf-8"))
            extraction = raw.get("extraction")
            if not raw.get("parse_valid") or not isinstance(extraction, Mapping):
                raise RuntimeError(str(raw.get("parse_error") or "invalid vision output"))
            result = self._resolve_extraction(upload_id, extraction)
        except (
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            payload.update(
                status="failed",
                error=f"Screenshot analysis failed: {str(exc)[:2_000]}",
                updated_at=_utc_now(),
            )
        else:
            payload.update(
                status="ready_for_review",
                result=result,
                error=None,
                updated_at=_utc_now(),
            )
        self._write(upload_id, payload)

    def confirm(self, upload_id: str) -> UploadStatus:
        payload = self._read(upload_id)
        if payload["status"] != "ready_for_review":
            raise UploadStoreError(
                "invalid_upload_state",
                "The screenshot must finish analysis and review before confirmation.",
            )
        result = payload.get("result") or {}
        if not result.get("team_valid"):
            raise UploadStoreError(
                "team_invalid",
                "Resolve the highlighted squad issues before confirmation.",
            )
        payload.update(status="confirmed", updated_at=_utc_now())
        self._write(upload_id, payload)
        return self._status(payload)

    def _resolve_extraction(
        self,
        upload_id: str,
        extraction: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows = extraction.get("players")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            rows = []
        imported: list[ImportedPlayer] = []
        captain_slots: list[tuple[str, int]] = []
        vice_slots: list[tuple[str, int]] = []
        parse_issues: list[str] = []
        seen_slots: set[tuple[str, int]] = set()
        for index, raw_row in enumerate(rows, start=1):
            if not isinstance(raw_row, Mapping):
                parse_issues.append(f"invalid player row {index}")
                continue
            role = str(raw_row.get("squad_role", "")).strip().lower()
            order = _optional_int(raw_row.get("order"))
            source_text = str(raw_row.get("source_text", "")).strip()
            position = str(raw_row.get("position", "")).strip().upper() or None
            if role not in {"starter", "bench"} or order is None or not source_text:
                parse_issues.append(f"invalid player row {index}")
                continue
            slot = (role, order)
            if slot in seen_slots:
                parse_issues.append(f"duplicate slot {role}:{order}")
                continue
            seen_slots.add(slot)
            try:
                imported.append(
                    ImportedPlayer(
                        source_text=source_text,
                        squad_role=role,
                        order=order,
                        position=position,
                    )
                )
            except ValueError as exc:
                parse_issues.append(f"invalid player row {index}: {exc}")
                continue
            if bool(raw_row.get("is_captain")):
                captain_slots.append(slot)
            if bool(raw_row.get("is_vice_captain")):
                vice_slots.append(slot)

        raw_unresolved = extraction.get("unresolved", [])
        unresolved = (
            tuple(str(value) for value in raw_unresolved)
            if isinstance(raw_unresolved, Sequence)
            and not isinstance(raw_unresolved, (str, bytes))
            else ()
        )
        raw_chips = extraction.get("chips", {})
        chips = (
            {str(key): str(value) for key, value in raw_chips.items() if value is not None}
            if isinstance(raw_chips, Mapping)
            else {}
        )
        proposal = ScreenshotTeamProposal(
            schema_version="screenshot-team-v1",
            source_image_id=upload_id,
            season=str(extraction.get("season") or "2026-27"),
            event=_optional_int(extraction.get("event")),
            deadline=_parse_deadline(extraction.get("deadline")),
            formation=(str(extraction["formation"]) if extraction.get("formation") else None),
            players=tuple(imported),
            captain_player_id=None,
            vice_captain_player_id=None,
            bench_order=(),
            chips=chips,
            unresolved=unresolved,
        )
        catalog = load_current_catalog(self.database_path)
        resolved = resolve_proposal(proposal, catalog)
        by_slot = {
            (player.squad_role, player.order): player.player_id for player in resolved.players
        }
        captain_id = by_slot.get(captain_slots[0]) if len(captain_slots) == 1 else None
        vice_id = by_slot.get(vice_slots[0]) if len(vice_slots) == 1 else None
        bench_ids = tuple(
            player.player_id
            for player in sorted(
                (player for player in resolved.players if player.squad_role == "bench"),
                key=lambda player: player.order,
            )
            if player.player_id is not None
        )
        resolved = ScreenshotTeamProposal(
            schema_version=resolved.schema_version,
            source_image_id=resolved.source_image_id,
            season=resolved.season,
            event=resolved.event,
            deadline=resolved.deadline,
            formation=derive_formation(resolved.players) or resolved.formation,
            players=resolved.players,
            captain_player_id=captain_id,
            vice_captain_player_id=vice_id,
            bench_order=bench_ids,
            chips=resolved.chips,
            unresolved=resolved.unresolved,
        )
        validation = validate_resolved_team(
            resolved,
            {player.player_id: player for player in catalog},
        )
        return {
            "schema_version": "upload-analysis-v1",
            "proposal": resolved.to_dict(),
            "team_valid": validation.valid and not parse_issues,
            "validation_issues": list(validation.issues),
            "parse_issues": parse_issues,
            "inferred_formation": validation.inferred_formation,
            "resolved_players": len(validation.resolved_player_ids),
            "vision_adapter": (
                str(self.vision_adapter.relative_to(ROOT))
                if self.vision_adapter and self.vision_adapter.exists()
                else None
            ),
        }

    def _read(self, upload_id: str) -> dict[str, Any]:
        if not upload_id.isalnum() or len(upload_id) != 32:
            raise UploadStoreError("upload_not_found", "The upload does not exist.")
        path = self.root / upload_id / "job.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UploadStoreError("upload_not_found", "The upload does not exist.") from exc

    def _write(self, upload_id: str, payload: Mapping[str, Any]) -> None:
        path = self.root / upload_id / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _status(payload: Mapping[str, Any]) -> UploadStatus:
        public = {
            key: value
            for key, value in payload.items()
            if key in UploadStatus.model_fields
        }
        return UploadStatus.model_validate(public)
