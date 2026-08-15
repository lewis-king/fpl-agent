import {
  ArrowRightIcon,
  ArrowsLeftRightIcon,
  CheckCircleIcon,
  ClockCountdownIcon,
  ShieldWarningIcon,
} from '@phosphor-icons/react'

import { formatPercent } from '../lib'
import type { WeeklyAction, WeeklyDecision, Workspace } from '../types'

interface WeeklyDecisionPanelProps {
  decision: WeeklyDecision
  phase: Workspace['phase']['phase']
}

function signed(value: number | null, digits = 2) {
  if (value === null) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

function actionDetail(action: WeeklyAction) {
  if (action.route_type === 'roll') {
    return `${action.next_free_transfers ?? '—'} free transfers at the next deadline`
  }
  if (action.incremental_points_cost > 0) {
    return `${action.incremental_points_cost}-point cost included`
  }
  return `${action.next_free_transfers ?? '—'} free transfer${action.next_free_transfers === 1 ? '' : 's'} retained`
}

export function WeeklyDecisionPanel({ decision, phase }: WeeklyDecisionPanelProps) {
  if (decision.status === 'not_available' && phase === 'preseason') return null

  if (decision.status !== 'ready' || !decision.selected) {
    const blocked = decision.status === 'blocked'
    return (
      <section className={`weekly-decision-empty ${blocked ? 'is-blocked' : ''}`} aria-label="Weekly decision status">
        {blocked
          ? <ShieldWarningIcon size={19} weight="fill" aria-hidden="true" />
          : <ClockCountdownIcon size={19} aria-hidden="true" />}
        <div>
          <span>{blocked ? 'Weekly receipt blocked' : `GW${decision.event} action pending`}</span>
          <p>{decision.explanation}</p>
        </div>
      </section>
    )
  }

  const selected = decision.selected
  const alternative = decision.strongest_rejected
  const change = selected.route_type !== 'roll'

  return (
    <section className="weekly-decision" aria-labelledby="weekly-decision-title">
      <div className="weekly-decision-topline">
        <span>GW{decision.event} model call</span>
        <small>{decision.promotion_status.replaceAll('_', ' ')}</small>
      </div>

      <div className="weekly-decision-headline">
        <span className="weekly-route-icon" aria-hidden="true">
          {change
            ? <ArrowsLeftRightIcon size={19} />
            : <CheckCircleIcon size={19} weight="fill" />}
        </span>
        <div>
          <h3 id="weekly-decision-title">{selected.label}</h3>
          <p>{decision.explanation}</p>
        </div>
        <strong>{signed(decision.expected_gain_vs_roll)}</strong>
      </div>

      {selected.transfers.length ? (
        <div className="weekly-transfers" aria-label="Recommended transfers">
          {selected.transfers.map((transfer) => (
            <div key={`${transfer.outgoing_player_id}-${transfer.incoming_player_id}`}>
              <span><small>Sell</small><strong>{transfer.outgoing_name}</strong></span>
              <ArrowRightIcon size={13} aria-hidden="true" />
              <span><small>Buy · £{transfer.incoming_price.toFixed(1)}m</small><strong>{transfer.incoming_name}</strong></span>
            </div>
          ))}
        </div>
      ) : (
        <div className="weekly-roll-line">
          <span>No transfer</span>
          <strong>{actionDetail(selected)}</strong>
        </div>
      )}

      <div className="weekly-confidence" aria-label="Decision confidence">
        <div>
          <span>Paired 95% range</span>
          <strong>{signed(decision.confidence_low)} to {signed(decision.confidence_high)}</strong>
        </div>
        <div>
          <span>Beats roll</span>
          <strong>{decision.beat_roll_probability === null ? '—' : formatPercent(decision.beat_roll_probability)}</strong>
        </div>
        <div>
          <span>Worst model world</span>
          <strong>{signed(decision.worst_scenario_gain)}</strong>
        </div>
      </div>

      <div className="weekly-team-call">
        {selected.projected_points !== null ? <span><small>Projected</small><strong>{selected.projected_points.toFixed(1)}</strong></span> : null}
        <span><small>Shape</small><strong>{selected.formation}</strong></span>
        <span><small>Captain</small><strong>{selected.captain_name}</strong></span>
        <span><small>Next FT</small><strong>{selected.next_free_transfers ?? '—'}</strong></span>
      </div>

      {decision.chip_advice || decision.execution_timing ? (
        <details className="weekly-guardrails">
          <summary>
            <span>Chip &amp; timing</span>
            <strong>
              {decision.chip_advice ? 'Save chips' : ''}
              {decision.chip_advice && decision.execution_timing ? ' · ' : ''}
              {decision.execution_timing?.recommendation === 'wait' ? 'Wait to execute' : ''}
            </strong>
          </summary>
          <div className="weekly-guardrail-body">
            {decision.chip_advice ? (
              <div>
                <small>Chip call</small>
                <strong>{decision.chip_advice.headline}</strong>
                <span>{decision.chip_advice.detail}</span>
              </div>
            ) : null}
            {decision.execution_timing ? (
              <div className={decision.execution_timing.affordability_at_risk ? 'is-attention' : ''}>
                <small>Execution</small>
                <strong>{decision.execution_timing.headline}</strong>
                <span>{decision.execution_timing.detail}</span>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {alternative ? (
        <div className="weekly-alternative">
          <span>Strongest rejected</span>
          <strong>{alternative.label}</strong>
          <small>{actionDetail(alternative)}</small>
        </div>
      ) : null}
    </section>
  )
}
