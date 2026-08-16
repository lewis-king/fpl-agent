from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from fplagent_data.http import sha256_file
from fplagent_data.participation_consensus import CONSENSUS as DEFAULT_PARTICIPATION_CONSENSUS
from fplagent_llm.paths import ROOT
from fplagent_llm.runtime_tools import (
    DEFAULT_COMPONENTS,
    DEFAULT_DECISION,
    DEFAULT_FORECASTS,
    CaptainComparisonService,
    LocalManagerRepository,
)

from .models import (
    AppearanceStatesView,
    CapabilityView,
    CaptainInsight,
    ChipAdviceView,
    DecisionView,
    EvidenceItem,
    ExecutionTimingView,
    FixtureView,
    FreshnessView,
    HorizonEvent,
    ModelSquadView,
    ParticipationAlternativeView,
    ParticipationSummaryView,
    PhaseView,
    PlayerParticipationView,
    PlayerView,
    RecommendedSquadView,
    SquadChangePlayerView,
    SquadComparisonView,
    SquadView,
    UserView,
    WeeklyActionView,
    WeeklyDecisionView,
    WeeklyLineupView,
    WeeklyTransferView,
    WorkspaceView,
)
from .preseason import DEFAULT_ACTIVE_DECISION, PreseasonSquadService
from .profile import DEFAULT_PROFILE_PATH, ManagerProfileStore

DEFAULT_DATABASE = ROOT / "data" / "fpl_history.duckdb"
DEFAULT_DEADLINE_STATUS = ROOT / "data" / "manifests" / "fpl-deadline-evidence-status.json"
DEFAULT_WEEKLY_DECISION = ROOT / "data" / "decisions" / "2026-27-weekly-current.json"
DEFAULT_REFRESH_STATE = ROOT / "data" / "web" / "state" / "workspace-refresh.json"
DEFAULT_AVAILABILITY_WATCH = ROOT / "data" / "manifests" / "fpl-availability-watch.json"
DEFAULT_DEADLINE_PACK = ROOT / "data" / "manifests" / "gw1-deadline-pack.json"


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
        availability_watch_path: Path | None = DEFAULT_AVAILABILITY_WATCH,
        participation_consensus_path: Path | None = None,
        deadline_pack_path: Path | None = DEFAULT_DEADLINE_PACK,
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
        self.availability_watch_path = availability_watch_path
        self.participation_consensus_path = participation_consensus_path
        self.deadline_pack_path = deadline_pack_path
        if (
            self.participation_consensus_path is None
            and availability_watch_path == DEFAULT_AVAILABILITY_WATCH
            and forecast_path == DEFAULT_FORECASTS
        ):
            self.participation_consensus_path = DEFAULT_PARTICIPATION_CONSENSUS

    def build(self, *, now: datetime | None = None) -> WorkspaceView:
        current = now or datetime.now(tz=UTC)
        if current.tzinfo is None:
            raise ValueError("workspace time must include a timezone")
        resolved_decision_path = self._resolved_decision_path()
        payload = self._read_decision(resolved_decision_path)
        published_payload = (
            self._read_decision(self.decision_path)
            if self.decision_path.is_file()
            else None
        )
        phase = self._phase(current, self._event_calendar())
        analysis_event = phase.decision_event or phase.event
        candidate_meta = payload.get("workspace_candidate") or {}
        risk_profile = str(candidate_meta.get("risk_profile") or "safer")
        captain_policy = "robust" if risk_profile == "safer" else "expected_points"
        managers = LocalManagerRepository(resolved_decision_path, manager_id=self.manager_id)
        state = managers.get_state(self.manager_id, current.isoformat())
        weekly_decision = self._weekly_decision(event=analysis_event)
        captain_result = CaptainComparisonService(
            managers,
            self.forecast_path,
            self.component_path,
        ).compare(
            {
                "manager_id": self.manager_id,
                "event": analysis_event,
                "risk_policy": captain_policy,
                "as_of": current.isoformat(),
            }
        )
        squad_payload = payload["decision"]["squad"]
        all_rows = list(squad_payload["starters"]) + list(squad_payload["bench"])
        player_ids = [int(row["element"]) for row in all_rows]
        published_rows = (
            list(published_payload["decision"]["squad"]["starters"])
            + list(published_payload["decision"]["squad"]["bench"])
            if published_payload is not None
            else []
        )
        published_player_ids = [int(row["element"]) for row in published_rows]
        weekly_player_ids: list[int] = []
        if weekly_decision.status == "ready" and weekly_decision.selected is not None:
            weekly_player_ids = [
                *weekly_decision.selected.starter_player_ids,
                *weekly_decision.selected.bench_player_ids,
            ]
        forecast_player_ids = list(
            dict.fromkeys([*player_ids, *published_player_ids, *weekly_player_ids])
        )
        forecasts = self._forecasts(forecast_player_ids, event=analysis_event)
        participation, participation_by_id = self._participation_context(
            resolved_decision_path,
            {player_id: forecasts[player_id] for player_id in player_ids},
        )
        fixtures = self._fixtures(event=analysis_event)
        teams = self._teams()
        lineup = payload["decision"]["candidate"]["lineups"]["1"]
        model_squad = self._model_squad(
            event=analysis_event,
            payload=published_payload,
            forecasts=forecasts,
            fixtures=fixtures,
            teams=teams,
        )

        starters = [
            self._player_view(
                row, "starter", index, forecasts, fixtures, teams, participation_by_id
            )
            for index, row in enumerate(squad_payload["starters"], start=1)
        ]
        bench = [
            self._player_view(
                row, "bench", index, forecasts, fixtures, teams, participation_by_id
            )
            for index, row in enumerate(squad_payload["bench"], start=1)
        ]
        names = {row.player_id: row.name for row in starters + bench}
        recommended_squad = self._recommended_squad(
            event=analysis_event,
            weekly_decision=weekly_decision,
            captain_result=captain_result,
            current_rows=all_rows,
            current_starter_ids=[int(row["element"]) for row in squad_payload["starters"]],
            forecasts=forecasts,
            fixtures=fixtures,
            teams=teams,
            participation_by_id=participation_by_id,
        )
        names.update(
            {row.player_id: row.name for row in recommended_squad.starters + recommended_squad.bench}
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
        if recommended_squad.source == "weekly_decision" and weekly_decision.selected is not None:
            selected_action = weekly_decision.selected
            recommended_ids = {row.player_id for row in recommended_squad.starters}
            current_starter_ids = {row.player_id for row in starters}
            captain = {
                "player_id": selected_action.captain_player_id,
                "name": selected_action.captain_name,
            }
            vice = {
                "player_id": selected_action.vice_captain_player_id,
                "name": selected_action.vice_captain_name,
            }
            promoted_ids = sorted(recommended_ids - current_starter_ids)
            benched_ids = sorted(current_starter_ids - recommended_ids)
            recommended_lineup = {
                "formation": recommended_squad.formation,
                "promoted_player_ids": promoted_ids,
                "promoted_player_names": [names.get(value, f"#{value}") for value in promoted_ids],
                "benched_player_ids": benched_ids,
                "benched_player_names": [names.get(value, f"#{value}") for value in benched_ids],
                "aligned_with_current_xi": not promoted_ids and not benched_ids,
            }
            stored_captain = {
                **stored_captain,
                "captaincy_aligned": (
                    selected_action.captain_player_id
                    == int(stored_captain["captain_player_id"])
                    and selected_action.vice_captain_player_id
                    == int(stored_captain["vice_captain_player_id"])
                ),
            }
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
        horizon = self._horizon(
            payload,
            names,
            start_event=analysis_event,
            weekly_decision=weekly_decision,
        )
        if not horizon:
            horizon = [
                HorizonEvent(
                    event=analysis_event,
                    formation=recommended_squad.formation,
                    expected_points=recommended_squad.expected_points,
                    captain_name=str(captain["name"]),
                    vice_captain_name=str(vice["name"]),
                )
            ]

        current_expected_points = round(
            sum(
                forecasts[int(row["element"])]["expected_points"]
                for row in squad_payload["starters"]
            )
            + forecasts[int(lineup["captain"])]["expected_points"],
            2,
        )
        comparison = self._squad_comparison(
            phase=phase,
            incumbent_candidate_id=str(payload["decision"]["candidate"]["candidate_id"]),
            current_expected_points=current_expected_points,
            current_players=[*starters, *bench],
            model_squad=model_squad,
            recommended_squad=recommended_squad,
            evidence_blocked=evidence_blocked,
        )

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
            participation=participation,
            squad=SquadView(
                source=source,
                confirmed=confirmed,
                requires_confirmation=requires_confirmation,
                formation=str(squad_payload["formation"]),
                budget_spent=float(squad_payload["budget_spent"]),
                bank=float(squad_payload["bank"]),
                expected_points=current_expected_points,
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
                    evidence_status=(
                        "weekly_decision_receipt"
                        if recommended_squad.source == "weekly_decision"
                        else str(captain_result["evidence_status"])
                    ),
                    score_metric=(
                        "shared_scenario_points"
                        if recommended_squad.source == "weekly_decision"
                        else str(captain_result["score_metric"])
                    ),
                    score_edge=(
                        float(forecasts[int(captain["player_id"])]["robust_points"])
                        - float(forecasts[int(vice["player_id"])]["robust_points"])
                    ),
                    receipt_id=(
                        weekly_decision.selected.action_id
                        if recommended_squad.source == "weekly_decision"
                        and weekly_decision.selected is not None
                        else str(captain_result["receipt_id"])
                    ),
                    main_risk=str(captain_result["main_risk"]),
                ),
                comparison=comparison,
                recommended_squad=recommended_squad,
                model_squad=model_squad,
                horizon=horizon,
                evidence=decision_evidence,
                recommendation=" ".join(recommendation_parts),
                caveat=str(payload["deadline_rule"]),
                weekly=weekly_decision,
            ),
            capabilities=CapabilityView(),
        )

    def _squad_comparison(
        self,
        *,
        phase: PhaseView,
        incumbent_candidate_id: str,
        current_expected_points: float,
        current_players: list[PlayerView],
        model_squad: ModelSquadView | None,
        recommended_squad: RecommendedSquadView,
        evidence_blocked: bool,
    ) -> SquadComparisonView:
        if phase.phase == "preseason" and model_squad is not None:
            authority = "model"
            recommendation_id = model_squad.candidate_id
            recommended_points = model_squad.expected_points
            recommendation_players = [*model_squad.starters, *model_squad.bench]
            selection_reason = model_squad.selection_basis
        elif recommended_squad.source == "weekly_decision":
            authority = "weekly"
            recommendation_id = recommended_squad.action_id
            recommended_points = recommended_squad.expected_points
            recommendation_players = [
                *recommended_squad.starters,
                *recommended_squad.bench,
            ]
            selection_reason = (
                "The weekly policy beat the roll route after transfer costs and scenario stress."
            )
        else:
            return SquadComparisonView(
                status="aligned",
                authoritative_squad="current",
                incumbent_candidate_id=incumbent_candidate_id,
                recommendation_candidate_id=incumbent_candidate_id,
                current_expected_points=current_expected_points,
                recommended_expected_points=current_expected_points,
                expected_points_delta=0.0,
                headline="The active squad is the decision baseline",
                detail="No separate 15-player recommendation is available for this phase.",
                reasons=["Lineup and captaincy advice still use the complete active squad."],
            )

        current_ids = {player.player_id for player in current_players}
        recommendation_ids = {player.player_id for player in recommendation_players}
        incoming = [
            self._change_player(player)
            for player in recommendation_players
            if player.player_id not in current_ids
        ]
        outgoing = [
            self._change_player(player)
            for player in current_players
            if player.player_id not in recommendation_ids
        ]
        change_count = max(len(incoming), len(outgoing))
        points_delta = round(recommended_points - current_expected_points, 2)
        pack = self._deadline_pack()
        gates = pack.get("gates") if isinstance(pack.get("gates"), dict) else {}
        passed_gates = sum(
            bool(gate.get("passed"))
            for gate in gates.values()
            if isinstance(gate, dict)
        )
        total_gates = sum(isinstance(gate, dict) for gate in gates.values())
        churn_protected = bool(
            gates
            and isinstance(gates.get("historical_selector"), dict)
            and gates["historical_selector"].get("passed")
            and isinstance(gates.get("global_search"), dict)
            and gates["global_search"].get("passed")
        )
        aligned = not incoming and not outgoing
        if aligned:
            status = "aligned"
            headline = "Your 15 players match the recommendation"
            detail = "No squad transfer is needed; use the recommended XI, bench order and armband."
        elif evidence_blocked:
            status = "awaiting_refresh"
            headline = "Keep the last valid recommendation on screen"
            detail = (
                "A newer evidence run has not passed publication, so no unvalidated change is "
                "being promoted."
            )
        else:
            status = "adopt_recommendation"
            headline = (
                f"Make {change_count} squad change{'s' if change_count != 1 else ''}"
            )
            detail = (
                "This is the validated 15-player decision. The app will not replace it for a "
                "small unvalidated fluctuation."
            )
        delta_reason = (
            f"The recommendation adds {points_delta:.2f} modelled points in the decision event."
            if points_delta >= 0
            else (
                f"It accepts {abs(points_delta):.2f} fewer opening-event points for the stronger "
                "validated multiweek policy."
            )
        )
        reasons = [delta_reason, selection_reason]
        if total_gates:
            reasons.append(
                f"{passed_gates} of {total_gates} deadline publication gates currently pass."
            )
        if churn_protected:
            reasons.append(
                "The historical selector and global search gates protect against changing squads "
                "for a marginal re-run fluctuation."
            )
        return SquadComparisonView(
            status=status,
            authoritative_squad=authority,
            incumbent_candidate_id=incumbent_candidate_id,
            recommendation_candidate_id=recommendation_id,
            current_expected_points=current_expected_points,
            recommended_expected_points=recommended_points,
            expected_points_delta=points_delta,
            change_count=change_count,
            incoming=incoming,
            outgoing=outgoing,
            validation_gates_passed=passed_gates,
            validation_gates_total=total_gates,
            churn_protected=churn_protected,
            headline=headline,
            detail=detail,
            reasons=reasons,
        )

    @staticmethod
    def _change_player(player: PlayerView) -> SquadChangePlayerView:
        return SquadChangePlayerView(
            player_id=player.player_id,
            name=player.name,
            position=player.position,
            team=player.team,
            price=player.price,
        )

    def _deadline_pack(self) -> dict[str, Any]:
        if self.deadline_pack_path is None or not self.deadline_pack_path.is_file():
            return {}
        try:
            value = json.loads(self.deadline_pack_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

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
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            pa.ArrowException,
        ):
            return None

    def _refresh_is_running(self) -> bool:
        if self.refresh_state_path is None or not self.refresh_state_path.is_file():
            return False
        try:
            value = json.loads(self.refresh_state_path.read_text(encoding="utf-8"))
            return value.get("status") == "running"
        except (OSError, json.JSONDecodeError):
            return False

    @staticmethod
    def _player_participation(
        forecast: dict[str, Any], evidence: dict[str, Any] | None
    ) -> PlayerParticipationView:
        states = AppearanceStatesView(
            dnp=round(float(forecast["p_dnp"]), 4),
            minutes_1_59=round(float(forecast["p_1_59"]), 4),
            minutes_60_89=round(float(forecast["p_60_89"]), 4),
            minutes_90_plus=round(float(forecast["p_90_or_more"]), 4),
        )
        if evidence is None:
            return PlayerParticipationView(
                evidence_status="refreshing",
                confidence="low",
                headline="Role evidence refreshing",
                detail=(
                    "The minute-band forecast is available, but the attributable official and "
                    "lineup evidence is not aligned to this decision yet."
                ),
                states=states,
            )

        attention = list(map(str, evidence.get("attention") or []))
        official = evidence.get("official") or {}
        preseason = evidence.get("preseason") or {}
        sensitivity = evidence.get("supported_edge_sensitivity") or {}
        predicted = evidence.get("predicted_lineups") or {}
        predicted_consensus = str(predicted.get("consensus") or "") or None
        predicted_start_sources = list(
            map(str, predicted.get("predicted_start_sources") or [])
        )
        predicted_not_start_sources = list(
            map(str, predicted.get("predicted_not_start_sources") or [])
        )
        source_support = len(predicted_start_sources)
        source_suffix = (
            f" {source_support} current predicted-XI source"
            f"{'s' if source_support != 1 else ''} also include this player; this is "
            "prospective evidence with zero production weight."
            if source_support
            else ""
        )
        if "official_unavailable" in attention:
            status, confidence = "official_attention", "low"
            headline = "Officially unavailable"
            detail = str(official.get("news") or "Official FPL availability is zero.")
        elif "official_doubt_or_news" in attention:
            status, confidence = "official_attention", "medium"
            headline = "Official update needs review"
            detail = str(official.get("news") or "Official FPL carries an availability flag.")
        elif "predicted_bench_consensus_shadow" in attention:
            status, confidence = "lineup_watch", "low"
            headline = "Predicted XIs flag a bench role"
            detail = (
                f"{len(predicted_not_start_sources)} independent current sources omit this "
                "player from the predicted XI. This opens a deadline review; it does not yet "
                "override the validated minute model."
            )
        elif "predicted_lineup_disagreement" in attention:
            status, confidence = "lineup_watch", "medium"
            headline = "Predicted XIs disagree"
            detail = (
                "Current providers disagree on the starting role. Keep the model prior and "
                "recheck after press conferences."
            )
        elif "three_plus_lineup_absence" in attention:
            status, confidence = "verify_role", "low"
            headline = "Deadline role check required"
            detail = (
                f"Not listed in {int(preseason.get('eligible_team_matches') or 0)} "
                "tracked preseason lineups. Post-tournament phased returns can cause this; it is "
                "a verification flag, not an injury claim or a forecast downgrade."
            ) + source_suffix
        elif "low_recent_start_share" in attention:
            status, confidence = "verify_role", "medium"
            headline = "Starting role needs verification"
            detail = (
                f"Started {int(preseason.get('starts') or 0)} of "
                f"{int(preseason.get('eligible_team_matches') or 0)} tracked preseason matches. "
                "Friendly rotation and phased returns do not automatically reduce projected minutes."
            ) + source_suffix
        elif "uncovered_club_feed" in attention:
            status, confidence = "uncovered", "low"
            headline = "No confirmed club lineup feed"
            detail = "Role evidence is unknown for this club; no penalty is silently applied."
        else:
            status, confidence = "clear", "high"
            headline = (
                "Predicted XI support"
                if predicted_consensus
                in {"predicted_start_consensus", "single_source_start"}
                else "No current participation flag"
            )
            matches = int(preseason.get("eligible_team_matches") or 0)
            starts = int(preseason.get("starts") or 0)
            if source_support:
                confidence = "high" if source_support >= 2 else "medium"
                detail = (
                    f"Included in {source_support} current predicted XI source"
                    f"{'s' if source_support != 1 else ''}. The source vote is shown separately "
                    "and retains zero model weight until prospective validation."
                )
            else:
                detail = (
                    f"Observed in the current evidence set with {starts} starts across "
                    f"{matches} tracked matches."
                    if matches
                    else "Official status and the production forecast carry no current warning."
                )
        return PlayerParticipationView(
            evidence_status=status,
            confidence=confidence,
            headline=headline,
            detail=detail,
            attention=attention,
            states=states,
            official_chance=(
                int(official["chance"]) if official.get("chance") is not None else None
            ),
            official_news=str(official.get("news") or ""),
            eligible_team_matches=(
                int(preseason["eligible_team_matches"])
                if preseason.get("eligible_team_matches") is not None
                else None
            ),
            squad_listings=(
                int(preseason["squad_listings"])
                if preseason.get("squad_listings") is not None
                else None
            ),
            starts=(
                int(preseason["starts"]) if preseason.get("starts") is not None else None
            ),
            appearances=(
                int(preseason["appearances"])
                if preseason.get("appearances") is not None
                else None
            ),
            last_match_listed=preseason.get("last_match_listed"),
            last_match_started=preseason.get("last_match_started"),
            mechanically_retained_p_play=(
                round(float(sensitivity["mechanically_retained_p_play"]), 4)
                if sensitivity.get("mechanically_retained_p_play") is not None
                else None
            ),
            predicted_lineup_consensus=predicted_consensus,
            predicted_start_sources=predicted_start_sources,
            predicted_not_start_sources=predicted_not_start_sources,
            predicted_lineup_production_weight=0.0,
        )

    def _participation_context(
        self, decision_path: Path, forecasts: dict[int, dict[str, Any]]
    ) -> tuple[ParticipationSummaryView, dict[int, dict[str, Any]]]:
        path = self.availability_watch_path
        refreshing = self._refresh_is_running()
        fallback_status = "refreshing" if refreshing else "unavailable"
        fallback = ParticipationSummaryView(
            status=fallback_status,
            headline=(
                "Checking lineup confidence"
                if refreshing
                else "Lineup evidence is not available"
            ),
            detail=(
                "The last decision remains visible while official and role evidence is aligned."
                if refreshing
                else "Use the model minute bands cautiously until a matching evidence receipt exists."
            ),
            selected_players=len(forecasts),
        )
        if path is None or not path.is_file():
            return fallback, {}
        try:
            watch = json.loads(path.read_text(encoding="utf-8"))
            lineage = watch.get("lineage") or {}
            forecast_aligned = lineage.get("forecast_sha256") == sha256_file(
                self.forecast_path
            )
            decision_aligned = lineage.get("decision_sha256") == sha256_file(decision_path)
            if not forecast_aligned or not watch.get("current"):
                return fallback, {}
            rows = {
                int(row["element"]): row
                for row in watch.get("players") or []
                if row.get("element") is not None and int(row["element"]) in forecasts
            }
            stability = watch.get("scenario_stability") or {}
            coverage = watch.get("coverage") or {}
            predicted_layer = watch.get("predicted_lineup_consensus") or {}
            if (
                predicted_layer.get("current")
                and self.participation_consensus_path is not None
                and self.participation_consensus_path.is_file()
            ):
                for predicted in pq.read_table(self.participation_consensus_path).to_pylist():
                    element = int(predicted["element"])
                    if element not in forecasts or element in rows:
                        continue
                    predicted_attention = list(map(str, predicted.get("attention") or []))
                    rows[element] = {
                        "element": element,
                        "attention": predicted_attention,
                        "official": {
                            "chance": predicted.get("official_chance"),
                            "news": str(predicted.get("official_news") or ""),
                        },
                        "preseason": {},
                        "supported_edge_sensitivity": None,
                        "predicted_lineups": {
                            "consensus": str(predicted.get("consensus") or ""),
                            "predicted_start_sources": list(
                                map(str, predicted.get("predicted_start_sources") or [])
                            ),
                            "predicted_not_start_sources": list(
                                map(
                                    str,
                                    predicted.get("predicted_not_start_sources") or [],
                                )
                            ),
                            "complete_source_count": int(
                                predicted.get("complete_source_count") or 0
                            ),
                            "production_weight": 0.0,
                            "production_adjustment_authorized": False,
                        },
                    }
            alternatives = (
                [
                    ParticipationAlternativeView.model_validate(row)
                    for row in watch.get("decision_impacts") or []
                ]
                if decision_aligned
                else []
            )
            attentions = [set(map(str, row.get("attention") or [])) for row in rows.values()]
            official_attention = sum(
                bool(values & {"official_unavailable", "official_doubt_or_news"})
                for values in attentions
            )
            role_verification = sum(
                bool(values & {"three_plus_lineup_absence", "low_recent_start_share"})
                for values in attentions
            )
            uncovered = sum("uncovered_club_feed" in values for values in attentions)
            predicted_start_support = sum(
                (row.get("predicted_lineups") or {}).get("consensus")
                in {"predicted_start_consensus", "single_source_start"}
                for row in rows.values()
            )
            predicted_bench = sum(
                (row.get("predicted_lineups") or {}).get("consensus")
                == "predicted_bench_consensus"
                for row in rows.values()
            )
            predicted_disagreement = sum(
                (row.get("predicted_lineups") or {}).get("consensus")
                == "source_disagreement"
                for row in rows.values()
            )
            missing = len(set(forecasts) - set(rows))
            baseline_stable = (
                bool(stability.get("baseline_stable")) if decision_aligned else None
            )
            moderate_stable = (
                bool(stability.get("moderate_stable")) if decision_aligned else None
            )
            unstable = bool(
                decision_aligned
                and (not baseline_stable or not moderate_stable)
            )
            needs_attention = bool(
                official_attention
                or role_verification
                or uncovered
                or predicted_bench
                or predicted_disagreement
                or missing
                or unstable
            )
            flagged = (
                official_attention
                + role_verification
                + uncovered
                + predicted_bench
                + predicted_disagreement
                + missing
            )
            official_clear = max(0, len(rows) - official_attention)
            if official_attention:
                headline = "Official availability needs review"
            elif predicted_bench or predicted_disagreement:
                headline = "Predicted lineups need a deadline check"
            elif role_verification or unstable:
                headline = "Official status clear; context checks remain"
            else:
                headline = "Official participation status is clear"
            if official_attention:
                detail = (
                    f"{official_attention} of {len(forecasts)} players carries an official FPL "
                    "availability or news flag. Official evidence is already represented in the "
                    "minute forecast."
                )
            elif predicted_bench or predicted_disagreement:
                detail = (
                    f"{predicted_bench} selected players carry a two-source bench flag and "
                    f"{predicted_disagreement} have contradictory predicted XIs. These are "
                    "review triggers, not automatic forecast changes."
                )
            elif unstable:
                detail = (
                    f"All {official_clear} aligned players are officially clear. A friendly-lineup "
                    "stress test identifies a supported alternative, but friendly evidence has "
                    "zero production weight and cannot change the squad without attributable "
                    "deadline evidence."
                )
            elif not decision_aligned:
                detail = (
                    f"Player-level evidence is current for {len(rows)} of {len(forecasts)} players. "
                    "Squad-specific stress alternatives are hidden because this is a different "
                    "connected or uploaded squad."
                )
            elif flagged:
                detail = (
                    f"All {official_clear} aligned players are officially clear; "
                    f"{role_verification + uncovered} carry a zero-weight preseason context check."
                )
            elif predicted_start_support:
                detail = (
                    f"{predicted_start_support} of {len(forecasts)} selected players appear in "
                    "the currently eligible predicted XI feed. This is independently visible "
                    "but remains zero-weight while the prospective scoreboard accumulates."
                )
            else:
                detail = "No selected player carries a current official or observed-role flag."
            return (
                ParticipationSummaryView(
                    status="attention" if needs_attention else "current",
                    checked_at=str(watch.get("checked_at") or "") or None,
                    headline=headline,
                    detail=detail,
                    selected_players=len(forecasts),
                    clear_players=sum(not values for values in attentions),
                    official_clear_players=official_clear,
                    official_attention=official_attention,
                    role_verification=role_verification,
                    uncovered_club_feed=uncovered,
                    predicted_start_support=predicted_start_support,
                    predicted_bench_flags=predicted_bench,
                    predicted_disagreements=predicted_disagreement,
                    predicted_lineup_eligible_sources=int(
                        predicted_layer.get("eligible_source_count") or 0
                    ),
                    predicted_lineup_captured_sources=int(
                        predicted_layer.get("captured_source_count") or 0
                    ),
                    predicted_lineup_status=str(
                        predicted_layer.get("status") or "not_collected"
                    ),
                    baseline_stable=baseline_stable,
                    moderate_stable=moderate_stable,
                    teams_with_confirmed_lineups=(
                        int(coverage["teams_with_confirmed_lineups"])
                        if coverage.get("teams_with_confirmed_lineups") is not None
                        else None
                    ),
                    teams_total=(
                        int(coverage["teams"])
                        if coverage.get("teams") is not None
                        else None
                    ),
                    alternatives=alternatives,
                ),
                rows,
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return fallback, {}

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
        event_lineups = [
            WeeklyLineupView(
                event=int(row["event"]),
                formation=str(row["formation"]),
                projected_points=float(row["projected_points"]),
                starter_player_ids=[int(value) for value in row["starter_player_ids"]],
                bench_player_ids=[int(value) for value in row["bench_player_ids"]],
                captain_player_id=int(row["captain_player_id"]),
                vice_captain_player_id=int(row["vice_captain_player_id"]),
            )
            for row in summary.get("event_lineups", [])
        ]
        starter_player_ids = [
            int(value) for value in summary.get("starter_player_ids", [])
        ]
        bench_player_ids = [int(value) for value in summary.get("bench_player_ids", [])]
        if event_lineups and not starter_player_ids:
            starter_player_ids = event_lineups[0].starter_player_ids
        if event_lineups and not bench_player_ids:
            bench_player_ids = event_lineups[0].bench_player_ids
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
            starter_player_ids=starter_player_ids,
            bench_player_ids=bench_player_ids,
            projected_points=(event_lineups[0].projected_points if event_lineups else None),
            event_lineups=event_lineups,
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
            if decision_event != event:
                return WeeklyDecisionView(
                    status="not_available",
                    event=event,
                    promotion_status="awaiting_current_event_receipt",
                    explanation=(
                        f"The stored weekly receipt is for GW{decision_event}; a validated GW{event} "
                        "receipt has not been published yet."
                    ),
                    receipt_path=str(path),
                )
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
            execution_timing = self._execution_timing_view(
                (payload.get("diagnostics") or {}).get("early_transfer_shadow") or {}
            )
            chip_advice = self._chip_advice_view(
                payload.get("chip_shadow") or {},
                payload.get("squad_chip_shadow") or {},
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
                execution_timing=execution_timing,
                chip_advice=chip_advice,
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
    def _execution_timing_view(payload: dict[str, Any]) -> ExecutionTimingView | None:
        if not payload:
            return None
        status = str(payload.get("status") or "not_ready")
        if status == "not_applicable":
            return ExecutionTimingView(
                status=status,
                recommendation="not_applicable",
                headline="No transfer timing decision",
                detail=str(payload.get("reason") or "The selected route makes no transfer."),
            )
        affordability_at_risk = bool(payload.get("route_blocked_by_threshold_stress"))
        if affordability_at_risk:
            headline = "Price pressure could block this move"
            detail = (
                "The threshold stress would make the route unaffordable, but the price signal is "
                "still shadow-only. Wait for team news unless a later calibrated policy clears it."
            )
        elif status == "ready_shadow":
            headline = "Wait before making the transfer"
            detail = (
                "The route remains affordable under the current threshold stress; preserve injury "
                "and lineup information for now."
            )
        else:
            headline = "Transfer timing evidence is not ready"
            detail = str(payload.get("reason") or "The safe operational action is to wait.")
        return ExecutionTimingView(
            status=status,
            recommendation="wait",
            headline=headline,
            detail=detail,
            affordability_at_risk=affordability_at_risk,
            next_price_change_at=(
                str(payload["next_price_change_at"])
                if payload.get("next_price_change_at")
                else None
            ),
        )

    @staticmethod
    def _chip_advice_view(
        team_chip: dict[str, Any], squad_chip: dict[str, Any]
    ) -> ChipAdviceView | None:
        if not team_chip and not squad_chip:
            return None
        watched = []
        for payload in (team_chip, squad_chip):
            preference = payload.get("shadow_preference") or {}
            chip = preference.get("chip")
            if chip and str(chip) not in watched:
                watched.append(str(chip))
        blockers: list[str] = []
        for payload in (team_chip, squad_chip):
            candidates = payload.get("candidates") or []
            if not candidates:
                continue
            for check in candidates[0].get("checks") or []:
                if not check.get("passed"):
                    value = str(check.get("name") or "chip safety gate")
                    if value not in blockers:
                        blockers.append(value)
        detail = "All eligible chip branches were compared with retaining the chip."
        if watched:
            detail += " The strongest research-only shadows were " + " and ".join(watched) + "."
        detail += " None has cleared the historical and prospective safety gates."
        return ChipAdviceView(
            headline="Save the chips",
            detail=detail,
            watched_chips=watched,
            blockers=blockers[:4],
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
                       coalesce(c.expected_minutes, 0.0),
                       f.p_dnp, f.p_1_59, f.p_60_89, f.p_90_or_more
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
                "p_dnp": float(row[9]),
                "p_1_59": float(row[10]),
                "p_60_89": float(row[11]),
                "p_90_or_more": float(row[12]),
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

    def _fixtures(self, event: int) -> dict[int, list[FixtureView]]:
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
        fixtures: dict[int, list[FixtureView]] = {}
        for row in sorted(rows, key=lambda value: (str(value[4]), int(value[0]))):
            fixtures.setdefault(int(row[0]), []).append(FixtureView(
                opponent=str(row[1]),
                venue=str(row[2]),
                difficulty=int(row[3]),
                kickoff_time=str(row[4]),
                label=f"{row[1]} ({row[2]})",
            ))
        return fixtures

    def _player_metadata_rows(self, player_ids: list[int]) -> dict[int, dict[str, Any]]:
        if not player_ids:
            return {}
        connection = self._connection()
        try:
            rows = connection.execute(
                """
                SELECT p.id, p.web_name,
                       CASE pos.singular_name_short WHEN 'GKP' THEN 'GK'
                            ELSE pos.singular_name_short END,
                       p.team, p.now_cost / 10.0
                FROM fpl_current_players p
                JOIN fpl_current_positions pos ON pos.id = p.element_type
                WHERE p.id IN (SELECT * FROM unnest(?))
                """,
                [player_ids],
            ).fetchall()
        finally:
            connection.close()
        return {
            int(row[0]): {
                "element": int(row[0]),
                "name": str(row[1]),
                "position": str(row[2]),
                "team": int(row[3]),
                "price": float(row[4]),
            }
            for row in rows
        }

    def _model_squad(
        self,
        *,
        event: int,
        payload: dict[str, Any] | None,
        forecasts: dict[int, dict[str, Any]],
        fixtures: dict[int, list[FixtureView]],
        teams: dict[int, tuple[str, str]],
    ) -> ModelSquadView | None:
        if payload is None or event != 1:
            return None
        try:
            squad = payload["decision"]["squad"]
            lineup = payload["decision"]["candidate"]["lineups"]["1"]
            raw_starters = [dict(row) for row in squad["starters"]]
            raw_bench = [dict(row) for row in squad["bench"]]
            candidate_id = str(payload["decision"]["candidate"]["candidate_id"])
        except (KeyError, TypeError) as exc:
            raise WorkspaceBuildError("the published model squad is incomplete") from exc
        model_ids = {
            int(row["element"]) for row in [*raw_starters, *raw_bench]
        }
        missing = model_ids - set(forecasts)
        if missing:
            raise WorkspaceBuildError(
                f"GW1 forecast missing for published model players: {sorted(missing)}"
            )
        _, participation_by_id = self._participation_context(
            self.decision_path,
            {player_id: forecasts[player_id] for player_id in model_ids},
        )
        captain_id = int(lineup["captain"])
        vice_id = int(lineup["vice_captain"])
        for row in [*raw_starters, *raw_bench]:
            player_id = int(row["element"])
            row["captain"] = player_id == captain_id
            row["vice_captain"] = player_id == vice_id
        starters = [
            self._player_view(
                row,
                "starter",
                index,
                forecasts,
                fixtures,
                teams,
                participation_by_id,
            )
            for index, row in enumerate(raw_starters, start=1)
        ]
        bench = [
            self._player_view(
                row,
                "bench",
                index,
                forecasts,
                fixtures,
                teams,
                participation_by_id,
            )
            for index, row in enumerate(raw_bench, start=1)
        ]
        return ModelSquadView(
            event=1,
            candidate_id=candidate_id,
            generated_at=str(payload["created_at"]),
            formation=str(squad["formation"]),
            expected_points=round(
                sum(
                    forecasts[int(row["element"])]["expected_points"]
                    for row in raw_starters
                )
                + forecasts[captain_id]["expected_points"],
                2,
            ),
            budget_spent=float(squad["budget_spent"]),
            bank=float(squad["bank"]),
            selection_basis=(
                "Lowest combined regret across the independent five-week robust and "
                "eight-week horizon audit families."
            ),
            starters=starters,
            bench=bench,
        )

    def _recommended_squad(
        self,
        *,
        event: int,
        weekly_decision: WeeklyDecisionView,
        captain_result: dict[str, Any],
        current_rows: list[dict[str, Any]],
        current_starter_ids: list[int],
        forecasts: dict[int, dict[str, Any]],
        fixtures: dict[int, list[FixtureView]],
        teams: dict[int, tuple[str, str]],
        participation_by_id: dict[int, dict[str, Any]],
    ) -> RecommendedSquadView:
        selected = weekly_decision.selected
        weekly_ids = (
            [*selected.starter_player_ids, *selected.bench_player_ids]
            if weekly_decision.status == "ready" and selected is not None
            else []
        )
        if (
            selected is not None
            and len(selected.starter_player_ids) == 11
            and len(selected.bench_player_ids) == 4
            and len(set(weekly_ids)) == 15
            and set(weekly_ids) <= set(forecasts)
        ):
            rows_by_id = self._player_metadata_rows(weekly_ids)
            if set(rows_by_id) == set(weekly_ids):
                for player_id, row in rows_by_id.items():
                    row["captain"] = player_id == selected.captain_player_id
                    row["vice_captain"] = player_id == selected.vice_captain_player_id
                starters = [
                    self._player_view(
                        rows_by_id[player_id],
                        "starter",
                        index,
                        forecasts,
                        fixtures,
                        teams,
                        participation_by_id,
                    )
                    for index, player_id in enumerate(selected.starter_player_ids, start=1)
                ]
                bench = [
                    self._player_view(
                        rows_by_id[player_id],
                        "bench",
                        index,
                        forecasts,
                        fixtures,
                        teams,
                        participation_by_id,
                    )
                    for index, player_id in enumerate(selected.bench_player_ids, start=1)
                ]
                expected_points = selected.projected_points
                if expected_points is None:
                    expected_points = sum(row.robust_points for row in starters)
                    expected_points += next(
                        row.robust_points
                        for row in starters
                        if row.player_id == selected.captain_player_id
                    )
                return RecommendedSquadView(
                    event=event,
                    source="weekly_decision",
                    action_id=selected.action_id,
                    formation=selected.formation,
                    expected_points=round(expected_points, 2),
                    starters=starters,
                    bench=bench,
                )

        current_by_id = {int(row["element"]): dict(row) for row in current_rows}
        recommended = captain_result["recommended_lineup"]
        starter_ids = [int(value) for value in recommended["starter_player_ids"]]
        starter_set = set(starter_ids)
        ordered_starters = [value for value in current_starter_ids if value in starter_set]
        ordered_starters.extend(value for value in starter_ids if value not in ordered_starters)
        bench_ids = [value for value in current_by_id if value not in starter_set]
        captain_id = int(captain_result["captain"]["player_id"])
        vice_id = int(captain_result["vice_captain"]["player_id"])
        for player_id, row in current_by_id.items():
            row["captain"] = player_id == captain_id
            row["vice_captain"] = player_id == vice_id
        starters = [
            self._player_view(
                current_by_id[player_id],
                "starter",
                index,
                forecasts,
                fixtures,
                teams,
                participation_by_id,
            )
            for index, player_id in enumerate(ordered_starters, start=1)
        ]
        bench = [
            self._player_view(
                current_by_id[player_id],
                "bench",
                index,
                forecasts,
                fixtures,
                teams,
                participation_by_id,
            )
            for index, player_id in enumerate(bench_ids, start=1)
        ]
        return RecommendedSquadView(
            event=event,
            source="lineup_optimizer",
            action_id=str(captain_result["receipt_id"]),
            formation=str(recommended["formation"]),
            expected_points=round(float(recommended["captain_inclusive_score"]), 2),
            starters=starters,
            bench=bench,
        )

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
        fixtures: dict[int, list[FixtureView]],
        teams: dict[int, tuple[str, str]],
        participation_by_id: dict[int, dict[str, Any]],
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
            fixture=(fixtures.get(team_id) or [None])[0],
            fixtures=fixtures.get(team_id, []),
            role=role,
            order=order,
            captain=bool(row.get("captain", False)),
            vice_captain=bool(row.get("vice_captain", False)),
            availability_status=str(forecast["status"]),
            news=str(forecast["news"]),
            participation=WorkspaceBuilder._player_participation(
                forecast, participation_by_id.get(player_id)
            ),
        )

    @staticmethod
    def _horizon(
        payload: dict[str, Any],
        names: dict[int, str],
        *,
        start_event: int,
        weekly_decision: WeeklyDecisionView,
    ) -> list[HorizonEvent]:
        if weekly_decision.status == "ready" and weekly_decision.selected is not None:
            weekly_rows = [
                HorizonEvent(
                    event=row.event,
                    formation=row.formation,
                    expected_points=round(row.projected_points, 2),
                    captain_name=names.get(row.captain_player_id, f"#{row.captain_player_id}"),
                    vice_captain_name=names.get(
                        row.vice_captain_player_id, f"#{row.vice_captain_player_id}"
                    ),
                )
                for row in weekly_decision.selected.event_lineups
                if row.event >= start_event
            ]
            if weekly_rows:
                return weekly_rows
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
            if int(event) >= start_event
        ]

    @staticmethod
    def _evidence_label(path: str) -> str:
        if "decisions" in path:
            return "Squad decision"
        if "components" in path:
            return "Minutes model"
        return "Player forecast"
