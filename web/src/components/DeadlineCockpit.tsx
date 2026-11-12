import {
  ArrowClockwiseIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  ClockCountdownIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'

import { formatObservedAt } from '../lib'
import { lastValidatedAt } from '../refreshStatus'
import type { DeadlineSchedule, Workspace, WorkspaceRefresh } from '../types'

interface DeadlineCockpitProps {
  workspace: Workspace
  schedule: DeadlineSchedule | null
  refreshRun: WorkspaceRefresh | null
  refreshing: boolean
  onViewRecommendation: () => void
  onRefresh: () => void
}

export function DeadlineCockpit({
  workspace,
  schedule,
  refreshRun,
  refreshing,
  onViewRecommendation,
  onRefresh,
}: DeadlineCockpitProps) {
  const comparison = workspace.decision.comparison
  const handoff = workspace.deadline_handoff
  const delta = comparison.expected_points_delta
  const incoming = comparison.incoming.map((player) => player.name).join(', ')
  const outgoing = comparison.outgoing.map((player) => player.name).join(', ')
  const ready = comparison.status !== 'awaiting_refresh'
    && workspace.freshness.status !== 'stale'
    && (!handoff || handoff.status === 'ready')
  const event = workspace.phase.decision_event ?? workspace.phase.event
  const validatedAt = lastValidatedAt(refreshRun, schedule, event)
  const attemptedAt = refreshRun?.event === event ? refreshRun.started_at : schedule?.last_attempt_at
  const waitingForInput = refreshRun?.status === 'not_ready' || refreshRun?.status === 'blocked'
  const nextCheck = waitingForInput
    ? refreshRun?.status === 'not_ready' ? 'Waiting for input' : 'Paused until resolved'
    : refreshing || schedule?.status === 'running'
      ? 'Running now'
      : schedule?.next_window_at
    ? formatObservedAt(schedule.next_window_at)
    : 'Checking schedule…'
  const cadenceDetail = refreshing || schedule?.status === 'running'
    ? 'Runs on the server — you can leave this page'
    : waitingForInput ? 'Not running. Resolve the notice above, then retry.'
      : 'Earlier checks also run when material evidence changes'
  const recommendationLabel = comparison.authoritative_squad === 'weekly'
    || workspace.decision.recommended_squad.source === 'weekly_decision'
    ? 'View recommended moves'
    : comparison.authoritative_squad === 'model'
      ? 'View recommended squad'
      : 'View best lineup'
  const switchBoundaries = handoff?.boundaries
    .filter((boundary) => boundary.trigger_expected_minutes !== null)
    .map((boundary) => `${boundary.player_name} ≤${boundary.trigger_expected_minutes?.toFixed(0)}m`)
    .join(' · ')

  return (
    <section className={`deadline-cockpit is-${comparison.status}`} aria-labelledby="deadline-decision-title">
      <div className="deadline-command">
        <span className="decision-seal" aria-hidden="true">
          {ready
            ? <ShieldCheckIcon size={23} weight="fill" />
            : <WarningCircleIcon size={23} weight="fill" />}
        </span>
        <div>
          <span className="module-kicker">Deadline decision</span>
          <h2 id="deadline-decision-title">{comparison.headline}</h2>
          <p>{comparison.detail}</p>
        </div>
      </div>

      <div className="deadline-proof" aria-label="Recommendation proof">
        <div>
          <span>Recommendation</span>
          <strong>{comparison.recommendation_candidate_id ?? 'Pending'}</strong>
          <small>{comparison.authoritative_squad === 'model' ? '15-player model build' : 'legal weekly action'}</small>
        </div>
        <div>
          <span>Event xP delta</span>
          <strong className={delta !== null && delta < 0 ? 'is-tradeoff' : ''}>
            {delta === null ? '—' : `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(2)}`}
          </strong>
          <small>{delta !== null && delta < 0 ? 'multiweek trade-off' : 'versus your squad'}</small>
        </div>
        <div>
          <span>Validation</span>
          <strong>{comparison.validation_gates_passed}/{comparison.validation_gates_total || '—'}</strong>
          <small>{comparison.churn_protected ? 'churn protection active' : 'publication checks'}</small>
        </div>
      </div>

      {comparison.change_count > 0 ? (
        <div className="deadline-swaps">
          <p><span>In</span><strong>{incoming}</strong></p>
          <ArrowRightIcon size={15} aria-hidden="true" />
          <p><span>Out</span><strong>{outgoing}</strong></p>
        </div>
      ) : comparison.status !== 'awaiting_refresh' ? (
        <div className="deadline-aligned">
          <CheckCircleIcon size={17} weight="fill" aria-hidden="true" />
          <span>All 15 player selections are aligned.</span>
        </div>
      ) : null}

      {handoff ? (
        <div className="deadline-operating-plan" aria-label="Deadline operating plan">
          <div>
            <span>Chip instruction</span>
            <strong>{handoff.chip_label.replace('_', ' ')}</strong>
            <small>{handoff.chip_detail}</small>
          </div>
          <div>
            <span>Evidence switches</span>
            <strong>{switchBoundaries || 'Central squad holds'}</strong>
            <small>
              {handoff.precomputed_fallbacks} legal fallbacks from {handoff.route_count} tested routes
            </small>
          </div>
        </div>
      ) : null}

      <dl className="refresh-timeline" aria-label={`GW${event} refresh history`}>
        <div><dt>Last attempt</dt><dd>{attemptedAt ? formatObservedAt(attemptedAt) : 'Not yet run'}</dd></div>
        <div><dt>GW{event} last validated</dt><dd>{validatedAt ? formatObservedAt(validatedAt) : 'No validated decision yet'}</dd></div>
        <div><dt>Next automatic check</dt><dd>{nextCheck}</dd></div>
      </dl>

      <div className="deadline-actions">
        <div className="cadence-copy">
          <ClockCountdownIcon size={16} aria-hidden="true" />
          <span>
            <strong>{schedule?.cadence_label ?? 'Deadline-aware checks'}</strong>
            <small>{cadenceDetail}</small>
          </span>
        </div>
        <button className="secondary-button" type="button" onClick={onRefresh} disabled={refreshing}>
          <ArrowClockwiseIcon className={refreshing ? 'is-spinning' : ''} size={16} aria-hidden="true" />
          {refreshing ? 'Refreshing…' : waitingForInput ? 'Sync FPL & retry' : 'Refresh decisions'}
        </button>
        <button className="primary-button" type="button" onClick={onViewRecommendation} disabled={!ready}>
          {recommendationLabel}
          <span className="button-island"><ArrowRightIcon size={14} aria-hidden="true" /></span>
        </button>
      </div>
    </section>
  )
}
