from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from fplagent_engine.capital_efficiency import candidate_publication_role_risks
from fplagent_engine.optimizer import POSITION_ORDER, _player_rows, _solve
from fplagent_llm.paths import ROOT
from fplagent_llm.runtime_tools import DEFAULT_DECISION, DEFAULT_FORECASTS

from .models import (
    GenerateSquadRequest,
    GenerateSquadResponse,
    PreseasonOptions,
    PreseasonTeamOption,
    SquadCritique,
)

DEFAULT_DATABASE = ROOT / "data" / "fpl_history.duckdb"
DEFAULT_ACTIVE_DECISION = ROOT / "data" / "web" / "state" / "active-manager-decision.json"


class PreseasonSquadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class PreseasonSquadService:
    """Fast candidate-squad scenarios over the latest published forecast artifact."""

    def __init__(
        self,
        *,
        published_decision_path: Path = DEFAULT_DECISION,
        active_decision_path: Path = DEFAULT_ACTIVE_DECISION,
        database_path: Path = DEFAULT_DATABASE,
        forecast_path: Path = DEFAULT_FORECASTS,
    ) -> None:
        self.published_decision_path = published_decision_path
        self.active_decision_path = active_decision_path
        self.database_path = database_path
        self.forecast_path = forecast_path

    def decision_path(self) -> Path:
        return (
            self.active_decision_path
            if self.active_decision_path.exists()
            else self.published_decision_path
        )

    def current_payload(self) -> dict[str, Any]:
        path = self.decision_path()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreseasonSquadError(
                "decision_unavailable", "The current candidate squad is unavailable."
            ) from exc

    def options(self) -> PreseasonOptions:
        published = self._published_payload()
        candidate = published["decision"]["candidate"]
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, name, short_name FROM fpl_current_teams ORDER BY name"
            ).fetchall()
        return PreseasonOptions(
            published_candidate_id=str(candidate["candidate_id"]),
            published_generated_at=str(published["created_at"]),
            custom_build_estimate_seconds="about 3 seconds for five gameweeks",
            teams=[
                PreseasonTeamOption(team_id=int(row[0]), name=str(row[1]), short_name=str(row[2]))
                for row in rows
            ],
        )

    def generate(self, request: GenerateSquadRequest) -> GenerateSquadResponse:
        started = time.perf_counter()
        locked = set(request.locked_player_ids)
        excluded = set(request.excluded_player_ids)
        if len(locked) != len(request.locked_player_ids):
            raise PreseasonSquadError("duplicate_lock", "A player can only be locked once.")
        if len(excluded) != len(request.excluded_player_ids):
            raise PreseasonSquadError("duplicate_exclusion", "A player can only be excluded once.")
        if locked & excluded:
            raise PreseasonSquadError(
                "conflicting_constraint", "A player cannot be both locked and excluded."
            )

        rows, all_events = _player_rows(self.forecast_path)
        events = all_events[: request.horizon]
        rows = [row for row in rows if int(row["event_number"]) in events]
        available_ids = {int(row["element"]) for row in rows}
        unknown = (locked | excluded) - available_ids
        if unknown:
            raise PreseasonSquadError(
                "player_unavailable",
                f"No selectable forecast exists for player IDs {sorted(unknown)}.",
            )
        team_ids = self._team_ids()
        club_minimums: dict[int, int] = {}
        for item in request.club_minimums:
            short_name = item.team_short_name.upper()
            team_id = team_ids.get(short_name)
            if team_id is None:
                raise PreseasonSquadError(
                    "club_not_found", f"No current FPL club matches {short_name}."
                )
            club_minimums[team_id] = max(club_minimums.get(team_id, 0), item.count)

        score = self._score(rows, request.risk_profile)
        event_rows = {int(row["element"]): row for row in rows if int(row["event_number"]) == 1}
        role_exclusions: set[int] = set()
        try:
            while True:
                solution = _solve(
                    rows,
                    events,
                    score_by_row=score,
                    required_players=locked,
                    excluded_players=excluded | role_exclusions,
                    club_minimums=club_minimums,
                )
                role_risks = candidate_publication_role_risks(
                    solution,
                    event_rows,
                    solution["player_meta"],
                )
                newly_unsafe = {
                    int(risk["element"])
                    for risk in role_risks
                    if int(risk["element"]) not in locked
                } - role_exclusions
                if not newly_unsafe:
                    break
                role_exclusions.update(newly_unsafe)
        except (RuntimeError, ValueError) as exc:
            raise PreseasonSquadError(
                "constraints_infeasible",
                "Those rules do not produce a legal, role-safe squad. Remove one or more locks, "
                "exclusions, or club targets and try again.",
            ) from exc

        current_ids = self._current_player_ids()
        created_at = _utc_now()
        constraint_payload = request.model_dump(mode="json")
        seed = json.dumps(
            {
                "selected": sorted(solution["selected"]),
                "lineup": solution["lineups"][1],
                "constraints": constraint_payload,
                "created_at": created_at,
            },
            sort_keys=True,
        )
        candidate_id = "S-" + hashlib.sha256(seed.encode()).hexdigest()[:10]
        receipt_id = "squad-v1-" + hashlib.sha256(seed.encode()).hexdigest()[:16]
        payload = self._generated_payload(
            solution,
            candidate_id=candidate_id,
            receipt_id=receipt_id,
            created_at=created_at,
            constraints=constraint_payload,
            parent_candidate_id=self._current_candidate_id(),
            role_integrity_risks=role_risks,
        )
        _atomic_json(self.active_decision_path, payload)
        lineup = solution["lineups"][1]
        duration_ms = (time.perf_counter() - started) * 1000
        return GenerateSquadResponse(
            candidate_id=candidate_id,
            receipt_id=receipt_id,
            formation=str(lineup["formation"]),
            expected_points=round(float(lineup["expected_points"]), 2),
            budget_spent=round(float(solution["budget"]) / 10.0, 1),
            bank=round((1000.0 - float(solution["budget"])) / 10.0, 1),
            changed_player_ids=sorted(set(current_ids) ^ set(solution["selected"])),
            duration_ms=round(duration_ms, 1),
            message=(
                "A legal candidate is active, but one or more explicitly locked players need a "
                "role review."
                if role_risks
                else "A new legal, role-safe candidate squad is now active in the decision workspace."
            ),
        )

    def use_published(self) -> GenerateSquadResponse:
        started = time.perf_counter()
        published = self._published_payload()
        previous_ids = set(self._current_player_ids())
        copied = json.loads(json.dumps(published))
        candidate = copied["decision"]["candidate"]
        candidate_id = str(candidate["candidate_id"])
        receipt_seed = f"published:{candidate_id}:{_utc_now()}"
        receipt_id = "squad-v1-" + hashlib.sha256(receipt_seed.encode()).hexdigest()[:16]
        copied["created_at"] = _utc_now()
        copied["workspace_candidate"] = {
            "source": "generated",
            "source_label": "Published robust recommendation",
            "confirmed": False,
            "requires_confirmation": True,
            "parent_candidate_id": self._current_candidate_id(),
            "locked_player_ids": [],
            "risk_profile": "safer",
            "horizon": 5,
            "constraints": {},
            "receipt_id": receipt_id,
        }
        _atomic_json(self.active_decision_path, copied)
        squad = copied["decision"]["squad"]
        lineup = candidate["lineups"]["1"]
        selected_ids = {int(row["element"]) for row in squad["starters"] + squad["bench"]}
        return GenerateSquadResponse(
            candidate_id=candidate_id,
            receipt_id=receipt_id,
            formation=str(squad["formation"]),
            expected_points=round(float(lineup["expected_points"]), 2),
            budget_spent=float(squad["budget_spent"]),
            bank=float(squad["bank"]),
            changed_player_ids=sorted(previous_ids ^ selected_ids),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            message="The published robust recommendation is now active.",
        )

    def adopt_upload(self, analysis: Mapping[str, Any]) -> str:
        if not analysis.get("team_valid"):
            raise PreseasonSquadError(
                "team_invalid", "Only a validated screenshot squad can become active."
            )
        proposal = analysis.get("proposal")
        if not isinstance(proposal, Mapping):
            raise PreseasonSquadError("proposal_missing", "The screenshot proposal is missing.")
        raw_players = proposal.get("players")
        if not isinstance(raw_players, list):
            raise PreseasonSquadError("proposal_missing", "The screenshot players are missing.")

        rows, _ = _player_rows(self.forecast_path)
        event_rows = {int(row["element"]): row for row in rows if int(row["event_number"]) == 1}
        selected_ids = [int(row["player_id"]) for row in raw_players]
        if len(selected_ids) != 15 or len(set(selected_ids)) != 15:
            raise PreseasonSquadError(
                "proposal_invalid", "The screenshot must contain 15 unique resolved players."
            )
        missing = set(selected_ids) - set(event_rows)
        if missing:
            raise PreseasonSquadError(
                "forecast_missing", f"GW1 forecasts are missing for player IDs {sorted(missing)}."
            )
        starters = sorted(
            (row for row in raw_players if row["squad_role"] == "starter"),
            key=lambda row: int(row["order"]),
        )
        bench = sorted(
            (row for row in raw_players if row["squad_role"] == "bench"),
            key=lambda row: int(row["order"]),
        )
        starter_ids = [int(row["player_id"]) for row in starters]
        bench_ids = [int(row["player_id"]) for row in bench]
        captain = proposal.get("captain_player_id")
        vice = proposal.get("vice_captain_player_id")
        ranked = sorted(
            starter_ids,
            key=lambda element: float(event_rows[element]["robust_points"]),
            reverse=True,
        )
        captain_id = int(captain) if captain in starter_ids else ranked[0]
        vice_id = int(vice) if vice in starter_ids and vice != captain_id else ranked[1]
        formation = str(proposal.get("formation") or self._formation(starter_ids, event_rows))
        expected_points = sum(
            float(event_rows[element]["expected_points"]) for element in starter_ids
        ) + float(event_rows[captain_id]["expected_points"])
        all_items = {
            element: self._player_item(event_rows[element], element) for element in selected_ids
        }
        squad_starters = [
            self._role_item(all_items[element], element, captain_id, vice_id)
            for element in starter_ids
        ]
        squad_bench = [
            self._role_item(all_items[element], element, captain_id, vice_id)
            for element in bench_ids
        ]
        budget = sum(float(item["price"]) for item in all_items.values())
        created_at = _utc_now()
        image_id = str(proposal.get("source_image_id") or "upload")
        candidate_id = (
            "U-" + hashlib.sha256(f"{image_id}:{sorted(selected_ids)}".encode()).hexdigest()[:10]
        )
        receipt_id = (
            "upload-v1-" + hashlib.sha256(f"{image_id}:{created_at}".encode()).hexdigest()[:16]
        )
        payload = {
            "created_at": created_at,
            "decision_status": "confirmed-local-draft",
            "deadline_rule": self._published_payload()["deadline_rule"],
            "workspace_candidate": {
                "source": "uploaded",
                "source_label": "Confirmed screenshot draft",
                "confirmed": True,
                "requires_confirmation": False,
                "parent_candidate_id": self._current_candidate_id(),
                "locked_player_ids": selected_ids,
                "risk_profile": "safer",
                "horizon": 1,
                "constraints": {"source_image_id": image_id},
                "receipt_id": receipt_id,
            },
            "decision": {
                "candidate": {
                    "candidate_id": candidate_id,
                    "display_name": f"{formation} · uploaded draft",
                    "lineups": {
                        "1": {
                            "starters": starter_ids,
                            "bench_order": bench_ids,
                            "captain": captain_id,
                            "vice_captain": vice_id,
                            "formation": formation,
                            "expected_points": expected_points,
                        }
                    },
                },
                "squad": {
                    "formation": formation,
                    "budget_spent": round(budget, 1),
                    "bank": round(100.0 - budget, 1),
                    "starters": squad_starters,
                    "bench": squad_bench,
                },
            },
        }
        _atomic_json(self.active_decision_path, payload)
        return candidate_id

    def adopt_mcp_snapshot(self, snapshot: Mapping[str, Any]) -> str:
        if snapshot.get("status") != "connected":
            raise PreseasonSquadError(
                "mcp_not_authenticated", "Authenticate the local FPL MCP server before syncing."
            )
        raw_picks = snapshot.get("picks")
        if not isinstance(raw_picks, list) or len(raw_picks) != 15:
            raise PreseasonSquadError(
                "mcp_squad_invalid", "The MCP snapshot did not contain a complete 15-player squad."
            )
        captain = next((int(row["element"]) for row in raw_picks if row.get("is_captain")), None)
        vice = next((int(row["element"]) for row in raw_picks if row.get("is_vice_captain")), None)
        proposal_players = [
            {
                "source_text": str(row.get("name") or row["element"]),
                "squad_role": "starter" if int(row["position"]) <= 11 else "bench",
                "order": (
                    int(row["position"])
                    if int(row["position"]) <= 11
                    else int(row["position"]) - 11
                ),
                "player_id": int(row["element"]),
            }
            for row in raw_picks
        ]
        analysis = {
            "team_valid": True,
            "proposal": {
                "source_image_id": f"mcp-entry-{snapshot.get('entry_id', 'local')}",
                "formation": None,
                "players": proposal_players,
                "captain_player_id": captain,
                "vice_captain_player_id": vice,
            },
        }
        candidate_id = self.adopt_upload(analysis)
        payload = self.current_payload()
        observed_at = str(snapshot.get("observed_at") or _utc_now())
        entry_id = int(snapshot["entry_id"])
        squad_identity = [
            {
                "element": int(row["element"]),
                "position": int(row["position"]),
                "captain": bool(row.get("is_captain")),
                "vice_captain": bool(row.get("is_vice_captain")),
            }
            for row in sorted(raw_picks, key=lambda item: int(item["position"]))
        ]
        candidate_id = (
            "M-"
            + hashlib.sha256(
                json.dumps(
                    {"entry_id": entry_id, "picks": squad_identity},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()[:10]
        )
        payload["created_at"] = observed_at
        payload["decision_status"] = "synced-manager-state"
        payload["decision"]["candidate"]["candidate_id"] = candidate_id
        payload["decision"]["candidate"]["display_name"] = (
            f"{payload['decision']['squad']['formation']} · synced FPL squad"
        )
        payload["workspace_candidate"].update(
            {
                "source": "connected",
                "source_label": "Synced from authenticated FPL",
                "confirmed": True,
                "requires_confirmation": False,
                "locked_player_ids": [],
                "constraints": {"entry_id": entry_id},
            }
        )
        if snapshot.get("squad_value") is not None:
            payload["decision"]["squad"]["budget_spent"] = round(
                float(snapshot["squad_value"]) / 10.0, 1
            )
        if snapshot.get("bank") is not None:
            payload["decision"]["squad"]["bank"] = round(float(snapshot["bank"]) / 10.0, 1)
        payload["manager_context"] = {
            "entry_id": entry_id,
            "free_transfers": snapshot.get("free_transfers"),
            "transfer_cost": snapshot.get("transfer_cost"),
            "chips": snapshot.get("chips", []),
            "observed_at": observed_at,
        }
        _atomic_json(self.active_decision_path, payload)
        return candidate_id

    def critique(self, payload: Mapping[str, Any] | None = None) -> SquadCritique:
        current = dict(payload or self.current_payload())
        published = self._published_payload()
        squad = current["decision"]["squad"]
        lineup = current["decision"]["candidate"]["lineups"]["1"]
        meta = current.get("workspace_candidate") or {}
        players = list(squad["starters"]) + list(squad["bench"])
        published_squad = published["decision"]["squad"]
        published_players = list(published_squad["starters"]) + list(published_squad["bench"])
        player_ids = [int(row["element"]) for row in players]
        current_by_id = {int(row["element"]): row for row in players}
        published_by_id = {int(row["element"]): row for row in published_players}
        current_only_ids = sorted(set(current_by_id) - set(published_by_id))
        published_only_ids = sorted(set(published_by_id) - set(current_by_id))
        rows, _ = _player_rows(self.forecast_path)
        forecasts = {
            int(row["element"]): row
            for row in rows
            if int(row["event_number"]) == 1 and int(row["element"]) in player_ids
        }
        benchmark = float(published["decision"]["candidate"]["lineups"]["1"]["expected_points"])
        expected = float(lineup["expected_points"])
        delta = expected - benchmark
        candidate_for_gate = dict(current["decision"]["candidate"])
        candidate_for_gate.setdefault("selected", player_ids)
        role_risks = candidate_publication_role_risks(
            candidate_for_gate,
            forecasts,
            forecasts,
        )
        risky_ids = {int(risk["element"]) for risk in role_risks}
        bench_spend = sum(float(row["price"]) for row in squad["bench"])
        starter_ids = {int(value) for value in lineup["starters"]}
        starters = [row for row in players if int(row["element"]) in starter_ids]
        weakest = min(
            starters,
            key=lambda row: float(forecasts[int(row["element"])]["robust_points"]),
        )
        robust_rank = sorted(
            starters,
            key=lambda row: float(forecasts[int(row["element"])]["robust_points"]),
            reverse=True,
        )
        strengths: list[dict[str, Any]] = [
            {
                "code": "legal_budget",
                "title": "Legal £100m structure",
                "detail": (
                    f"The draft spends £{float(squad['budget_spent']):.1f}m and leaves "
                    f"£{float(squad['bank']):.1f}m available."
                ),
                "player_ids": [],
            }
        ]
        if not role_risks:
            strengths.append(
                {
                    "code": "minutes_floor",
                    "title": "Actionable roles clear the safety floor",
                    "detail": "The XI, armbands and ordered outfield bench clear their role-specific minutes and appearance gates.",
                    "player_ids": [],
                }
            )
        if delta >= -1.0:
            strengths.append(
                {
                    "code": "benchmark_close",
                    "title": "Close to the published benchmark",
                    "detail": f"The current GW1 projection is {delta:+.2f} points versus the robust baseline.",
                    "player_ids": [],
                }
            )
        if not current_only_ids and not published_only_ids:
            strengths.append(
                {
                    "code": "published_squad_match",
                    "title": "Exact 15-player benchmark match",
                    "detail": "This squad contains the same 15 players as the active robust benchmark.",
                    "player_ids": player_ids,
                }
            )

        concerns: list[dict[str, Any]] = []
        if role_risks:
            names = ", ".join(str(risk["player_name"]) for risk in role_risks[:3])
            details = "; ".join(
                f"{risk['player_name']} ({risk.get('action', 'premium capital')}: "
                f"{float(risk['expected_minutes']):.1f} expected minutes, "
                f"{float(risk['p_play']) * 100:.0f}% plays)"
                for risk in role_risks[:3]
            )
            concerns.append(
                {
                    "code": "role_integrity_risk",
                    "title": "Actionable roles need changing",
                    "detail": f"{names} fail a role-specific safety gate: {details}.",
                    "player_ids": sorted(risky_ids),
                }
            )
        if bench_spend > 22.5:
            concerns.append(
                {
                    "code": "bench_spend",
                    "title": "Value is tied up on the bench",
                    "detail": f"The bench costs £{bench_spend:.1f}m; test whether that money improves a starter.",
                    "player_ids": [int(row["element"]) for row in squad["bench"]],
                }
            )
        if delta < -1.0:
            concerns.append(
                {
                    "code": "projection_gap",
                    "title": "Projection gap to the baseline",
                    "detail": f"This XI trails the published robust squad by {abs(delta):.2f} projected GW1 points.",
                    "player_ids": [],
                }
            )
        if current_only_ids or published_only_ids:
            current_names = (
                ", ".join(str(current_by_id[element]["name"]) for element in current_only_ids)
                or "no alternatives"
            )
            benchmark_names = (
                ", ".join(str(published_by_id[element]["name"]) for element in published_only_ids)
                or "no alternatives"
            )
            concerns.append(
                {
                    "code": "published_squad_delta",
                    "title": "The robust benchmark uses a different squad structure",
                    "detail": (
                        f"This squad contains {current_names}; the active benchmark instead "
                        f"contains {benchmark_names}. Review those full-squad differences "
                        "alongside the projection edge rather than judging only the XI."
                    ),
                    "player_ids": [*current_only_ids, *published_only_ids],
                }
            )
        captain_id = int(lineup["captain"])
        if captain_id != int(robust_rank[0]["element"]):
            concerns.append(
                {
                    "code": "captain_alternative",
                    "title": "Captaincy has a stronger marginal option",
                    "detail": f"{robust_rank[0]['name']} ranks above the current captain on robust GW1 points.",
                    "player_ids": [captain_id, int(robust_rank[0]["element"])],
                }
            )

        source = str(meta.get("source") or "generated")
        if concerns and (len(concerns) >= 2 or delta < -2.0):
            status = "needs_attention"
            headline = "There is a useful core, but the draft has decisions to resolve."
        elif concerns:
            status = "promising"
            headline = "The structure is credible with one clear review point."
        else:
            status = "strong"
            headline = "This is a strong current candidate, subject to deadline refresh."
        summary = (
            "The uploaded draft is being compared with the same forecasts and rules as generated "
            "squads."
            if source == "uploaded"
            else "This candidate is legal and scored against the published robust baseline."
        )
        questions = [
            f"Why is {weakest['name']} the weakest starter in this squad?",
            f"Should I captain {robust_rank[0]['name']} for GW1?",
            "What changes if I prioritise the first five gameweeks?",
        ]
        if current_only_ids or published_only_ids:
            questions.insert(
                0,
                (
                    "Why does the benchmark use "
                    + ", ".join(
                        str(published_by_id[element]["name"]) for element in published_only_ids
                    )
                    + " instead of "
                    + ", ".join(str(current_by_id[element]["name"]) for element in current_only_ids)
                    + "?"
                ),
            )
        if source == "uploaded":
            questions.insert(0, "What are the two best changes to my uploaded draft?")
        return SquadCritique.model_validate(
            {
                "status": status,
                "headline": headline,
                "summary": summary,
                "benchmark_expected_points": round(benchmark, 2),
                "expected_points_delta": round(delta, 2),
                "strengths": strengths,
                "concerns": concerns,
                "suggested_questions": questions[:4],
            }
        )

    def handle_optimize_squad(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if int(arguments["manager_id"]) != 1 or int(arguments["start_event"]) != 1:
            raise PreseasonSquadError(
                "unsupported_context",
                "The local preseason optimiser currently supports manager 1 and GW1.",
            )
        raw = arguments.get("constraints")
        constraints = dict(raw) if isinstance(raw, Mapping) else {}
        legacy_policy = str(constraints.get("policy") or "")
        risk_profile = constraints.get("risk_profile")
        if not risk_profile:
            folded_policy = legacy_policy.casefold()
            if "upside" in folded_policy:
                risk_profile = "upside"
            elif "safe" in folded_policy or "robust" in folded_policy:
                risk_profile = "safer"
            else:
                risk_profile = "balanced"
        request = GenerateSquadRequest.model_validate(
            {
                "risk_profile": risk_profile,
                "horizon": int(arguments.get("horizon", 5)),
                "locked_player_ids": constraints.get("locked_player_ids", []),
                "excluded_player_ids": constraints.get("excluded_player_ids", []),
                "club_minimums": constraints.get("club_minimums", []),
            }
        )
        result = self.generate(request)
        payload = self.current_payload()
        squad = payload["decision"]["squad"]

        def roster_item(player: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "player_id": int(player["element"]),
                "name": str(player["name"]),
                "position": str(player["position"]),
                "team_short_name": str(player["team"]),
                "captain": bool(player.get("captain")),
                "vice_captain": bool(player.get("vice_captain")),
            }

        return {
            "schema_version": "squad-generation-v1",
            "candidate_id": result.candidate_id,
            "receipt_id": result.receipt_id,
            "formation": result.formation,
            "gw1_expected_points": result.expected_points,
            "budget_spent": result.budget_spent,
            "bank": result.bank,
            "changed_player_ids": result.changed_player_ids,
            "duration_ms": result.duration_ms,
            "planning_horizon_gameweeks": request.horizon,
            "applied_constraints": request.model_dump(mode="json"),
            "starters": [roster_item(player) for player in squad["starters"]],
            "bench": [roster_item(player) for player in squad["bench"]],
            "message": result.message,
            "requires_confirmation": True,
            "workspace_changed": True,
        }

    def handle_search_players(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        query = str(arguments["query"]).strip().casefold()
        if not query:
            raise PreseasonSquadError("empty_query", "Enter part of a player name.")
        position = str(arguments.get("position") or "").upper()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT p.id,
                       trim(coalesce(p.first_name, '') || ' ' || coalesce(p.second_name, '')),
                       p.web_name,
                       CASE p.element_type
                           WHEN 1 THEN 'GK' WHEN 2 THEN 'DEF'
                           WHEN 3 THEN 'MID' WHEN 4 THEN 'FWD'
                       END,
                       t.name, t.short_name, p.now_cost, p.status, p.snapshot_at
                FROM fpl_current_players p
                JOIN fpl_current_teams t ON t.id = p.team
                WHERE p.can_select AND NOT p.removed
                """
            ).fetchall()
        candidates = []
        for row in rows:
            row_position = str(row[3])
            if position and row_position != position:
                continue
            full_name = str(row[1]).strip()
            web_name = str(row[2])
            folded = f"{full_name} {web_name}".casefold()
            contains = query in folded
            score = max(
                SequenceMatcher(None, query, full_name.casefold()).ratio(),
                SequenceMatcher(None, query, web_name.casefold()).ratio(),
            )
            if not contains and score < 0.52:
                continue
            candidates.append(
                {
                    "player_id": int(row[0]),
                    "name": full_name or web_name,
                    "web_name": web_name,
                    "position": row_position,
                    "team": str(row[4]),
                    "team_short_name": str(row[5]),
                    "price": float(row[6]) / 10.0,
                    "status": str(row[7]),
                    "match_confidence": round(1.0 if contains else score, 3),
                    "snapshot_at": str(row[8]),
                }
            )
        candidates.sort(key=lambda item: (-float(item["match_confidence"]), str(item["name"])))
        return {
            "schema_version": "player-search-v1",
            "query": arguments["query"],
            "candidates": candidates[:8],
            "exact_match": len(candidates) == 1 and candidates[0]["match_confidence"] == 1.0,
        }

    def _generated_payload(
        self,
        solution: Mapping[str, Any],
        *,
        candidate_id: str,
        receipt_id: str,
        created_at: str,
        constraints: Mapping[str, Any],
        parent_candidate_id: str | None,
        role_integrity_risks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lineup = solution["lineups"][1]
        captain = int(lineup["captain"])
        vice = int(lineup["vice_captain"])
        items = {
            int(element): self._player_item(
                solution["by_player"][element][1], int(element), solution["player_meta"][element]
            )
            for element in solution["selected"]
        }
        starter_ids = sorted(
            (int(value) for value in lineup["starters"]),
            key=lambda element: (
                POSITION_ORDER[str(items[element]["position"])],
                -float(items[element]["expected_points"]),
            ),
        )
        bench_ids = [int(value) for value in lineup["bench_order"]]
        lineups = {
            str(event): {
                "starters": [int(value) for value in event_lineup["starters"]],
                "bench_order": [int(value) for value in event_lineup["bench_order"]],
                "captain": int(event_lineup["captain"]),
                "vice_captain": int(event_lineup["vice_captain"]),
                "formation": str(event_lineup["formation"]),
                "expected_points": float(event_lineup["expected_points"]),
            }
            for event, event_lineup in solution["lineups"].items()
        }
        budget = float(solution["budget"]) / 10.0
        return {
            "created_at": created_at,
            "decision_status": "provisional-scenario",
            "deadline_rule": self._published_payload()["deadline_rule"],
            "workspace_candidate": {
                "source": "generated",
                "source_label": "Custom constrained build",
                "confirmed": False,
                "requires_confirmation": True,
                "parent_candidate_id": parent_candidate_id,
                "locked_player_ids": list(constraints.get("locked_player_ids", [])),
                "risk_profile": constraints.get("risk_profile", "balanced"),
                "horizon": constraints.get("horizon", 5),
                "constraints": dict(constraints),
                "receipt_id": receipt_id,
                "role_integrity_risks": role_integrity_risks,
            },
            "decision": {
                "candidate": {
                    "candidate_id": candidate_id,
                    "display_name": f"{lineup['formation']} · custom scenario",
                    "lineups": lineups,
                },
                "squad": {
                    "formation": str(lineup["formation"]),
                    "budget_spent": round(budget, 1),
                    "bank": round(100.0 - budget, 1),
                    "starters": [
                        self._role_item(items[element], element, captain, vice)
                        for element in starter_ids
                    ],
                    "bench": [
                        self._role_item(items[element], element, captain, vice)
                        for element in bench_ids
                    ],
                },
            },
        }

    @staticmethod
    def _score(rows: list[dict[str, Any]], risk_profile: str) -> np.ndarray:
        if risk_profile == "safer":
            return np.asarray([float(row["robust_points"]) for row in rows], dtype=np.float64)
        if risk_profile == "upside":
            return np.asarray(
                [
                    float(row["expected_points"]) + 0.18 * max(float(row["model_sd"]), 0.0)
                    for row in rows
                ],
                dtype=np.float64,
            )
        return np.asarray([float(row["expected_points"]) for row in rows], dtype=np.float64)

    @staticmethod
    def _player_item(
        forecast: Mapping[str, Any],
        element: int,
        meta: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = meta or forecast
        return {
            "element": element,
            "name": str(source["player_name"]),
            "team": str(source["team_short_name"]),
            "position": str(source["position"]),
            "price": float(source["market_price"]) / 10.0,
            "expected_points": float(forecast["expected_points"]),
            "robust_points": float(forecast["robust_points"]),
            "p_play": float(forecast["p_play"]),
            "uncertainty": float(forecast["epistemic_uncertainty"]),
            "cold_start": bool(forecast["cold_start"]),
            "news": str(forecast.get("news") or ""),
        }

    @staticmethod
    def _role_item(
        item: Mapping[str, Any], element: int, captain: int, vice: int
    ) -> dict[str, Any]:
        return {
            **dict(item),
            "captain": element == captain,
            "vice_captain": element == vice,
        }

    @staticmethod
    def _formation(starter_ids: list[int], rows: Mapping[int, Mapping[str, Any]]) -> str:
        counts = Counter(str(rows[element]["position"]) for element in starter_ids)
        return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"

    def _current_player_ids(self) -> list[int]:
        payload = self.current_payload()
        squad = payload["decision"]["squad"]
        return [int(row["element"]) for row in squad["starters"] + squad["bench"]]

    def _current_candidate_id(self) -> str | None:
        try:
            return str(self.current_payload()["decision"]["candidate"]["candidate_id"])
        except (KeyError, TypeError, PreseasonSquadError):
            return None

    def _published_payload(self) -> dict[str, Any]:
        try:
            return json.loads(self.published_decision_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreseasonSquadError(
                "published_decision_unavailable",
                "The published robust GW1 recommendation is unavailable.",
            ) from exc

    def _team_ids(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, short_name FROM fpl_current_teams").fetchall()
        return {str(row[1]).upper(): int(row[0]) for row in rows}

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if not self.database_path.exists():
            raise PreseasonSquadError(
                "catalog_unavailable", "The current FPL player catalog is unavailable."
            )
        return duckdb.connect(str(self.database_path), read_only=True)
