import assert from 'node:assert/strict'
import test from 'node:test'
import { lastValidatedAt, refreshIdentity, refreshScheduleCopy, refreshSyncState, refreshTitle } from '../src/refreshStatus.ts'
import type { DeadlineSchedule, WorkspaceRefresh } from '../src/types.ts'

const run = (values: Partial<WorkspaceRefresh> = {}) => ({
  run_id: 'refresh-gw4', status: 'not_ready', event: 4,
  started_at: '2026-09-09T07:04:19Z', completed_at: '2026-09-09T07:04:32Z',
  message: 'Reconnect FPL: the previous private squad snapshot predates GW3.',
  ...values,
} as WorkspaceRefresh)

test('missing manager state is not described as a running role check', () => {
  assert.equal(refreshSyncState(run()), 'attention')
  assert.equal(refreshTitle('attention', run()), 'GW4 refresh needs input — not running')
  assert.match(refreshScheduleCopy(run(), null), /Waiting for the input/)
})

test('server-started jobs and terminal results map to the right states', () => {
  assert.equal(refreshSyncState(run({ status: 'running' })), 'syncing')
  assert.equal(refreshSyncState(run({ status: 'published' })), 'success')
  assert.equal(refreshSyncState(run({ status: 'reused' })), 'success')
  assert.equal(refreshSyncState(run({ status: 'failed' })), 'error')
  assert.equal(refreshSyncState(run({ status: 'blocked' })), 'attention')
})

test('a failed attempt is never presented as a successful validation', () => {
  assert.equal(lastValidatedAt(run(), null, 4), null)
  assert.equal(lastValidatedAt(run({ status: 'failed' }), null, 4), null)
})

test('previous-gameweek success is not a current-gameweek validation', () => {
  const old = run({ status: 'published', event: 3 })
  const schedule = { event: 3, last_validated_at: old.completed_at } as DeadlineSchedule
  assert.equal(lastValidatedAt(old, schedule, 4), null)
})

test('latest successful worker timestamp wins over a lagging scheduler', () => {
  const success = run({ status: 'published', completed_at: '2026-09-09T07:13:32Z' })
  const schedule = { event: 4, last_validated_at: '2026-09-09T06:00:00Z' } as DeadlineSchedule
  assert.equal(lastValidatedAt(success, schedule, 4), success.completed_at)
})

test('stage, terminal and external run changes are observed', () => {
  const running = run({ status: 'running', completed_at: null })
  assert.notEqual(refreshIdentity(running), refreshIdentity(run({ status: 'published' })))
  assert.notEqual(refreshIdentity(running), refreshIdentity({ ...running, current_stage: 'weekly_validation' }))
  assert.notEqual(refreshIdentity(running), refreshIdentity({ ...running, run_id: 'other-tab-run' }))
})
