from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fplagent_data.http import sha256_file
from fplagent_llm.paths import ROOT
from fplagent_llm.runtime_tools import (
    DEFAULT_COMPONENTS,
    DEFAULT_DECISION,
    DEFAULT_FORECASTS,
    CaptainComparisonService,
    LocalManagerRepository,
)

from .models import (
    CapabilityView,
    CaptainInsight,
    DecisionView,
    EvidenceItem,
    FixtureView,
    FreshnessView,
    HorizonEvent,
    PhaseView,
    PlayerView,
    SquadView,
    UserView,
    WeeklyActionView,
    WeeklyDecisionView,
    WeeklyTransferView,
    WorkspaceView,
)
from .preseason import DEFAULT_ACTIVE_DECISION, PreseasonSquadService
from .profile import DEFAULT_PROFILE_PATH, ManagerProfileStore

DEFAULT_DATABASE = ROOT / "data" / "fpl_history.duckdb"
DEFAULT_DEADLINE_STATUS = ROOT / "data" / "manifests" / "fpl-deadline-evidence-status.json"
DEFAULT_WEEKLY_DECISION = ROOT / "data" / "decisions" / "2026-27-weekly-current.json"
DEFAULT_REFRESH_STATE = ROOT / "data" / "web" / "state" / "workspace-refresh.json"


class WorkspaceBuildError(RuntimeError):
    """The local read model could not be assembled from versioned artifacts."""


class WorkspaceBuilder:
    def __init__(
        self,
        *,
        decision_path: Path = DEFAULT_DECISION,
        forecast_path: Path = DEFAULT_FORECASTS,
        component_path: Path = DEFAULT_COMPONENTS,
        database_path: Path = DEFAULT_DATABASE,
        manager_id: int = 1,
        active_decision_path: Path | None = DEFAULT_ACTIVE_DECISION,
        profile_path: Path = DEFAULT_PROFILE_PATH,
        deadline_status_path: Path | None = DEFAULT_DEADLINE_STATUS,
        weekly_decision_path: Path | None = DEFAULT_WEEKLY_DECISION,
        refresh_state_path: Path | None = None,
    ) -> None:
        self.decision_path = decision_path
        self.forecast_path = forecast_path
        self.component_path = component_path
        self.database_path = database_path
        self.manager_id = manager_id
        self.active_decision_path = active_decision_path
        self.profile_path = profile_path
        self.deadline_status_path = deadline_status_path
        self.weekly_decision_path = weekly_decision_path
        self.refresh_state_path = refresh_state_path

    def build(self, *, now: datetime | None = None) -> WorkspaceView:
        current = now or datetime.now(tz=UTC)
        if current.tzinfo is None:
            raise ValueError("workspace time must include a timezone")
        resolved_decision_path = self._resolved_decision_path()
        payload = self._read_decision(resolved_decision_path)
        candidate_meta = payload.get("workspace_candidate") or {}
        risk_profile = str(candidate_meta.get("risk_profile") or "safer")
        captain_policy = "robust" if risk_profile == "safer" else "expected_points"
        managers = LocalManagerRepository(resolved_decision_path, manager_id=self.manager_id)
        state = managers.get_state(self.manager_id, current.isoformat())
        captain_result = CaptainComparisonService(
            managers,
            self.forecast_path,
            self.component_path,
        ).compare(
            {
                "manager_id": self.manager_id,
                "event": 1,
                "risk_policy": captain_policy,
                "as_of": current.isoformat(),
            }
        )
        squad_payload = payload["decision"]["squad"]
        all_rows = list(squad_payload["starters"]) + list(squad_payload["bench"])
        player_ids = [int(row["element"]) for row in all_rows]
        forecasts = self._forecasts(player_ids, event=1)
        fixtures = self._fixtures(event=1)
        teams = self._teams()
        lineup = payload["decision"]["candidate"]["lineups"]["1"]

        starters = [
            self._player_view(row, "starter", index, forecasts, fixtures, teams)
            for index, row in enumerate(squad_payload["starters"], start=1)
        ]
        bench = [
            self._player_view(row, "bench", index, forecasts, fixtures, teams)
            for index, row in enumerate(squad_payload["bench"], start=1)
        ]
        names = {row.player_id: row.name for row in starters + bench}
        phase = self._phase(current, self._event_calendar())
        weekly_decision = self._weekly_decision(
            event=phase.decision_event or phase.event
        )
        forecast_observed_at = datetime.fromisoformat(str(captain_result["forecast_observed_at"]))
        if forecast_observed_at.tzinfo is None:
            forecast_observed_at = forecast_observed_at.replace(tzinfo=UTC)
        forecast_model_created_at = datetime.fromisoformat(
            str(captain_result["forecast_model_created_at"])
        )
        if forecast_model_created_at.tzinfo is None:
            forecast_model_created_at = forecast_model_created_at.replace(tzinfo=UTC)
        age_seconds = max(0.0, (current - forecast_observed_at).total_seconds())
        evidence_gate = self._deadline_evidence_status()
        evidence_blocked = bool(evidence_gate and not evidence_gate.get("publishable"))
        refresh_required = bool(state["refresh_required"]) or evidence_blocked
        freshness_status = "stale" if evidence_blocked else self._freshness_status(age_seconds)
        captain = captain_result["captain"]
        vice = captain_result["vice_captain"]
        stored_captain = captain_result["stored_receipt"]
        recommended_lineup = captain_result["recommended_lineup"]
        source = str(candidate_meta.get("source") or "generated")
        if source not in {"generated", "uploaded", "connected"}:
            source = "generated"
        confirmed = bool(candidate_meta.get("confirmed", state["confirmed"]))
        requires_confirmation = bool(
            candidate_meta.get("requires_confirmation", state["requires_confirmation"])
        )
        critique = PreseasonSquadService(
            published_decision_path=self.decision_path,
            active_decision_path=resolved_decision_path,
            database_path=self.database_path,
        ).critique(payload)
        profile = ManagerProfileStore(self.profile_path).get()
        recommendation_parts: list[str] = []
        if not recommended_lineup["aligned_with_current_xi"]:
            recommendation_parts.append(
                "Start "
                + ", ".join(str(value) for value in recommended_lineup["promoted_player_names"])
                + " and bench "
                + ", ".join(str(value) for value in recommended_lineup["benched_player_names"])
                + "."
            )
        if stored_captain["captaincy_aligned"]:
            recommendation_parts.append(
                f"Keep {captain['name']} captain with {vice['name']} vice-captain."
            )
        else:
            recommendation_parts.append(
                f"Move the armband from {stored_captain['captain_name']} to "
                f"{captain['name']}, with {vice['name']} as the modelled vice-captain."
            )
        decision_evidence = [
            EvidenceItem(
                label=self._evidence_label(str(source_item["path"])),
                path=str(source_item["path"]),
                sha256=str(source_item["sha256"]),
            )
            for source_item in captain_result["sources"]
        ]
        if weekly_decision.receipt_path and weekly_decision.receipt_sha256:
            decision_evidence.append(
                EvidenceItem(
                    label="Weekly action receipt",
                    path=weekly_decision.receipt_path,
                    sha256=weekly_decision.receipt_sha256,
                )
            )
        refresh_evidence = self._refresh_evidence()
        if refresh_evidence is not None:
            decision_evidence.append(refresh_evidence)

        return WorkspaceView(
            generated_at=current.isoformat(),
            user=UserView(
                user_id="local-lewis",
                display_name=profile.display_name,
                manager_id=self.manager_id,
                connection_state=source,
                fpl_entry_id=profile.fpl_entry_id,
                sync_state=profile.sync_state,
                last_synced_at=profile.last_synced_at,
            ),
            phase=phase,
            freshness=FreshnessView(
                status=freshness_status,
                observed_at=forecast_observed_at.isoformat(),
                model_generated_at=forecast_model_created_at.isoformat(),
                squad_synced_at=profile.last_synced_at,
                age_seconds=age_seconds,
                refresh_required=refresh_required,
                message=(
                    self._deadline_evidence_message(evidence_gate)
                    if evidence_blocked
                    else str(state["refresh_reason"])
                ),
            ),
            squad=SquadView(
                source=source,
                confirmed=confirmed,
                requires_confirmation=requires_confirmation,
                formation=str(squad_payload["formation"]),
                budget_spent=float(squad_payload["budget_spent"]),
                bank=float(squad_payload["bank"]),
                expected_points=round(float(lineup["expected_points"]), 2),
                candidate_id=str(payload["decision"]["candidate"]["candidate_id"]),
                source_label=str(
                    candidate_meta.get("source_label") or "Published robust recommendation"
                ),
                parent_candidate_id=(
                    str(candidate_meta["parent_candidate_id"])
                    if candidate_meta.get("parent_candidate_id")
                    else None
                ),
                locked_player_ids=[
                    int(value) for value in candidate_meta.get("locked_player_ids", [])
                ],
                starters=starters,
                bench=bench,
            ),
            critique=critique,
            decision=DecisionView(
                status="confirmed" if confirmed else "provisional",
                captain=CaptainInsight(
                    captain_player_id=int(captain["player_id"]),
                    captain_name=str(captain["name"]),
                    vice_captain_player_id=int(vice["player_id"]),
                    vice_captain_name=str(vice["name"]),
                    current_captain_player_id=int(stored_captain["captain_player_id"]),
                    current_captain_name=str(stored_captain["captain_name"]),
                    current_vice_captain_player_id=int(stored_captain["vice_captain_player_id"]),
                    current_vice_captain_name=str(stored_captain["vice_captain_name"]),
                    recommendation_aligned=bool(stored_captain["captaincy_aligned"]),
                    lineup_recommendation_aligned=bool(
                        recommended_lineup["aligned_with_current_xi"]
                    ),
                    recommended_formation=str(recommended_lineup["formation"]),
                    promoted_player_ids=[
                        int(value) for value in recommended_lineup["promoted_player_ids"]
                    ],
                    promoted_player_names=[
                        str(value) for value in recommended_lineup["promoted_player_names"]
                    ],
                    benched_player_ids=[
                        int(value) for value in recommended_lineup["benched_player_ids"]
                    ],
                    benched_player_names=[
                        str(value) for value in recommended_lineup["benched_player_names"]
                    ],
                    evidence_status=str(captain_result["evidence_status"]),
                    score_metric=str(captain_result["score_metric"]),
                    score_edge=float(captain_result["score_edge"]),
                    receipt_id=str(captain_result["receipt_id"]),
                    main_risk=str(captain_result["main_risk"]),
                ),
                horizon=self._horizon(payload, names),
                evidence=decision_evidence,
                recommendation=" ".join(recommendation_parts),
                caveat=str(payload["deadline_rule"]),
                weekly=weekly_decision,
            ),
            capabilities=CapabilityView(),
        )

    @staticmethod
    def _freshness_status(age_seconds: float) -> str:
        if age_seconds > 86_400:
            return "stale"
        if age_seconds > 21_600:
            return "attention"
        return "fresh"

    def _resolved_decision_path(self) -> Path:
        if self.active_decision_path is not None and self.active_decision_path.exists():
            return self.active_decision_path
        return self.decision_path

    def _deadline_evidence_status(self) -> dict[str, Any] | None:
        if self.deadline_status_path is None or not self.deadline_status_path.is_file():
            return None
        try:
            value = json.loads(self.deadline_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "publishable": False,
                "issues": ["The deadline evidence receipt cannot be read."],
            }
        return value if isinstance(value, dict) else None

    def _refresh_evidence(self) -> EvidenceItem | None:
        if self.refresh_state_path is None or not self.refresh_state_path.is_file():
            return None
        try:
            state = json.loads(self.refresh_state_path.read_text(encoding="utf-8"))
            if state.get("status") not in {"published", "reused"}:
                return None
            receipt_path = Path(str(state["receipt_path"]))
            expected_sha256 = str(state["receipt_sha256"])
            if not receipt_path.is_file() or sha256_file(receipt_path) != expected_sha256:
                return None
            return EvidenceItem(
                label="App-open decision pipeline",
                path=str(receipt_path),
                sha256=expected_sha256,
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _weekly_action_label(route_type: str, transfer_count: int, points_cost: int) -> str:
        if route_type == "roll":
            return "Roll the transfer"
        if route_type == "one_free_transfer":
            return "Make one free transfer"
        if route_type == "multi_free_transfer":
            return f"Use {transfer_count} free transfers"
        if route_type == "paid_transfer":
            return f"Make {transfer_count} transfers for a {points_cost}-point hit"
        raise ValueError(f"Unknown weekly route type: {route_type}")

    @classmethod
    def _weekly_action_view(cls, summary: dict[str, Any]) -> WeeklyActionView:
        route_type = str(summary["route_type"])
        transfer_count = int(summary["transfer_count"])
        points_cost = int(summary["incremental_points_cost"])
        return WeeklyActionView(
            action_id=str(summary["action_id"]),
            route_type=route_type,
            label=cls._weekly_action_label(route_type, transfer_count, points_cost),
            transfer_count=transfer_count,
            transfers=[
                WeeklyTransferView(
                    outgoing_player_id=int(transfer["outgoing_player_id"]),
                    outgoing_name=str(
                        transfer.get("outgoing_name") or f"#{transfer['outgoing_player_id']}"
                    ),
                    incoming_player_id=int(transfer["incoming_player_id"]),
                    incoming_name=str(
                        transfer.get("incoming_name") or f"#{transfer['incoming_player_id']}"
                    ),
                    incoming_price=float(transfer["incoming_price"]) / 10.0,
                )
                for transfer in summary.get("transfers", [])
            ],
            formation=str(summary["formation"]),
            captain_player_id=int(summary["captain_player_id"]),
            captain_name=str(
                summary.get("captain_name") or f"#{summary['captain_player_id']}"
            ),
            vice_captain_player_id=int(summary["vice_captain_player_id"]),
            vice_captain_name=str(
                summary.get("vice_captain_name") or f"#{summary['vice_captain_player_id']}"
            ),
            incremental_points_cost=points_cost,
            next_free_transfers=(
                int(summary["next_free_transfers"])
                if summary.get("next_free_transfers") is not None
                else None
            ),
            terminal_free_transfers=(
                int(summary["terminal_free_transfers"])
                if summary.get("terminal_free_transfers") is not None
                else None
            ),
            terminal_transfer_value=float(summary.get("terminal_transfer_value") or 0.0),
        )

    def _weekly_decision(self, *, event: int) -> WeeklyDecisionView:
        path = self.weekly_decision_path
        if path is None or not path.is_file():
            return WeeklyDecisionView(
                status="not_available",
                event=event,
                promotion_status="awaiting_complete_manager_state",
                explanation=(
                    "A weekly roll-versus-transfer receipt will appear after the authenticated "
                    "manager state and current forecasts are complete."
                ),
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            decision_event = int(payload["decision_event"])
            summaries = {
                str(summary["action_id"]): summary for summary in payload["action_summaries"]
            }
            selected_id = str(payload["selected_action_id"])
            selected = self._weekly_action_view(summaries[selected_id])
            rejected_row = payload.get("strongest_rejected")
            rejected = (
                self._weekly_action_view(summaries[str(rejected_row["action_id"])])
                if isinstance(rejected_row, dict) and rejected_row.get("action_id")
                else None
            )
            weights = {
                str(name): float(weight)
                for name, weight in payload["method"]["scenario_weights"].items()
            }
            scenario_metrics = payload["scenario_metrics_by_action"]
            selected_metrics = {
                name: scenario_metrics[name][selected_id] for name in weights
            }
            central_name = str(
                payload["promotion_gate"].get("central_scenario")
                or max(weights, key=weights.get)
            )
            central = selected_metrics[central_name]
            expected_gain = sum(
                weights[name] * float(metric["mean_delta_to_roll"])
                for name, metric in selected_metrics.items()
            )
            beat_probability = sum(
                weights[name] * float(metric["beat_roll_probability"])
                for name, metric in selected_metrics.items()
            )
            worst_gain = min(
                float(metric["mean_delta_to_roll"])
                for metric in selected_metrics.values()
            )
            promotion_status = str(payload["promotion_gate"]["status"])
            if selected.route_type == "roll" and promotion_status == "roll_is_robust_leader":
                explanation = "Rolling has the lowest robust regret across every model world."
            elif selected.route_type == "roll":
                explanation = (
                    "The leading move did not clear the uncertainty gate, so the safer action is "
                    "to preserve the transfer."
                )
            else:
                explanation = (
                    "This route cleared the after-cost gain, scenario-stability and paired "
                    "uncertainty gates."
                )
            return WeeklyDecisionView(
                status="ready",
                event=decision_event,
                created_at=str(payload["created_at"]),
                selected=selected,
                strongest_rejected=rejected,
                expected_gain_vs_roll=expected_gain,
                confidence_low=float(central["delta_to_roll_95ci_low"]),
                confidence_high=float(central["delta_to_roll_95ci_high"]),
                beat_roll_probability=beat_probability,
                worst_scenario_gain=worst_gain,
                robust_regret=float(payload["selected_robust_metrics"]["robust_regret"]),
                promotion_status=promotion_status,
                explanation=explanation,
                receipt_path=str(path),
                receipt_sha256=sha256_file(path),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return WeeklyDecisionView(
                status="blocked",
                event=event,
                promotion_status="invalid_weekly_receipt",
                explanation=f"The weekly decision receipt cannot be trusted: {exc}",
                receipt_path=str(path),
            )

    @staticmethod
    def _deadline_evidence_message(status: dict[str, Any] | None) -> str:
        issues = status.get("issues", []) if status else []
        if not isinstance(issues, list) or not issues:
            return "The current decision has not passed the deadline evidence gate."
        return "Decision refresh required: " + "; ".join(str(issue) for issue in issues[:2])

    def _read_decision(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["decision"]["candidate"]["lineups"]["1"]
            payload["deadline_rule"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise WorkspaceBuildError("the GW1 decision artifact is unavailable") from exc
        return payload

    def _forecasts(self, player_ids: list[int], event: int) -> dict[int, dict[str, Any]]:
        for path in (self.forecast_path, self.component_path):
            if not path.exists():
                raise WorkspaceBuildError(f"forecast artifact is unavailable: {path}")
        connection = duckdb.connect()
        try:
            rows = connection.execute(
                """
                SELECT f.element, f.team_id, f.team_short_name, f.expected_points,
                       f.robust_points, f.p_play, f.status, f.news,
                       coalesce(c.expected_minutes, 0.0)
                FROM read_parquet(?) f
                LEFT JOIN read_parquet(?) c USING (season, event_number, element)
                WHERE f.event_number = ?
                  AND f.element IN (SELECT * FROM unnest(?))
                """,
                [str(self.forecast_path), str(self.component_path), event, player_ids],
            ).fetchall()
        finally:
            connection.close()
        return {
            int(row[0]): {
                "team_id": int(row[1]),
                "team_short_name": str(row[2]),
                "expected_points": float(row[3]),
                "robust_points": float(row[4]),
                "p_play": float(row[5]),
                "status": str(row[6]),
                "news": str(row[7] or ""),
                "expected_minutes": float(row[8]),
            }
            for row in rows
        }

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if not self.database_path.exists():
            raise WorkspaceBuildError("the point-in-time FPL database is unavailable")
        return duckdb.connect(str(self.database_path), read_only=True)

    def _teams(self) -> dict[int, tuple[str, str]]:
        connection = self._connection()
        try:
            rows = connection.execute(
                "SELECT id, name, short_name FROM fpl_current_teams"
            ).fetchall()
        finally:
            connection.close()
        return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}

    def _fixtures(self, event: int) -> dict[int, FixtureView]:
        connection = self._connection()
        try:
            rows = connection.execute(
                """
                SELECT f.team_h, away.short_name, 'H', f.team_h_difficulty, f.kickoff_time
                FROM fpl_current_fixtures f
                JOIN fpl_current_teams away ON away.id = f.team_a
                WHERE f.event = ?
                UNION ALL
                SELECT f.team_a, home.short_name, 'A', f.team_a_difficulty, f.kickoff_time
                FROM fpl_current_fixtures f
                JOIN fpl_current_teams home ON home.id = f.team_h
                WHERE f.event = ?
                """,
                [event, event],
            ).fetchall()
        finally:
            connection.close()
        return {
            int(row[0]): FixtureView(
                opponent=str(row[1]),
                venue=str(row[2]),
                difficulty=int(row[3]),
                kickoff_time=str(row[4]),
                label=f"{row[1]} ({row[2]})",
            )
            for row in rows
        }

    def _event_calendar(self) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            rows = connection.execute(
                """
                SELECT id, name, deadline_time, finished, data_checked
                FROM fpl_current_events
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            raise WorkspaceBuildError("The official FPL event calendar is unavailable")
        return [
            {
                "event": int(row[0]),
                "name": str(row[1]),
                "deadline": str(row[2]),
                "finished": bool(row[3]),
                "data_checked": bool(row[4]),
            }
            for row in rows
        ]

    @staticmethod
    def _phase(now: datetime, events: list[dict[str, Any]]) -> PhaseView:
        if now.tzinfo is None:
            raise ValueError("phase time must include a timezone")
        calendar: list[tuple[dict[str, Any], datetime]] = []
        for row in events:
            deadline = datetime.fromisoformat(str(row["deadline"]))
            if deadline.tzinfo is None:
                raise WorkspaceBuildError("official event deadline must include a timezone")
            calendar.append((row, deadline.astimezone(UTC)))
        calendar.sort(key=lambda item: int(item[0]["event"]))
        upcoming = next(
            ((row, deadline) for row, deadline in calendar if now < deadline),
            None,
        )
        previous = next(
            (
                (row, deadline)
                for row, deadline in reversed(calendar)
                if now >= deadline
            ),
            None,
        )

        if upcoming is None:
            if previous is None:
                raise WorkspaceBuildError("official event calendar has no actionable event")
            row, deadline = previous
            event = int(row["event"])
            return PhaseView(
                phase="review",
                season="2026-27",
                event=event,
                label=f"GW{event} review",
                title="Review the season and score every frozen decision.",
                narrative=(
                    "The final deadline has passed. Attribute realised points and decision regret "
                    "against the prospective receipts."
                ),
                deadline=deadline.isoformat(),
                deadline_label="Season deadlines complete",
                decision_event=None,
                decision_deadline=None,
                primary_action="review",
                decision_modules=["submitted_team", "decision_review"],
            )

        upcoming_row, upcoming_deadline = upcoming
        upcoming_event = int(upcoming_row["event"])
        if upcoming_event == 1:
            delta_seconds = max(0, int((upcoming_deadline - now).total_seconds()))
            days, remainder = divmod(delta_seconds, 86_400)
            hours = remainder // 3_600
            return PhaseView(
                phase="preseason",
                season="2026-27",
                event=1,
                label="Pre-season · GW1 build",
                title="Build a squad that survives the opening run.",
                narrative=(
                    "Generate from the full player pool, import an existing draft, and test the "
                    "captain, bench and first transfers before the deadline."
                ),
                deadline=upcoming_deadline.isoformat(),
                deadline_label=f"{days}d {hours}h to deadline",
                decision_event=1,
                decision_deadline=upcoming_deadline.isoformat(),
                primary_action="generate_squad",
                decision_modules=["squad_builder", "screenshot_import", "captaincy"],
            )

        if previous is not None:
            previous_row, previous_deadline = previous
            previous_event = int(previous_row["event"])
            if not bool(previous_row.get("data_checked")):
                return PhaseView(
                    phase="live_gameweek",
                    season="2026-27",
                    event=previous_event,
                    label=f"GW{previous_event} live",
                    title="Follow the decisions already made.",
                    narrative=(
                        "Track the submitted team while preserving it separately from the next "
                        "deadline proposal."
                    ),
                    deadline=previous_deadline.isoformat(),
                    deadline_label="Deadline passed",
                    decision_event=upcoming_event,
                    decision_deadline=upcoming_deadline.isoformat(),
                    primary_action="follow_live",
                    decision_modules=[
                        "live_score",
                        "submitted_team",
                        "next_deadline_watch",
                    ],
                )

        delta_seconds = max(0, int((upcoming_deadline - now).total_seconds()))
        days, remainder = divmod(delta_seconds, 86_400)
        hours = remainder // 3_600
        return PhaseView(
            phase="pre_deadline",
            season="2026-27",
            event=upcoming_event,
            label=f"GW{upcoming_event} decision desk",
            title="Choose the highest-value move before the next lock.",
            narrative=(
                "Compare roll, transfers and hits, then set the best XI, bench order, captain and "
                "eligible chip from the complete 15."
            ),
            deadline=upcoming_deadline.isoformat(),
            deadline_label=f"{days}d {hours}h to deadline",
            decision_event=upcoming_event,
            decision_deadline=upcoming_deadline.isoformat(),
            primary_action="manage_team",
            decision_modules=["transfers", "lineup", "captaincy", "chips"],
        )

    @staticmethod
    def _player_view(
        row: dict[str, Any],
        role: str,
        order: int,
        forecasts: dict[int, dict[str, Any]],
        fixtures: dict[int, FixtureView],
        teams: dict[int, tuple[str, str]],
    ) -> PlayerView:
        player_id = int(row["element"])
        forecast = forecasts.get(player_id)
        if forecast is None:
            raise WorkspaceBuildError(f"GW1 forecast missing for player {player_id}")
        team_id = int(forecast["team_id"])
        team_name, team_short = teams.get(
            team_id,
            (str(row["team"]), str(forecast["team_short_name"])),
        )
        return PlayerView(
            player_id=player_id,
            name=str(row["name"]),
            position=str(row["position"]),
            team=team_name,
            team_short_name=team_short,
            price=float(row["price"]),
            expected_points=round(float(forecast["expected_points"]), 2),
            robust_points=round(float(forecast["robust_points"]), 2),
            expected_minutes=round(float(forecast["expected_minutes"]), 1),
            play_probability=round(float(forecast["p_play"]), 4),
            fixture=fixtures.get(team_id),
            role=role,
            order=order,
            captain=bool(row.get("captain", False)),
            vice_captain=bool(row.get("vice_captain", False)),
            availability_status=str(forecast["status"]),
            news=str(forecast["news"]),
        )

    @staticmethod
    def _horizon(payload: dict[str, Any], names: dict[int, str]) -> list[HorizonEvent]:
        return [
            HorizonEvent(
                event=int(event),
                formation=str(lineup["formation"]),
                expected_points=round(float(lineup["expected_points"]), 2),
                captain_name=names.get(int(lineup["captain"]), f"#{lineup['captain']}"),
                vice_captain_name=names.get(
                    int(lineup["vice_captain"]), f"#{lineup['vice_captain']}"
                ),
            )
            for event, lineup in sorted(
                payload["decision"]["candidate"]["lineups"].items(),
                key=lambda item: int(item[0]),
            )
        ]

    @staticmethod
    def _evidence_label(path: str) -> str:
        if "decisions" in path:
            return "Squad decision"
        if "components" in path:
            return "Minutes model"
        return "Player forecast"
