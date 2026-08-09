from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.manager_snapshots import (
    MANAGER_SNAPSHOT_ROOT,
    latest_manager_snapshot,
)
from fplagent_data.paths import DATA, MANIFESTS

from .manager_state_adapter import (
    ManagerStateInputError,
    manager_state_from_snapshot,
    player_catalog_from_rows,
)
from .optimizer import CURRENT_FORECAST
from .rules import SquadRules, load_rules
from .season_state import (
    ChipSlot,
    ChipStatus,
    ChipType,
    EventStatus,
    Lineup,
    ManagerState,
    PlayerHolding,
    validate_manager_state,
)

SEASON = "2026-27"
CONTRACT_VERSION = 1
MANAGER_STATE_ROOT = DATA / "model" / "manager-states" / SEASON
DEFAULT_DATABASE = DATA / "fpl_history.duckdb"


class ManagerStateContractError(ValueError):
    """An immutable manager-state contract is invalid or cannot be reproduced."""


def canonical_rules_sha256(rules: SquadRules) -> str:
    payload = json.dumps(asdict(rules), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def manager_state_pointer_path(entry_id: int, manifest_root: Path = MANIFESTS) -> Path:
    return manifest_root / f"fpl-manager-{entry_id}-derived-state.json"


def current_actionable_event(database_path: Path = DEFAULT_DATABASE) -> int:
    """Return the one official next deadline, never a guessed event number."""
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        rows = connection.execute(
            """
            SELECT id
            FROM fpl_current_events
            WHERE is_next IS TRUE
            ORDER BY id
            """
        ).fetchall()
    except (duckdb.Error, OSError) as exc:
        raise ManagerStateContractError(
            "the current official event table is unavailable"
        ) from exc
    finally:
        if "connection" in locals():
            connection.close()
    if len(rows) != 1:
        raise ManagerStateContractError(
            f"expected one official next event, found {len(rows)}"
        )
    event = int(rows[0][0])
    if not 1 <= event <= 38:
        raise ManagerStateContractError(f"official next event is outside [1, 38]: {event}")
    return event


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _state_payload(state: ManagerState) -> dict[str, Any]:
    return {
        "season": state.season,
        "event": state.event,
        "event_status": state.event_status.value,
        "squad": [
            {
                "player_id": player.player_id,
                "position": player.position,
                "team_id": player.team_id,
                "purchase_price": player.purchase_price,
                "current_price": player.current_price,
                "selling_price": player.selling_price,
            }
            for player in state.squad
        ],
        "bank": state.bank,
        "free_transfers": state.free_transfers,
        "chips": [
            {
                "chip": slot.chip.value,
                "half": slot.half,
                "status": slot.status.value,
                "played_event": slot.played_event,
            }
            for slot in state.chips
        ],
        "lineup": {
            "starters": list(state.lineup.starters),
            "bench_order": list(state.lineup.bench_order),
            "captain": state.lineup.captain,
            "vice_captain": state.lineup.vice_captain,
        },
        "previous_chip": state.previous_chip.value if state.previous_chip else None,
        "previous_chip_event": state.previous_chip_event,
        "committed_points_cost": state.committed_points_cost,
    }


def _state_from_payload(value: Mapping[str, Any]) -> ManagerState:
    try:
        lineup = value["lineup"]
        state = ManagerState(
            season=str(value["season"]),
            event=int(value["event"]),
            event_status=EventStatus(str(value["event_status"])),
            squad=tuple(
                PlayerHolding(
                    player_id=int(player["player_id"]),
                    position=str(player["position"]),
                    team_id=int(player["team_id"]),
                    purchase_price=int(player["purchase_price"]),
                    current_price=int(player["current_price"]),
                    selling_price=int(player["selling_price"]),
                )
                for player in value["squad"]
            ),
            bank=int(value["bank"]),
            free_transfers=int(value["free_transfers"]),
            chips=tuple(
                ChipSlot(
                    chip=ChipType(str(slot["chip"])),
                    half=int(slot["half"]),
                    status=ChipStatus(str(slot["status"])),
                    played_event=(
                        int(slot["played_event"])
                        if slot.get("played_event") is not None
                        else None
                    ),
                )
                for slot in value["chips"]
            ),
            lineup=Lineup(
                starters=tuple(int(player) for player in lineup["starters"]),
                bench_order=tuple(int(player) for player in lineup["bench_order"]),
                captain=int(lineup["captain"]),
                vice_captain=int(lineup["vice_captain"]),
            ),
            previous_chip=(
                ChipType(str(value["previous_chip"]))
                if value.get("previous_chip") is not None
                else None
            ),
            previous_chip_event=(
                int(value["previous_chip_event"])
                if value.get("previous_chip_event") is not None
                else None
            ),
            committed_points_cost=int(value.get("committed_points_cost", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManagerStateContractError("manager-state payload has an invalid schema") from exc
    return state


def _generation_id(
    *,
    event: int,
    manager_snapshot_sha256: str,
    forecast_sha256: str,
    rules_sha256: str,
) -> str:
    source = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "event": event,
            "manager_snapshot_sha256": manager_snapshot_sha256,
            "forecast_sha256": forecast_sha256,
            "rules_sha256": rules_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def derive_latest_manager_state(
    entry_id: int,
    event: int,
    *,
    forecast_path: Path = CURRENT_FORECAST,
    rules: SquadRules | None = None,
    snapshot_root: Path = MANAGER_SNAPSHOT_ROOT,
    snapshot_manifest_root: Path = MANIFESTS,
    state_root: Path = MANAGER_STATE_ROOT,
    state_manifest_root: Path = MANIFESTS,
) -> dict[str, Any]:
    """Build one exact weekly state, or report why official data is not ready."""
    if not 1 <= event <= 38:
        raise ManagerStateContractError(f"decision event is outside [1, 38]: {event}")
    snapshot_dir, snapshot_manifest, snapshot = latest_manager_snapshot(
        entry_id,
        snapshot_root=snapshot_root,
        manifest_root=snapshot_manifest_root,
    )
    snapshot_id = str(snapshot_manifest["snapshot_id"])
    if not bool(snapshot_manifest.get("complete")):
        unavailable = [str(value) for value in snapshot_manifest.get("unavailable_fields", [])]
        return {
            "status": "not_ready",
            "entry_id": entry_id,
            "event": event,
            "snapshot_id": snapshot_id,
            "unavailable_fields": unavailable,
            "message": (
                "The authenticated squad is synced, but FPL has not exposed the exact weekly "
                f"state yet: {', '.join(unavailable)}."
            ),
        }

    try:
        table = pq.read_table(forecast_path)
    except (OSError, pa.ArrowException) as exc:
        raise ManagerStateContractError(
            f"the current forecast artifact is unreadable: {forecast_path}"
        ) from exc
    loaded_rules = rules or load_rules()
    try:
        state = manager_state_from_snapshot(
            snapshot,
            event=event,
            player_catalog=player_catalog_from_rows(table.to_pylist(), event=event),
            rules=loaded_rules,
            season=SEASON,
        )
    except ManagerStateInputError as exc:
        return {
            "status": "not_ready",
            "entry_id": entry_id,
            "event": event,
            "snapshot_id": snapshot_id,
            "unavailable_fields": [],
            "message": f"The authenticated squad is synced, but weekly state is not ready: {exc}.",
        }

    manager_snapshot_path = snapshot_dir / "manager-state.json"
    manager_manifest_path = snapshot_dir / "manifest.json"
    manager_hash = sha256_file(manager_snapshot_path)
    if manager_hash != snapshot_manifest.get("manager_state_sha256"):
        raise ManagerStateContractError("the raw manager snapshot hash changed during derivation")
    forecast_hash = sha256_file(forecast_path)
    rules_hash = canonical_rules_sha256(loaded_rules)
    generation_id = _generation_id(
        event=event,
        manager_snapshot_sha256=manager_hash,
        forecast_sha256=forecast_hash,
        rules_sha256=rules_hash,
    )
    generation_dir = (
        state_root / str(entry_id) / snapshot_id / f"event-{event}" / generation_id
    )
    contract_path = generation_dir / "manager-state.json"
    contract = {
        "contract_version": CONTRACT_VERSION,
        "generation_id": generation_id,
        "manager_state": _state_payload(state),
        "source_artifacts": {
            "manager_snapshot": str(manager_snapshot_path),
            "manager_snapshot_sha256": manager_hash,
            "manager_snapshot_manifest": str(manager_manifest_path),
            "manager_snapshot_manifest_sha256": sha256_file(manager_manifest_path),
            "forecast": str(forecast_path),
            "forecast_sha256": forecast_hash,
            "runtime_rules_sha256": rules_hash,
        },
    }
    rendered = json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if contract_path.exists():
        if contract_path.read_text(encoding="utf-8") != rendered:
            raise ManagerStateContractError(
                f"immutable manager-state contract collision for generation {generation_id}"
            )
    else:
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = contract_path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(contract_path)

    contract_manifest = {
        "manifest_version": 1,
        "contract_version": CONTRACT_VERSION,
        "season": state.season,
        "entry_id": entry_id,
        "event": event,
        "snapshot_id": snapshot_id,
        "generation_id": generation_id,
        "observed_at": str(snapshot_manifest["observed_at"]),
        "manager_state_contract_sha256": sha256_file(contract_path),
        "manager_snapshot_sha256": manager_hash,
        "forecast_sha256": forecast_hash,
        "runtime_rules_sha256": rules_hash,
        "complete": True,
    }
    contract_manifest_path = generation_dir / "manifest.json"
    if contract_manifest_path.exists():
        if json.loads(contract_manifest_path.read_text(encoding="utf-8")) != contract_manifest:
            raise ManagerStateContractError(
                f"immutable manager-state manifest collision for generation {generation_id}"
            )
    else:
        _atomic_json(contract_manifest_path, contract_manifest)

    pointer_path = manager_state_pointer_path(entry_id, state_manifest_root)
    _atomic_json(
        pointer_path,
        {
            "pointer_version": 1,
            "season": state.season,
            "entry_id": entry_id,
            "event": event,
            "snapshot_id": snapshot_id,
            "generation_id": generation_id,
            "observed_at": str(snapshot_manifest["observed_at"]),
            "contract_manifest": str(contract_manifest_path),
            "contract_manifest_sha256": sha256_file(contract_manifest_path),
        },
    )
    return {
        "status": "ready",
        "entry_id": entry_id,
        "event": event,
        "snapshot_id": snapshot_id,
        "generation_id": generation_id,
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "unavailable_fields": [],
        "message": "The authenticated squad is ready for exact weekly optimisation.",
    }


def load_manager_state_contract(
    contract_path: Path,
    *,
    rules: SquadRules,
    expected_event: int | None = None,
    expected_forecast_path: Path | None = None,
) -> ManagerState:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagerStateContractError(
            f"manager-state contract is unreadable: {contract_path}"
        ) from exc
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ManagerStateContractError("manager-state contract version is unsupported")
    sources = contract.get("source_artifacts")
    if not isinstance(sources, Mapping):
        raise ManagerStateContractError("manager-state contract has no source lineage")
    if sources.get("runtime_rules_sha256") != canonical_rules_sha256(rules):
        raise ManagerStateContractError("manager-state contract rules do not match runtime rules")
    if expected_forecast_path is not None:
        if not expected_forecast_path.is_file():
            raise ManagerStateContractError("expected forecast artifact is missing")
        if sources.get("forecast_sha256") != sha256_file(expected_forecast_path):
            raise ManagerStateContractError(
                "manager-state contract forecast does not match the requested forecast"
            )
    raw_state = contract.get("manager_state")
    if not isinstance(raw_state, Mapping):
        raise ManagerStateContractError("manager-state contract has no manager_state object")
    state = _state_from_payload(raw_state)
    if expected_event is not None and state.event != expected_event:
        raise ManagerStateContractError(
            f"manager-state contract event {state.event} does not match {expected_event}"
        )
    try:
        validate_manager_state(state, rules)
    except ValueError as exc:
        raise ManagerStateContractError(str(exc)) from exc
    return state
