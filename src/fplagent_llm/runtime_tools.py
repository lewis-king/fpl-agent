from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

import duckdb

from .paths import ROOT
from .tool_contracts import TOOL_BY_NAME, ToolContract, validate_tool_arguments

DEFAULT_MANAGER_ID = 1
DEFAULT_DECISION = ROOT / "data" / "decisions" / "2026-27-gw1-synthesized.json"
DEFAULT_FORECASTS = ROOT / "data" / "model" / "forecasts" / "2026-27-preseason.parquet"
DEFAULT_COMPONENTS = (
    ROOT / "data" / "model" / "forecasts" / "2026-27-preseason-components.parquet"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _aware_datetime(value: str, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeToolError("invalid_datetime", f"{field} must include a timezone")
    return parsed


class RuntimeToolError(ValueError):
    """Expected tool failure safe to expose to the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolExecution:
    name: str
    ok: bool
    output: Mapping[str, Any] | None
    error_code: str | None
    error_message: str | None
    duration_ms: float

    def model_payload(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "result": dict(self.output or {})}
        return {
            "ok": False,
            "error": {
                "code": self.error_code or "tool_error",
                "message": self.error_message or "The tool could not complete safely.",
            },
        }


ToolHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class ToolRegistry:
    """Schema-validating dispatcher exposing only explicitly enabled read-only tools."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if name not in TOOL_BY_NAME:
            raise ValueError(f"cannot register unknown tool {name!r}")
        if not TOOL_BY_NAME[name].read_only:
            raise ValueError(f"runtime v1 only permits read-only tools: {name!r}")
        if name in self._handlers:
            raise ValueError(f"tool is already registered: {name!r}")
        self._handlers[name] = handler

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    def contracts(self) -> tuple[ToolContract, ...]:
        return tuple(TOOL_BY_NAME[name] for name in self._handlers)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [contract.to_openai_tool() for contract in self.contracts()]

    def execute(self, name: str, arguments: Mapping[str, Any]) -> ToolExecution:
        started = time.perf_counter()
        if name not in self._handlers:
            return ToolExecution(
                name=name,
                ok=False,
                output=None,
                error_code="tool_not_enabled",
                error_message=f"Tool {name!r} is not enabled in this runtime.",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        try:
            validate_tool_arguments(name, arguments)
            output = self._handlers[name](arguments)
        except (TypeError, ValueError) as exc:
            code = exc.code if isinstance(exc, RuntimeToolError) else "invalid_arguments"
            return ToolExecution(
                name=name,
                ok=False,
                output=None,
                error_code=code,
                error_message=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except (OSError, KeyError, json.JSONDecodeError, duckdb.Error):
            return ToolExecution(
                name=name,
                ok=False,
                output=None,
                error_code="tool_internal_error",
                error_message="The tool failed internally; no recommendation was produced.",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        return ToolExecution(
            name=name,
            ok=True,
            output=dict(output),
            error_code=None,
            error_message=None,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


class LocalManagerRepository:
    """Adapter from the current versioned decision artifact to manager-state-v1."""

    def __init__(
        self,
        decision_path: Path = DEFAULT_DECISION,
        *,
        manager_id: int = DEFAULT_MANAGER_ID,
        stale_after: timedelta = timedelta(hours=24),
        fallback_decision_path: Path | None = None,
    ) -> None:
        self.decision_path = decision_path
        self.fallback_decision_path = fallback_decision_path
        self.manager_id = manager_id
        self.stale_after = stale_after

    def _resolved_path(self) -> Path:
        if self.decision_path.exists():
            return self.decision_path
        if self.fallback_decision_path is not None and self.fallback_decision_path.exists():
            return self.fallback_decision_path
        return self.decision_path

    def _decision(self) -> dict[str, Any]:
        path = self._resolved_path()
        if not path.exists():
            raise RuntimeToolError(
                "manager_snapshot_missing",
                f"Manager snapshot does not exist at {path}.",
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            payload["decision"]["squad"]
            payload["decision"]["candidate"]["lineups"]["1"]
            payload["created_at"]
        except (KeyError, TypeError) as exc:
            raise RuntimeToolError(
                "manager_snapshot_invalid", "Manager snapshot has an unsupported shape."
            ) from exc
        return payload

    def get_state(self, manager_id: int, as_of: str) -> dict[str, Any]:
        if manager_id != self.manager_id:
            raise RuntimeToolError(
                "manager_not_found",
                f"No local manager snapshot is configured for manager {manager_id}.",
            )
        requested_at = _aware_datetime(as_of, "as_of")
        payload = self._decision()
        source_path = self._resolved_path()
        observed_at = _aware_datetime(str(payload["created_at"]), "created_at")
        if requested_at < observed_at:
            raise RuntimeToolError(
                "snapshot_unavailable_at_requested_time",
                "The local snapshot was created after the requested as_of time.",
            )
        decision = payload["decision"]
        squad = decision["squad"]
        lineup = decision["candidate"]["lineups"]["1"]
        starters = [self._player(row, "starter", index) for index, row in enumerate(
            squad["starters"], start=1
        )]
        bench = [
            self._player(row, "bench", index)
            for index, row in enumerate(squad["bench"], start=1)
        ]
        age = requested_at - observed_at
        manager_context = payload.get("manager_context") or {}
        return {
            "schema_version": "manager-state-v1",
            "manager_id": manager_id,
            "requested_as_of": requested_at.isoformat(),
            "observed_at": observed_at.isoformat(),
            "source": _display_path(source_path),
            "source_sha256": _sha256(source_path),
            "state": str(payload.get("decision_status", "provisional")),
            "confirmed": bool((payload.get("workspace_candidate") or {}).get("confirmed", False)),
            "requires_confirmation": bool(
                (payload.get("workspace_candidate") or {}).get("requires_confirmation", True)
            ),
            "stale": age > self.stale_after,
            "age_seconds": age.total_seconds(),
            "season": "2026-27",
            "event": 1,
            "squad_player_ids": [row["player_id"] for row in starters + bench],
            "squad": {
                "formation": str(squad["formation"]),
                "starters": starters,
                "bench": bench,
                "captain_player_id": int(lineup["captain"]),
                "vice_captain_player_id": int(lineup["vice_captain"]),
                "bench_order": [int(value) for value in lineup["bench_order"]],
            },
            "bank": float(squad["bank"]),
            "budget_spent": float(squad["budget_spent"]),
            "free_transfers": manager_context.get("free_transfers"),
            "chips": manager_context.get("chips"),
            "preferences": {
                "risk_policy": (payload.get("workspace_candidate") or {}).get(
                    "risk_profile", "robust"
                ),
                "source": (payload.get("workspace_candidate") or {}).get(
                    "source", "decision_synthesis"
                ),
            },
            "unavailable_fields": [
                field
                for field in ("free_transfers", "chips")
                if manager_context.get(field) is None
            ],
            "refresh_required": True,
            "refresh_reason": str(payload.get("deadline_rule", "Live refresh required.")),
        }

    @staticmethod
    def _player(row: Mapping[str, Any], role: str, order: int) -> dict[str, Any]:
        return {
            "player_id": int(row["element"]),
            "name": str(row["name"]),
            "position": str(row["position"]),
            "team": str(row["team"]),
            "price": float(row["price"]),
            "role": role,
            "order": order,
            "captain": bool(row.get("captain", False)),
            "vice_captain": bool(row.get("vice_captain", False)),
            "expected_points": round(float(row.get("expected_points", 0.0)), 4),
            "robust_points": round(float(row.get("robust_points", 0.0)), 4),
            "play_probability": round(float(row.get("p_play", 0.0)), 4),
            "uncertainty": round(float(row.get("uncertainty", 0.0)), 4),
            "news": str(row.get("news") or ""),
        }

    def handle_get_manager_state(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.get_state(int(arguments["manager_id"]), str(arguments["as_of"]))


class CaptainComparisonService:
    """Grounded captain comparison over the stored lineup and versioned forecasts."""

    def __init__(
        self,
        managers: LocalManagerRepository,
        forecast_path: Path = DEFAULT_FORECASTS,
        component_path: Path = DEFAULT_COMPONENTS,
    ) -> None:
        self.managers = managers
        self.forecast_path = forecast_path
        self.component_path = component_path

    def compare(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        manager_id = int(arguments["manager_id"])
        event = int(arguments["event"])
        risk_policy = str(arguments["risk_policy"])
        as_of = str(arguments["as_of"])
        if event != 1:
            raise RuntimeToolError(
                "event_not_available",
                "The current local decision receipt supports GW1 only; rerun the engine first.",
            )
        if risk_policy == "mini_league":
            raise RuntimeToolError(
                "mini_league_context_missing",
                "Mini-league captaincy needs rank, rival and objective context that is not stored.",
            )
        state = self.managers.get_state(manager_id, as_of)
        starter_ids = [int(row["player_id"]) for row in state["squad"]["starters"]]
        squad_ids = [
            int(row["player_id"])
            for row in state["squad"]["starters"] + state["squad"]["bench"]
        ]
        requested = [int(value) for value in arguments.get("candidate_player_ids", [])]
        if len(requested) != len(set(requested)):
            raise RuntimeToolError(
                "duplicate_candidates", "Captain candidate IDs must be unique."
            )
        illegal = sorted(set(requested) - set(squad_ids))
        if illegal:
            raise RuntimeToolError(
                "candidate_not_in_squad",
                f"Captain candidates must be in the stored 15-player squad; invalid IDs: {illegal}.",
            )
        if requested and len(requested) < 2:
            raise RuntimeToolError(
                "insufficient_candidates", "At least two legal captain candidates are required."
            )
        # First choose the best legal XI from all 15 players, then rank captaincy within that XI.
        # A requested subset remains an additional pairwise comparison and cannot redefine the
        # open recommendation.
        squad_rows = self._forecast_rows(squad_ids, event)
        if len(squad_rows) != len(squad_ids):
            found = {int(row["player_id"]) for row in squad_rows}
            missing = sorted(set(squad_ids) - found)
            raise RuntimeToolError(
                "forecast_missing", f"No versioned GW{event} forecast for player IDs {missing}."
            )
        metric = "expected_points" if risk_policy == "expected_points" else "robust_points"
        recommended_ids, lineup_score = self._best_legal_lineup(squad_rows, metric)
        rows = [row for row in squad_rows if int(row["player_id"]) in recommended_ids]
        rows.sort(key=lambda row: (-float(row[metric]), int(row["player_id"])))
        captain, vice = rows[:2]
        requested_comparison = None
        if requested:
            requested_rows = [
                row for row in squad_rows if int(row["player_id"]) in requested
            ]
            requested_rows.sort(
                key=lambda row: (-float(row[metric]), int(row["player_id"]))
            )
            requested_comparison = {
                "candidate_player_ids": requested,
                "winner": requested_rows[0],
                "runner_up": requested_rows[1],
                "score_edge": round(
                    float(requested_rows[0][metric]) - float(requested_rows[1][metric]),
                    4,
                ),
                "ranked_candidates": requested_rows,
                "winner_in_recommended_xi": int(requested_rows[0]["player_id"])
                in recommended_ids,
            }
        stored_captain = int(state["squad"]["captain_player_id"])
        stored_vice = int(state["squad"]["vice_captain_player_id"])
        by_id = {int(row["player_id"]): row for row in squad_rows}
        promoted_ids = sorted(recommended_ids - set(starter_ids))
        benched_ids = sorted(set(starter_ids) - recommended_ids)
        lineup_aligned = not promoted_ids and not benched_ids
        captaincy_aligned = (
            captain["player_id"] == stored_captain
            and vice["player_id"] == stored_vice
        )
        receipt_backed = lineup_aligned and captaincy_aligned
        receipt_seed = (
            f"{manager_id}:{event}:{risk_policy}:{captain['player_id']}:"
            f"{vice['player_id']}:{state['source_sha256']}:{_sha256(self.forecast_path)}"
        )
        receipt_id = "captain-v1-" + hashlib.sha256(receipt_seed.encode()).hexdigest()[:16]
        return {
            "schema_version": "captain-comparison-v1",
            "receipt_id": receipt_id,
            "manager_id": manager_id,
            "event": event,
            "risk_policy": risk_policy,
            "requested_as_of": state["requested_as_of"],
            "manager_state_observed_at": state["observed_at"],
            "forecast_observed_at": rows[0]["snapshot_at"],
            "forecast_model_created_at": rows[0]["model_created_at"],
            "forecast_model_version": rows[0]["model_version"],
            "captain": captain,
            "vice_captain": vice,
            "score_metric": metric,
            "score_edge": round(float(captain[metric]) - float(vice[metric]), 4),
            "ranked_candidates": rows,
            "squad_ranked_candidates": sorted(
                squad_rows,
                key=lambda row: (-float(row[metric]), int(row["player_id"])),
            ),
            "selection_scope": "best_legal_xi_from_full_squad",
            "requested_comparison": requested_comparison,
            "recommended_lineup": {
                "starter_player_ids": sorted(recommended_ids),
                "bench_player_ids": sorted(set(squad_ids) - recommended_ids),
                "formation": self._formation(
                    [by_id[player_id] for player_id in recommended_ids]
                ),
                "captain_inclusive_score": round(lineup_score, 4),
                "promoted_player_ids": promoted_ids,
                "promoted_player_names": [by_id[player_id]["name"] for player_id in promoted_ids],
                "benched_player_ids": benched_ids,
                "benched_player_names": [by_id[player_id]["name"] for player_id in benched_ids],
                "aligned_with_current_xi": lineup_aligned,
            },
            "stored_receipt": {
                "captain_player_id": stored_captain,
                "captain_name": by_id[stored_captain]["name"],
                "vice_captain_player_id": stored_vice,
                "vice_captain_name": by_id[stored_vice]["name"],
                "captaincy_aligned": captaincy_aligned,
                "aligned": receipt_backed,
            },
            "evidence_status": (
                "stored_decision_receipt_aligned"
                if receipt_backed
                else "provisional_marginal_forecast_ranking"
            ),
            "correlation_caveat": (
                "The stored default pair comes from the existing component-simulation decision "
                "receipt. Any different full-XI marginal ranking requires a decision-engine rerun "
                "for correlation-aware promotion; filtered comparisons remain informational."
            ),
            "main_risk": "Minutes and availability remain modelled rather than guaranteed.",
            "manager_state_stale": bool(state["stale"]),
            "requires_refresh": bool(state["refresh_required"]),
            "requires_confirmation": bool(state["requires_confirmation"]),
            "sources": [
                {
                    "path": state["source"],
                    "sha256": state["source_sha256"],
                },
                {
                    "path": _display_path(self.forecast_path),
                    "sha256": _sha256(self.forecast_path),
                },
                {
                    "path": _display_path(self.component_path),
                    "sha256": _sha256(self.component_path),
                },
            ],
        }

    @staticmethod
    def _best_legal_lineup(
        rows: Sequence[Mapping[str, Any]], metric: str
    ) -> tuple[set[int], float]:
        best_ids: set[int] | None = None
        best_key: tuple[float, float, tuple[int, ...]] | None = None
        for candidate in combinations(rows, 11):
            counts = {
                position: sum(str(row["position"]) == position for row in candidate)
                for position in ("GK", "DEF", "MID", "FWD")
            }
            if not (
                counts["GK"] == 1
                and 3 <= counts["DEF"] <= 5
                and 2 <= counts["MID"] <= 5
                and 1 <= counts["FWD"] <= 3
            ):
                continue
            base_score = sum(float(row[metric]) for row in candidate)
            captain_score = max(float(row[metric]) for row in candidate)
            ids = tuple(sorted(int(row["player_id"]) for row in candidate))
            key = (base_score + captain_score, base_score, tuple(-value for value in ids))
            if best_key is None or key > best_key:
                best_key = key
                best_ids = set(ids)
        if best_ids is None or best_key is None:
            raise RuntimeToolError(
                "legal_lineup_unavailable",
                "The stored 15-player squad cannot form a legal starting XI.",
            )
        return best_ids, best_key[0]

    @staticmethod
    def _formation(rows: Sequence[Mapping[str, Any]]) -> str:
        values = list(rows)
        return "-".join(
            str(sum(str(row["position"]) == position for row in values))
            for position in ("DEF", "MID", "FWD")
        )

    def _forecast_rows(self, player_ids: Sequence[int], event: int) -> list[dict[str, Any]]:
        for path in (self.forecast_path, self.component_path):
            if not path.exists():
                raise RuntimeToolError(
                    "forecast_artifact_missing", f"Forecast artifact does not exist at {path}."
                )
        connection = duckdb.connect()
        try:
            records = connection.execute(
                """
                SELECT f.element, f.player_name, f.position, f.team_name,
                       f.expected_points, f.robust_points, f.p_play, f.model_sd,
                       c.expected_minutes, f.snapshot_at, f.model_created_at, f.model_version
                FROM read_parquet(?) f
                LEFT JOIN read_parquet(?) c
                  USING (season, event_number, element)
                WHERE f.event_number = ?
                  AND f.element IN (SELECT * FROM unnest(?))
                  AND f.can_select AND NOT f.removed
                """,
                [str(self.forecast_path), str(self.component_path), event, list(player_ids)],
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "player_id": int(row[0]),
                "name": str(row[1]),
                "position": str(row[2]),
                "team": str(row[3]),
                "expected_points": round(float(row[4]), 4),
                "robust_points": round(float(row[5]), 4),
                "p_play": round(float(row[6]), 4),
                "model_sd": round(float(row[7]), 4),
                "expected_minutes": round(float(row[8]), 2),
                "snapshot_at": str(row[9]),
                "model_created_at": str(row[10]),
                "model_version": str(row[11]),
            }
            for row in records
        ]

    def handle_compare_captains(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.compare(arguments)


def build_default_tool_registry(
    *,
    decision_path: Path = DEFAULT_DECISION,
    forecast_path: Path = DEFAULT_FORECASTS,
    component_path: Path = DEFAULT_COMPONENTS,
    manager_id: int = DEFAULT_MANAGER_ID,
    fallback_decision_path: Path | None = None,
) -> ToolRegistry:
    managers = LocalManagerRepository(
        decision_path,
        manager_id=manager_id,
        fallback_decision_path=fallback_decision_path,
    )
    captains = CaptainComparisonService(managers, forecast_path, component_path)
    registry = ToolRegistry()
    registry.register("get_manager_state", managers.handle_get_manager_state)
    registry.register("compare_captains", captains.handle_compare_captains)
    return registry
