from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserView(StrictModel):
    user_id: str
    display_name: str
    mode: Literal["local"] = "local"
    manager_id: int | None
    connection_state: Literal["generated", "uploaded", "connected", "empty"]
    fpl_entry_id: int | None = None
    sync_state: Literal["not_connected", "id_saved", "mcp_connected"] = "not_connected"
    last_synced_at: str | None = None


class PhaseView(StrictModel):
    phase: Literal["preseason", "pre_deadline", "live_gameweek", "review"]
    season: str
    event: int
    label: str
    title: str
    narrative: str
    deadline: str
    deadline_label: str
    decision_event: int | None = None
    decision_deadline: str | None = None
    primary_action: Literal["generate_squad", "manage_team", "follow_live", "review"]
    decision_modules: list[
        Literal[
            "squad_builder",
            "screenshot_import",
            "transfers",
            "lineup",
            "captaincy",
            "chips",
            "live_score",
            "submitted_team",
            "next_deadline_watch",
            "decision_review",
        ]
    ]


class FreshnessView(StrictModel):
    status: Literal["fresh", "attention", "stale"]
    observed_at: str
    model_generated_at: str
    squad_synced_at: str | None = None
    age_seconds: float
    refresh_required: bool
    message: str


class FixtureView(StrictModel):
    opponent: str
    venue: Literal["H", "A"]
    difficulty: int
    kickoff_time: str
    label: str


class PlayerView(StrictModel):
    player_id: int
    name: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    team: str
    team_short_name: str
    price: float
    expected_points: float
    robust_points: float
    expected_minutes: float
    play_probability: float
    fixture: FixtureView | None
    role: Literal["starter", "bench"]
    order: int
    captain: bool
    vice_captain: bool
    availability_status: str
    news: str


class SquadView(StrictModel):
    source: Literal["generated", "uploaded", "connected"]
    confirmed: bool
    requires_confirmation: bool
    formation: str
    budget_spent: float
    bank: float
    expected_points: float
    candidate_id: str
    source_label: str
    parent_candidate_id: str | None = None
    locked_player_ids: list[int] = Field(default_factory=list)
    starters: list[PlayerView]
    bench: list[PlayerView]


class CritiqueItem(StrictModel):
    code: str
    title: str
    detail: str
    player_ids: list[int] = Field(default_factory=list)


class SquadCritique(StrictModel):
    status: Literal["strong", "promising", "needs_attention"]
    headline: str
    summary: str
    benchmark_expected_points: float
    expected_points_delta: float
    strengths: list[CritiqueItem]
    concerns: list[CritiqueItem]
    suggested_questions: list[str]


class CaptainInsight(StrictModel):
    captain_player_id: int
    captain_name: str
    vice_captain_player_id: int
    vice_captain_name: str
    current_captain_player_id: int
    current_captain_name: str
    current_vice_captain_player_id: int
    current_vice_captain_name: str
    recommendation_aligned: bool
    lineup_recommendation_aligned: bool
    recommended_formation: str
    promoted_player_ids: list[int] = Field(default_factory=list)
    promoted_player_names: list[str] = Field(default_factory=list)
    benched_player_ids: list[int] = Field(default_factory=list)
    benched_player_names: list[str] = Field(default_factory=list)
    evidence_status: str
    score_metric: str
    score_edge: float
    receipt_id: str
    main_risk: str


class HorizonEvent(StrictModel):
    event: int
    formation: str
    expected_points: float
    captain_name: str
    vice_captain_name: str


class WeeklyTransferView(StrictModel):
    outgoing_player_id: int
    outgoing_name: str
    incoming_player_id: int
    incoming_name: str
    incoming_price: float


class WeeklyActionView(StrictModel):
    action_id: str
    route_type: Literal["roll", "one_free_transfer", "multi_free_transfer", "paid_transfer"]
    label: str
    transfer_count: int
    transfers: list[WeeklyTransferView]
    formation: str
    captain_player_id: int
    captain_name: str
    vice_captain_player_id: int
    vice_captain_name: str
    incremental_points_cost: int
    next_free_transfers: int | None
    terminal_free_transfers: int | None
    terminal_transfer_value: float


class WeeklyDecisionView(StrictModel):
    status: Literal["not_available", "ready", "blocked"]
    event: int
    created_at: str | None = None
    selected: WeeklyActionView | None = None
    strongest_rejected: WeeklyActionView | None = None
    expected_gain_vs_roll: float | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None
    beat_roll_probability: float | None = None
    worst_scenario_gain: float | None = None
    robust_regret: float | None = None
    promotion_status: str
    explanation: str
    receipt_path: str | None = None
    receipt_sha256: str | None = None


class EvidenceItem(StrictModel):
    label: str
    path: str
    sha256: str


class DecisionView(StrictModel):
    status: Literal["provisional", "confirmed"]
    captain: CaptainInsight
    horizon: list[HorizonEvent]
    evidence: list[EvidenceItem]
    recommendation: str
    caveat: str
    weekly: WeeklyDecisionView


class CapabilityView(StrictModel):
    generate_gw1_squad: bool = True
    upload_team: bool = True
    grounded_chat: bool = True
    live_manager_connection: bool = True
    write_fpl_changes: bool = False


class WorkspaceView(StrictModel):
    schema_version: Literal["fplagent-workspace-v1"] = "fplagent-workspace-v1"
    generated_at: str
    user: UserView
    phase: PhaseView
    freshness: FreshnessView
    squad: SquadView
    critique: SquadCritique
    decision: DecisionView
    capabilities: CapabilityView


class WorkspaceRefreshRequest(StrictModel):
    reason: Literal["app_open", "manual"] = "manual"


class WorkspaceRefreshView(StrictModel):
    schema_version: Literal["workspace-refresh-v1"] = "workspace-refresh-v1"
    run_id: str | None = None
    status: Literal[
        "idle",
        "running",
        "published",
        "reused",
        "not_ready",
        "blocked",
        "failed",
    ]
    mode: Literal["gw1", "weekly"] | None = None
    reason: Literal["app_open", "manual", "scheduled", "material_change"] | None = None
    requested_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    manager_entry_id: int | None = None
    event: int | None = None
    published: bool = False
    reused: bool = False
    input_fingerprint: str | None = None
    receipt_path: str | None = None
    receipt_sha256: str | None = None
    completed_stages: list[str] = Field(default_factory=list)
    current_stage: str | None = None
    completed_stage_count: int = 0
    total_stages: int | None = None
    progress_percent: int | None = None
    failure_code: str | None = None
    message: str


class DeadlineScheduleView(StrictModel):
    schema_version: Literal["deadline-refresh-schedule-v1"] = "deadline-refresh-schedule-v1"
    status: Literal["waiting", "running", "covered", "deadline_passed", "error"]
    checked_at: str
    event: int | None = None
    deadline: str | None = None
    active_window: str | None = None
    active_window_at: str | None = None
    next_window: str | None = None
    next_window_at: str | None = None
    last_attempt_window: str | None = None
    last_attempt_at: str | None = None
    material_checked_at: str | None = None
    material_local_fingerprint: str | None = None
    material_remote_fingerprint: str | None = None
    material_change_detected: bool = False
    refresh_run_id: str | None = None
    message: str


class MarketTelemetryView(StrictModel):
    schema_version: Literal["market-telemetry-v1"] = "market-telemetry-v1"
    status: Literal["idle", "collecting", "collected", "error"]
    checked_at: str | None = None
    last_attempt_at: str | None = None
    observed_at: str | None = None
    observation_id: str | None = None
    rows: int | None = None
    receipt_path: str | None = None
    receipt_sha256: str | None = None
    feature_status: Literal["not_ready", "ready"] | None = None
    feature_path: str | None = None
    feature_sha256: str | None = None
    outcome_status: Literal["not_ready", "ready"] | None = None
    outcome_nights: int | None = None
    next_collection_at: str | None = None
    message: str


class ClubMinimumRequest(StrictModel):
    team_short_name: str = Field(min_length=2, max_length=4)
    count: int = Field(ge=1, le=3)


class GenerateSquadRequest(StrictModel):
    risk_profile: Literal["balanced", "safer", "upside"] = "balanced"
    horizon: int = Field(default=5, ge=1, le=8)
    locked_player_ids: list[int] = Field(default_factory=list, max_length=15)
    excluded_player_ids: list[int] = Field(default_factory=list, max_length=15)
    club_minimums: list[ClubMinimumRequest] = Field(default_factory=list, max_length=3)


class GenerateSquadResponse(StrictModel):
    candidate_id: str
    receipt_id: str
    source: Literal["generated"] = "generated"
    formation: str
    expected_points: float
    budget_spent: float
    bank: float
    changed_player_ids: list[int]
    duration_ms: float
    message: str


class PreseasonTeamOption(StrictModel):
    team_id: int
    name: str
    short_name: str


class PreseasonOptions(StrictModel):
    published_candidate_id: str
    published_generated_at: str
    custom_build_estimate_seconds: str
    teams: list[PreseasonTeamOption]


class ManagerProfileRequest(StrictModel):
    display_name: str = Field(default="Lewis", min_length=1, max_length=80)
    fpl_entry_id: int = Field(ge=1, le=99_999_999)


class ManagerProfileView(StrictModel):
    display_name: str
    fpl_entry_id: int | None
    sync_state: Literal["not_connected", "id_saved", "mcp_connected"]
    last_synced_at: str | None
    message: str


class McpConnectionView(StrictModel):
    status: Literal["ready", "offline", "connected", "not_authenticated"]
    url: str
    tools_available: int = 0
    message: str


class McpLoginStarted(StrictModel):
    status: Literal["pending"] = "pending"
    request_id: str
    login_url: str


class McpLoginStatus(StrictModel):
    status: Literal["pending", "connected", "failed"]
    request_id: str
    entry_id: int | None = None
    display_name: str | None = None
    error: str | None = None


class McpSyncResult(StrictModel):
    status: Literal["synced"] = "synced"
    entry_id: int
    candidate_id: str
    observed_at: str
    player_count: int
    manager_state_status: Literal["ready", "not_ready", "blocked"]
    manager_state_event: int | None = None
    manager_state_message: str
    manager_state_contract_sha256: str | None = None
    message: str


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = None
    manager_id: int = Field(default=1, ge=1)
    event: int = Field(default=1, ge=1)


class ChatResponse(StrictModel):
    session_id: str
    response: str
    receipt_ids: list[str]
    tool_names: list[str]
    safe_failure: bool
    model: str
    failure_code: str | None = None
    grounding_guard_applied: bool = False
    duration_ms: float | None = None


class UploadAccepted(StrictModel):
    upload_id: str
    status: Literal["uploaded"] = "uploaded"
    filename: str
    media_type: str
    size_bytes: int
    image_sha256: str
    preview_url: str
    analysis_url: str


class UploadAnalysisStarted(StrictModel):
    upload_id: str
    status: Literal["analysing", "ready_for_review", "failed"]
    poll_url: str


class UploadStatus(StrictModel):
    upload_id: str
    status: Literal["uploaded", "analysing", "ready_for_review", "confirmed", "failed"]
    filename: str
    media_type: str
    size_bytes: int
    image_sha256: str
    created_at: str
    updated_at: str
    result: dict | None = None
    error: str | None = None


class UploadConfirmed(StrictModel):
    upload_id: str
    status: Literal["confirmed"] = "confirmed"
    message: str
