import {
  ArrowClockwiseIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  ClockCountdownIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'

import { formatObservedAt } from '../lib'
import type { DeadlineSchedule, Workspace } from '../types'

interface DeadlineCockpitProps {
  workspace: Workspace
  schedule: DeadlineSchedule | null
  refreshing: boolean
  onViewRecommendation: () => void
  onRefresh: () => void
}

export function DeadlineCockpit({
  workspace,
  schedule,
  refreshing,
  onViewRecommendation,
  onRefresh,
}: DeadlineCockpitProps) {
  const comparison = workspace.decision.comparison
  const delta = comparison.expected_points_delta
  const incoming = comparison.incoming.map((player) => player.name).join(', ')
  const outgoing = comparison.outgoing.map((player) => player.name).join(', ')
  const ready = comparison.status !== 'awaiting_refresh'
    && workspace.freshness.status !== 'stale'
  const nextCheck = schedule?.next_window_at
    ? formatObservedAt(schedule.next_window_at)
    : 'after the next evidence check'
  const cadenceDetail = refreshing || schedule?.status === 'running'
    ? 'A full validation is running now'
    : `Next automatic validation ${nextCheck}`
  const recommendationLabel = comparison.authoritative_squad === 'weekly'
    ? 'View recommended moves'
    : 'View recommended squad'

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
      ) : (
        <div className="deadline-aligned">
          <CheckCircleIcon size={17} weight="fill" aria-hidden="true" />
          <span>All 15 player selections are aligned.</span>
        </div>
      )}

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
          {refreshing ? 'Refreshing…' : 'Check evidence now'}
        </button>
        <button className="primary-button" type="button" onClick={onViewRecommendation}>
          {recommendationLabel}
          <span className="button-island"><ArrowRightIcon size={14} aria-hidden="true" /></span>
        </button>
      </div>
    </section>
  )
}
