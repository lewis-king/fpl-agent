import type {
  ApiErrorShape,
  ChatResult,
  GenerateSquadRequest,
  GenerateSquadResult,
  ManagerProfile,
  McpConnection,
  McpLoginStarted,
  McpLoginStatus,
  McpSyncResult,
  PreseasonOptions,
  UploadAccepted,
  UploadStatus,
  Workspace,
  WorkspaceRefresh,
} from './types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code = 'request_failed', status = 500) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

function normalizeWorkspace(workspace: Workspace): Workspace {
  // Keep the client usable during a rolling/local restart where Vite has the newest bundle but
  // the already-running Python process still serves the immediately previous v1 shape.
  const players = [...workspace.squad.starters, ...workspace.squad.bench]
  const captain = workspace.decision.captain
  const currentCaptain = players.find((player) => player.captain)
    ?? players.find((player) => player.player_id === captain.captain_player_id)
  const currentViceCaptain = players.find((player) => player.vice_captain)
    ?? players.find((player) => player.player_id === captain.vice_captain_player_id)
  const currentCaptainId = captain.current_captain_player_id ?? currentCaptain?.player_id
    ?? captain.captain_player_id
  const currentViceCaptainId = captain.current_vice_captain_player_id ?? currentViceCaptain?.player_id
    ?? captain.vice_captain_player_id
  const freshness = workspace.freshness

  return {
    ...workspace,
    freshness: {
      ...freshness,
      model_generated_at: freshness.model_generated_at ?? workspace.generated_at,
      squad_synced_at: freshness.squad_synced_at
        ?? (workspace.squad.source === 'connected'
          ? workspace.user.last_synced_at ?? freshness.observed_at
          : null),
    },
    decision: {
      ...workspace.decision,
      weekly: workspace.decision.weekly ?? {
        status: 'not_available',
        event: workspace.phase.event,
        created_at: null,
        selected: null,
        strongest_rejected: null,
        expected_gain_vs_roll: null,
        confidence_low: null,
        confidence_high: null,
        beat_roll_probability: null,
        worst_scenario_gain: null,
        robust_regret: null,
        promotion_status: 'awaiting_complete_manager_state',
        explanation: 'The weekly action receipt is not available yet.',
        receipt_path: null,
        receipt_sha256: null,
      },
      captain: {
        ...captain,
        current_captain_player_id: currentCaptainId,
        current_captain_name: captain.current_captain_name ?? currentCaptain?.name
          ?? captain.captain_name,
        current_vice_captain_player_id: currentViceCaptainId,
        current_vice_captain_name: captain.current_vice_captain_name ?? currentViceCaptain?.name
          ?? captain.vice_captain_name,
        recommendation_aligned: captain.recommendation_aligned
          ?? (currentCaptainId === captain.captain_player_id
            && currentViceCaptainId === captain.vice_captain_player_id),
        lineup_recommendation_aligned: captain.lineup_recommendation_aligned ?? true,
        recommended_formation: captain.recommended_formation ?? workspace.squad.formation,
        promoted_player_ids: captain.promoted_player_ids ?? [],
        promoted_player_names: captain.promoted_player_names ?? [],
        benched_player_ids: captain.benched_player_ids ?? [],
        benched_player_names: captain.benched_player_names ?? [],
        evidence_status: captain.evidence_status ?? 'legacy_workspace_receipt',
      },
    },
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T
  let payload: ApiErrorShape = {}
  try {
    payload = (await response.json()) as ApiErrorShape
  } catch {
    // The fallback below is intentionally user-safe.
  }
  const detail = payload.detail
  const message =
    typeof detail === 'string'
      ? detail
      : detail?.message ?? 'The local application service could not complete the request.'
  const code = typeof detail === 'object' ? detail?.code : undefined
  throw new ApiError(message, code, response.status)
}

export async function getWorkspace(signal?: AbortSignal): Promise<Workspace> {
  const response = await fetch('/api/v1/workspace', { signal })
  return normalizeWorkspace(await parseResponse<Workspace>(response))
}

export async function startWorkspaceRefresh(
  reason: 'app_open' | 'manual',
  signal?: AbortSignal,
): Promise<WorkspaceRefresh> {
  const response = await fetch('/api/v1/workspace/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
    signal,
  })
  return parseResponse<WorkspaceRefresh>(response)
}

export async function getWorkspaceRefresh(signal?: AbortSignal): Promise<WorkspaceRefresh> {
  const response = await fetch('/api/v1/workspace/refresh', { signal })
  return parseResponse<WorkspaceRefresh>(response)
}

export async function getPreseasonOptions(signal?: AbortSignal): Promise<PreseasonOptions> {
  const response = await fetch('/api/v1/preseason/options', { signal })
  return parseResponse<PreseasonOptions>(response)
}

export async function generateSquad(
  request: GenerateSquadRequest,
  signal?: AbortSignal,
): Promise<GenerateSquadResult> {
  const response = await fetch('/api/v1/preseason/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  return parseResponse<GenerateSquadResult>(response)
}

export async function activatePublishedSquad(signal?: AbortSignal): Promise<GenerateSquadResult> {
  const response = await fetch('/api/v1/preseason/use-published', {
    method: 'POST',
    signal,
  })
  return parseResponse<GenerateSquadResult>(response)
}

export async function saveManagerProfile(
  displayName: string,
  fplEntryId: number,
  signal?: AbortSignal,
): Promise<ManagerProfile> {
  const response = await fetch('/api/v1/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, fpl_entry_id: fplEntryId }),
    signal,
  })
  return parseResponse<ManagerProfile>(response)
}

export async function getMcpConnection(signal?: AbortSignal): Promise<McpConnection> {
  const response = await fetch('/api/v1/integrations/fpl', { signal })
  return parseResponse<McpConnection>(response)
}

export async function beginMcpLogin(signal?: AbortSignal): Promise<McpLoginStarted> {
  const response = await fetch('/api/v1/integrations/fpl/login', {
    method: 'POST',
    signal,
  })
  return parseResponse<McpLoginStarted>(response)
}

export async function pollMcpLogin(
  requestId: string,
  signal?: AbortSignal,
): Promise<McpLoginStatus> {
  const response = await fetch(`/api/v1/integrations/fpl/login/${requestId}`, { signal })
  return parseResponse<McpLoginStatus>(response)
}

export async function syncMcpSquad(signal?: AbortSignal): Promise<McpSyncResult> {
  const response = await fetch('/api/v1/integrations/fpl/sync', {
    method: 'POST',
    signal,
  })
  return parseResponse<McpSyncResult>(response)
}

export async function sendChat(
  message: string,
  sessionId: string | null,
  signal?: AbortSignal,
): Promise<ChatResult> {
  const response = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      manager_id: 1,
      event: 1,
    }),
    signal,
  })
  return parseResponse<ChatResult>(response)
}

export async function uploadTeam(file: File, signal?: AbortSignal): Promise<UploadAccepted> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/v1/uploads/team', {
    method: 'POST',
    body: form,
    signal,
  })
  return parseResponse<UploadAccepted>(response)
}

export async function analyseUpload(uploadId: string): Promise<void> {
  const response = await fetch(`/api/v1/uploads/${uploadId}/analyse`, { method: 'POST' })
  await parseResponse(response)
}

export async function getUploadStatus(uploadId: string): Promise<UploadStatus> {
  const response = await fetch(`/api/v1/uploads/${uploadId}`)
  return parseResponse<UploadStatus>(response)
}

export async function confirmUpload(uploadId: string): Promise<void> {
  const response = await fetch(`/api/v1/uploads/${uploadId}/confirm`, { method: 'POST' })
  await parseResponse(response)
}
