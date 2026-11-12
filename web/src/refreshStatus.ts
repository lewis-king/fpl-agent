import type { DeadlineSchedule, WorkspaceRefresh } from './types'

export type SyncState = 'idle' | 'syncing' | 'success' | 'attention' | 'error'

export function refreshSyncState(run: WorkspaceRefresh): SyncState {
  if (run.status === 'running') return 'syncing'
  if (run.status === 'published' || run.status === 'reused') return 'success'
  if (run.status === 'blocked' || run.status === 'not_ready') return 'attention'
  if (run.status === 'failed') return 'error'
  return 'idle'
}

export function refreshTitle(state: SyncState, run: WorkspaceRefresh | null): string {
  const event = run?.event ? `GW${run.event} ` : ''
  if (state === 'syncing') return `${event}decision refresh running`
  if (state === 'success') return `${event}decision validated`
  if (state === 'attention') return `${event}refresh needs input — not running`
  return `${event}decision refresh failed — not running`
}

export function refreshIdentity(run: WorkspaceRefresh): string {
  return JSON.stringify([run.run_id, run.status, run.completed_at, run.current_stage, run.completed_stage_count, run.message])
}

export function lastValidatedAt(run: WorkspaceRefresh | null, schedule: DeadlineSchedule | null, event: number): string | null {
  const values = [
    run?.event === event && (run.status === 'published' || run.status === 'reused') ? run.completed_at : null,
    schedule?.event === event ? schedule.last_validated_at : null,
  ].filter((value): value is string => Boolean(value) && Number.isFinite(Date.parse(value!)))
  return values.sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null
}

export function refreshScheduleCopy(run: WorkspaceRefresh | null, schedule: DeadlineSchedule | null): string {
  if (run?.status === 'running' || schedule?.status === 'running') return 'Running in the background; you can leave this page.'
  if (run?.status === 'not_ready') return 'Waiting for the input above. Sync FPL or retry after resolving it.'
  if (run?.status === 'blocked') return 'Automatic retries paused for this evidence. Resolve the issue, then retry.'
  if (schedule?.status === 'error') return schedule.message
  if (schedule?.status === 'deadline_passed') return 'Deadline passed — no further changes for this gameweek.'
  return schedule?.message ?? 'Checking the automatic refresh schedule…'
}
