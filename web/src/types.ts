export type Position = 'GK' | 'DEF' | 'MID' | 'FWD'

export interface Fixture {
  opponent: string
  venue: 'H' | 'A'
  difficulty: number
  kickoff_time: string
  label: string
}

export interface Player {
  player_id: number
  name: string
  position: Position
  team: string
  team_short_name: string
  price: number
  expected_points: number
  robust_points: number
  expected_minutes: number
  play_probability: number
  fixture: Fixture | null
  role: 'starter' | 'bench'
  order: number
  captain: boolean
  vice_captain: boolean
  availability_status: string
  news: string
}

export interface WeeklyTransfer {
  outgoing_player_id: number
  outgoing_name: string
  incoming_player_id: number
  incoming_name: string
  incoming_price: number
}

export interface WeeklyAction {
  action_id: string
  route_type: 'roll' | 'one_free_transfer' | 'multi_free_transfer' | 'paid_transfer'
  label: string
  transfer_count: number
  transfers: WeeklyTransfer[]
  formation: string
  captain_player_id: number
  captain_name: string
  vice_captain_player_id: number
  vice_captain_name: string
  incremental_points_cost: number
  next_free_transfers: number | null
  terminal_free_transfers: number | null
  terminal_transfer_value: number
}

export interface WeeklyDecision {
  status: 'not_available' | 'ready' | 'blocked'
  event: number
  created_at: string | null
  selected: WeeklyAction | null
  strongest_rejected: WeeklyAction | null
  expected_gain_vs_roll: number | null
  confidence_low: number | null
  confidence_high: number | null
  beat_roll_probability: number | null
  worst_scenario_gain: number | null
  robust_regret: number | null
  promotion_status: string
  explanation: string
  receipt_path: string | null
  receipt_sha256: string | null
}

export interface Workspace {
  schema_version: 'fplagent-workspace-v1'
  generated_at: string
  user: {
    user_id: string
    display_name: string
    mode: 'local'
    manager_id: number | null
    connection_state: 'generated' | 'uploaded' | 'connected' | 'empty'
    fpl_entry_id: number | null
    sync_state: 'not_connected' | 'id_saved' | 'mcp_connected'
    last_synced_at: string | null
  }
  phase: {
    phase: 'preseason' | 'pre_deadline' | 'live_gameweek' | 'review'
    season: string
    event: number
    label: string
    title: string
    narrative: string
    deadline: string
    deadline_label: string
    decision_event: number | null
    decision_deadline: string | null
    primary_action: 'generate_squad' | 'manage_team' | 'follow_live' | 'review'
    decision_modules: Array<
      | 'squad_builder'
      | 'screenshot_import'
      | 'transfers'
      | 'lineup'
      | 'captaincy'
      | 'chips'
      | 'live_score'
      | 'submitted_team'
      | 'next_deadline_watch'
      | 'decision_review'
    >
  }
  freshness: {
    status: 'fresh' | 'attention' | 'stale'
    observed_at: string
    model_generated_at: string
    squad_synced_at: string | null
    age_seconds: number
    refresh_required: boolean
    message: string
  }
  squad: {
    source: 'generated' | 'uploaded' | 'connected'
    confirmed: boolean
    requires_confirmation: boolean
    formation: string
    budget_spent: number
    bank: number
    expected_points: number
    candidate_id: string
    source_label: string
    parent_candidate_id: string | null
    locked_player_ids: number[]
    starters: Player[]
    bench: Player[]
  }
  critique: {
    status: 'strong' | 'promising' | 'needs_attention'
    headline: string
    summary: string
    benchmark_expected_points: number
    expected_points_delta: number
    strengths: CritiqueItem[]
    concerns: CritiqueItem[]
    suggested_questions: string[]
  }
  decision: {
    status: 'provisional' | 'confirmed'
    captain: {
      captain_player_id: number
      captain_name: string
      vice_captain_player_id: number
      vice_captain_name: string
      current_captain_player_id: number
      current_captain_name: string
      current_vice_captain_player_id: number
      current_vice_captain_name: string
      recommendation_aligned: boolean
      lineup_recommendation_aligned: boolean
      recommended_formation: string
      promoted_player_ids: number[]
      promoted_player_names: string[]
      benched_player_ids: number[]
      benched_player_names: string[]
      evidence_status: string
      score_metric: string
      score_edge: number
      receipt_id: string
      main_risk: string
    }
    horizon: Array<{
      event: number
      formation: string
      expected_points: number
      captain_name: string
      vice_captain_name: string
    }>
    evidence: Array<{
      label: string
      path: string
      sha256: string
    }>
    recommendation: string
    caveat: string
    weekly: WeeklyDecision
  }
  capabilities: {
    generate_gw1_squad: boolean
    upload_team: boolean
    grounded_chat: boolean
    live_manager_connection: boolean
    write_fpl_changes: boolean
  }
}

export interface WorkspaceRefresh {
  schema_version: 'workspace-refresh-v1'
  run_id: string | null
  status: 'idle' | 'running' | 'published' | 'reused' | 'not_ready' | 'blocked' | 'failed'
  mode: 'gw1' | 'weekly' | null
  reason: 'app_open' | 'manual' | 'scheduled' | 'material_change' | null
  requested_at: string | null
  started_at: string | null
  completed_at: string | null
  manager_entry_id: number | null
  event: number | null
  published: boolean
  reused: boolean
  input_fingerprint: string | null
  receipt_path: string | null
  receipt_sha256: string | null
  completed_stages: string[]
  current_stage: string | null
  completed_stage_count: number
  total_stages: number | null
  progress_percent: number | null
  failure_code: string | null
  message: string
}

export interface CritiqueItem {
  code: string
  title: string
  detail: string
  player_ids: number[]
}

export interface ClubMinimum {
  team_short_name: string
  count: number
}

export interface GenerateSquadRequest {
  risk_profile: 'balanced' | 'safer' | 'upside'
  horizon: 3 | 5 | 8
  locked_player_ids: number[]
  excluded_player_ids: number[]
  club_minimums: ClubMinimum[]
}

export interface GenerateSquadResult {
  candidate_id: string
  receipt_id: string
  source: 'generated'
  formation: string
  expected_points: number
  budget_spent: number
  bank: number
  changed_player_ids: number[]
  duration_ms: number
  message: string
}

export interface PreseasonOptions {
  published_candidate_id: string
  published_generated_at: string
  custom_build_estimate_seconds: string
  teams: Array<{
    team_id: number
    name: string
    short_name: string
  }>
}

export interface ManagerProfile {
  display_name: string
  fpl_entry_id: number | null
  sync_state: 'not_connected' | 'id_saved' | 'mcp_connected'
  last_synced_at: string | null
  message: string
}

export interface McpConnection {
  status: 'ready' | 'offline' | 'connected' | 'not_authenticated'
  url: string
  tools_available: number
  message: string
}

export interface McpLoginStarted {
  status: 'pending'
  request_id: string
  login_url: string
}

export interface McpLoginStatus {
  status: 'pending' | 'connected' | 'failed'
  request_id: string
  entry_id: number | null
  display_name: string | null
  error: string | null
}

export interface McpSyncResult {
  status: 'synced'
  entry_id: number
  candidate_id: string
  observed_at: string
  player_count: number
  manager_state_status: 'ready' | 'not_ready' | 'blocked'
  manager_state_event: number | null
  manager_state_message: string
  manager_state_contract_sha256: string | null
  message: string
}

export interface ChatResult {
  session_id: string
  response: string
  receipt_ids: string[]
  tool_names: string[]
  safe_failure: boolean
  model: string
  failure_code: string | null
  grounding_guard_applied: boolean
  duration_ms: number | null
}

export interface UploadAccepted {
  upload_id: string
  status: 'uploaded'
  filename: string
  media_type: string
  size_bytes: number
  image_sha256: string
  preview_url: string
  analysis_url: string
}

export interface UploadStatus {
  upload_id: string
  status: 'uploaded' | 'analysing' | 'ready_for_review' | 'confirmed' | 'failed'
  filename: string
  media_type: string
  size_bytes: number
  image_sha256: string
  created_at: string
  updated_at: string
  result: {
    schema_version: string
    proposal: {
      formation: string | null
      players: Array<{
        source_text: string
        squad_role: 'starter' | 'bench'
        order: number
        player_id: number | null
        position: Position | null
        confidence: number
      }>
    }
    team_valid: boolean
    validation_issues: string[]
    parse_issues: string[]
    inferred_formation: string | null
    resolved_players: number
    vision_adapter: string | null
  } | null
  error: string | null
}

export interface ApiErrorShape {
  detail?: string | { code?: string; message?: string }
}
