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


class AppearanceStatesView(StrictModel):
    dnp: float
    minutes_1_59: float
    minutes_60_89: float
    minutes_90_plus: float


class PlayerParticipationView(StrictModel):
    evidence_status: Literal[
        "clear",
        "lineup_watch",
        "verify_role",
        "official_attention",
        "uncovered",
        "refreshing",
    ]
    confidence: Literal["high", "medium", "low"]
    headline: str
    detail: str
    attention: list[str] = Field(default_factory=list)
    states: AppearanceStatesView
    official_chance: int | None = None
    official_news: str = ""
    eligible_team_matches: int | None = None
    squad_listings: int | None = None
    starts: int | None = None
    appearances: int | None = None
    last_match_listed: bool | None = None
    last_match_started: bool | None = None
    mechanically_retained_p_play: float | None = None
    predicted_lineup_consensus: str | None = None
    predicted_start_sources: list[str] = Field(default_factory=list)
    predicted_not_start_sources: list[str] = Field(default_factory=list)
    predicted_lineup_production_weight: float = 0.0


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
    fixtures: list[FixtureView] = Field(default_factory=list)
    role: Literal["starter", "bench"]
    order: int
    captain: bool
    vice_captain: bool
    availability_status: str
    news: str
    participation: PlayerParticipationView


class ParticipationAlternativeView(StrictModel):
    scenario: str
    description: str
    challenger_squad_id: str
    incoming: list[str]
    outgoing: list[str]
    formation: str
    captain: str
    vice_captain: str
    minimum_family_gain: float | None = None
    counterfactual_not_probability: bool = True
    challenger_synthesis_rank: int | None = None
    synthesis_regret_delta: float | None = None
    five_week_regret_delta: float | None = None
    eight_week_regret_delta: float | None = None
    why_not_selected: str | None = None


class ParticipationSummaryView(StrictModel):
    status: Literal["current", "attention", "refreshing", "unavailable"]
    checked_at: str | None = None
    headline: str
    detail: str
    selected_players: int = 15
    clear_players: int = 0
    official_clear_players: int = 0
    official_attention: int = 0
    role_verification: int = 0
    uncovered_club_feed: int = 0
    predicted_start_support: int = 0
    predicted_bench_flags: int = 0
    predicted_disagreements: int = 0
    predicted_lineup_eligible_sources: int = 0
    predicted_lineup_captured_sources: int = 0
    predicted_lineup_status: str = "not_collected"
    baseline_stable: bool | None = None
    moderate_stable: bool | None = None
    teams_with_confirmed_lineups: int | None = None
    teams_total: int | None = None
    alternatives: list[ParticipationAlternativeView] = Field(default_factory=list)


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


class RecommendedSquadView(StrictModel):
    event: int
    source: Literal["lineup_optimizer", "weekly_decision"]
    action_id: str
    formation: str
    expected_points: float
    starters: list[PlayerView]
    bench: list[PlayerView]


class ModelSquadView(StrictModel):
    event: int
    candidate_id: str
    generated_at: str
    formation: str
    expected_points: float
    budget_spent: float
    bank: float
    selection_basis: str
    capital_role_gate_passed: bool = False
    capital_role_excluded_finalists: int = 0
    capital_role_summary: str = "Premium-role publication gate not recorded."
    starters: list[PlayerView]
    bench: list[PlayerView]


class SquadChangePlayerView(StrictModel):
    player_id: int
    name: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    team: str
    price: float


class SquadComparisonView(StrictModel):
    status: Literal["aligned", "adopt_recommendation", "awaiting_refresh", "unavailable"]
    authoritative_squad: Literal["current", "model", "weekly"]
    incumbent_candidate_id: str
    recommendation_candidate_id: str | None = None
    current_expected_points: float
    recommended_expected_points: float | None = None
    expected_points_delta: float | None = None
    change_count: int = 0
    incoming: list[SquadChangePlayerView] = Field(default_factory=list)
    outgoing: list[SquadChangePlayerView] = Field(default_factory=list)
    validation_gates_passed: int = 0
    validation_gates_total: int = 0
    churn_protected: bool = False
    headline: str
    detail: str
    reasons: list[str] = Field(default_factory=list)


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


class WeeklyLineupView(StrictModel):
    event: int
    formation: str
    projected_points: float
    starter_player_ids: list[int]
    bench_player_ids: list[int]
    captain_player_id: int
    vice_captain_player_id: int


class WeeklyActionView(StrictModel):
    action_id: str
    configuration_action_id: str | None = None
    route_type: Literal[
        "roll", "configuration_roll", "one_free_transfer", "multi_free_transfer", "paid_transfer",
        "wildcard", "free_hit",
    ]
    label: str
    transfer_count: int
    transfers: list[WeeklyTransferView]
    formation: str
    captain_player_id: int
    captain_name: str
    vice_captain_player_id: int
    vice_captain_name: str
    starter_player_ids: list[int]
    bench_player_ids: list[int]
    projected_points: float | None = None
    event_lineups: list[WeeklyLineupView] = Field(default_factory=list)
    incremental_points_cost: int
    next_free_transfers: int | None
    terminal_free_transfers: int | None
    terminal_transfer_value: float


class ExecutionTimingView(StrictModel):
    status: str
    recommendation: Literal["wait", "not_applicable"]
    headline: str
    detail: str
    affordability_at_risk: bool = False
    next_price_change_at: str | None = None


class ChipOpportunityView(StrictModel):
    event: int
    chip: str
    projected_uplift: float | None = None
    schedule_note: str | None = None


class ChipCandidateStatusView(StrictModel):
    chip: str
    status: Literal["play", "retain", "research_only", "needs_review", "not_evaluated"]
    joint_net_value: float | None = None
    blockers: list[str] = Field(default_factory=list)


class ChipDeadlinePlanView(StrictModel):
    chip: str
    planned_event: int
    latest_safe_event: int
    play_now: bool = False
    expected_gain: float | None = None


class ChipAdviceView(StrictModel):
    needs_review: bool = False
    recommended_action_id: str | None = None
    parent_action_id: str | None = None
    recommendation: Literal["no_chip", "bench_boost", "triple_captain", "wildcard", "free_hit"] = (
        "no_chip"
    )
    headline: str
    detail: str
    watched_chips: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    half_expiry_event: int | None = None
    events_until_expiry: int | None = None
    next_opportunities: list[ChipOpportunityView] = Field(default_factory=list)
    candidate_statuses: list[ChipCandidateStatusView] = Field(default_factory=list)
    deadline_plan: list[ChipDeadlinePlanView] = Field(default_factory=list)
    expiry_forced: bool = False


class RetainedRoleSaleTransferView(StrictModel):
    outgoing_name: str
    incoming_name: str


class RetainedRoleWatchView(StrictModel):
    player_id: int
    player_name: str
    expected_minutes: float
    play_probability: float
    expected_points: float
    participation_consensus: str
    selected_action_sells_player: bool
    best_forced_sale_rank: int
    best_forced_sale_transfers: list[RetainedRoleSaleTransferView]
    forced_sale_delta_to_selected: float
    forced_sale_beats_selected: bool


class ObjectiveTradeoffView(StrictModel):
    worst_case_weight: float
    mean_points_sacrificed_to_safety_gates: float
    mean_points_sacrificed_to_robust_ranking: float


class WeeklyDecisionView(StrictModel):
    status: Literal["not_available", "ready", "blocked"]
    event: int
    created_at: str | None = None
    selected: WeeklyActionView | None = None
    strongest_rejected: WeeklyActionView | None = None
    expected_gain_vs_roll: float | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None
    confidence_mean: float | None = None
    confidence_scenario: str | None = None
    objective_tradeoff: ObjectiveTradeoffView | None = None
    beat_roll_probability: float | None = None
    worst_scenario_gain: float | None = None
    robust_regret: float | None = None
    promotion_status: str
    explanation: str
    execution_timing: ExecutionTimingView | None = None
    chip_advice: ChipAdviceView | None = None
    retained_role_watches: list[RetainedRoleWatchView] = Field(default_factory=list)
    receipt_path: str | None = None
    receipt_sha256: str | None = None


class EvidenceItem(StrictModel):
    label: str
    path: str
    sha256: str


class DecisionView(StrictModel):
    status: Literal["provisional", "confirmed"]
    captain: CaptainInsight
    comparison: SquadComparisonView
    recommended_squad: RecommendedSquadView
    model_squad: ModelSquadView | None = None
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


class DeadlineBoundaryView(StrictModel):
    player_id: int
    player_name: str
    trigger_expected_minutes: float | None = None
    next_incumbent_minutes: float | None = None
    fallback_candidate_id: str | None = None
    stable_on_tested_range: bool = False


class DeadlineHandoffView(StrictModel):
    status: Literal["ready", "blocked", "unavailable"]
    verdict: str
    chip_label: str
    chip_detail: str
    route_count: int = 0
    precomputed_fallbacks: int = 0
    boundaries: list[DeadlineBoundaryView] = Field(default_factory=list)
    receipt_path: str | None = None


class WorkspaceView(StrictModel):
    schema_version: Literal["fplagent-workspace-v1"] = "fplagent-workspace-v1"
    generated_at: str
    user: UserView
    phase: PhaseView
    freshness: FreshnessView
    participation: ParticipationSummaryView
    squad: SquadView
    critique: SquadCritique
    decision: DecisionView
    deadline_handoff: DeadlineHandoffView | None = None
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
    cadence_minutes: int | None = None
    cadence_label: str | None = None
    last_validated_at: str | None = None
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
    price_policy_status: Literal["not_ready", "shadow", "passed"] | None = None
    price_policy_events: int | None = None
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
