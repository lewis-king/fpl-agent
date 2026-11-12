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

function chipLabel(value: string) {
  if (value === 'no_chip') return 'Save chips'
  if (value === 'schedule_watch') return 'Fixture watch'
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
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
  const alternativePointEdge = alternative?.projected_points !== null
    && alternative?.projected_points !== undefined
    && selected.projected_points !== null
      ? alternative.projected_points - selected.projected_points
      : null
  const retainedRoleWatch = (decision.retained_role_watches ?? [])[0]
  // Older running APIs already expose candidate evidence; show the caution
  // immediately without requiring a refresh or changing the saved squad.
  const chipNeedsReview = decision.chip_advice?.needs_review || (
    decision.chip_advice?.recommendation === 'no_chip'
    && decision.chip_advice.candidate_statuses?.some(candidate =>
      ['research_only', 'needs_review'].includes(candidate.status)
      && (candidate.joint_net_value ?? 0) > 0)
  )

  return (
    <section className="weekly-decision" aria-labelledby="weekly-decision-title">
      <div className="weekly-decision-topline">
        <span>GW{decision.event} model call</span>
        <small>{chipNeedsReview ? 'Chip review needed' : decision.promotion_status.replaceAll('_', ' ')}</small>
      </div>

      <div className="weekly-decision-headline">
        <span className="weekly-route-icon" aria-hidden="true">
          {change
            ? <ArrowsLeftRightIcon size={19} />
            : <CheckCircleIcon size={19} weight="fill" />}
        </span>
        <div>
          <h3 id="weekly-decision-title">{chipNeedsReview ? 'Review chips before making transfers' : selected.label}</h3>
          <p>{chipNeedsReview
            ? `Saved no-chip route: ${selected.label}. This is conditional, not a final instruction: a chip alternative still needs validation.`
            : decision.explanation}</p>
        </div>
        <strong>{change ? signed(decision.expected_gain_vs_roll) : 'Hold'}</strong>
      </div>

      {selected.transfers.length ? (
        <div className="weekly-transfers" aria-label={chipNeedsReview ? 'Conditional transfer route' : 'Recommended transfers'}>
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

      {change ? (
        <div className="weekly-confidence" aria-label="Decision confidence">
          <div>
            <span>Simulation mean CI · 95%</span>
            <strong>{signed(decision.confidence_low)} to {signed(decision.confidence_high)}</strong>
          </div>
          <div>
            <span>Simulated win rate</span>
            <strong>{decision.beat_roll_probability === null ? '—' : formatPercent(decision.beat_roll_probability)}</strong>
          </div>
          <div>
            <span>Worst model world</span>
            <strong>{signed(decision.worst_scenario_gain)}</strong>
          </div>
        </div>
      ) : (
        <div className="weekly-confidence" aria-label="Hold decision context">
          <div>
            <span>GW{decision.event} projection</span>
            <strong>{selected.projected_points?.toFixed(1) ?? '—'}</strong>
          </div>
          <div>
            <span>Closest move · raw xP</span>
            <strong>{signed(alternativePointEdge)}</strong>
          </div>
          <div>
            <span>Cross-scenario regret</span>
            <strong>{decision.robust_regret?.toFixed(2) ?? '—'}</strong>
          </div>
        </div>
      )}

      <div className="weekly-team-call">
        {selected.projected_points !== null ? <span><small>Projected</small><strong>{selected.projected_points.toFixed(1)}</strong></span> : null}
        <span><small>Shape</small><strong>{selected.formation}</strong></span>
        <span><small>Captain</small><strong>{selected.captain_name}</strong></span>
        <span><small>Next FT</small><strong>{selected.next_free_transfers ?? '—'}</strong></span>
      </div>

      {change ? (
        <details className="weekly-guardrails">
          <summary><span>About these estimates</span><strong>Not an outcome guarantee</strong></summary>
          <div className="weekly-guardrail-body">
            <div>
              <strong>Simulation precision is not forecast certainty</strong>
              <span>
                The headline {signed(decision.expected_gain_vs_roll)} combines model worlds.
                The interval describes Monte Carlo precision around the mean
                {decision.confidence_mean != null ? ` (${signed(decision.confidence_mean)})` : ''}
                {decision.confidence_scenario ? ` in ${decision.confidence_scenario.replaceAll('_', ' ')}` : ' in one model world'}.
                It is not a 95% range for the points you will actually gain and does not include all model error.
              </span>
              <span>
                Win rate is simulated, not a calibrated probability of success.
                Worst model world compares average results, not the worst possible football outcome.
              </span>
              {decision.objective_tradeoff ? (
                <span>
                  Safety checks give up {decision.objective_tradeoff.mean_points_sacrificed_to_safety_gates.toFixed(2)}
                  {' '}weighted model points; cross-model protection gives up another{' '}
                  {decision.objective_tradeoff.mean_points_sacrificed_to_robust_ranking.toFixed(2)}.
                  These are horizon trade-offs against the highest-mean tested route, not proven points losses.
                </span>
              ) : null}
            </div>
          </div>
        </details>
      ) : null}

      {decision.chip_advice || decision.execution_timing ? (
        <details className="weekly-guardrails" open={chipNeedsReview || undefined}>
          <summary>
            <span>Chip &amp; timing</span>
            <strong>
              {chipNeedsReview ? 'Review before taking a hit'
                : decision.chip_advice ? chipLabel(decision.chip_advice.recommendation) : ''}
              {decision.chip_advice && decision.execution_timing ? ' · ' : ''}
              {decision.execution_timing?.recommendation === 'wait' ? 'Wait to execute' : ''}
            </strong>
          </summary>
          <div className="weekly-guardrail-body">
            {decision.chip_advice ? (
              <div>
                <small>Chip call</small>
                <strong>{chipNeedsReview ? 'Chip decision unresolved' : decision.chip_advice.headline}</strong>
                <span>{chipNeedsReview
                  ? 'A chip route has a positive modelled advantage but has not cleared its evidence checks. No chip is authorised; saving it has not been proven better. The saved transfer plan assumes no chip — review this before paying for transfers.'
                  : decision.chip_advice.detail}</span>
                {decision.chip_advice.candidate_statuses?.length ? (
                  <ul className="weekly-chip-statuses" aria-label="Chip evaluation status">
                    {decision.chip_advice.candidate_statuses.map((candidate) => (
                      <li key={candidate.chip}>
                        <strong>{chipLabel(candidate.chip)}</strong>
                        <span>{candidate.status === 'research_only' ? 'Research only · not validated'
                          : candidate.status === 'not_evaluated' ? 'Not evaluated'
                          : candidate.status === 'needs_review' ? 'Evidence needs review'
                          : candidate.status === 'play' ? 'Play this week' : 'Retain this week'}</span>
                        {candidate.joint_net_value != null ? (
                          <span>{signed(candidate.joint_net_value)} model points vs retaining</span>
                        ) : null}
                        {candidate.blockers.length ? <span>Checks not cleared: {candidate.blockers.join('; ')}.</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {decision.chip_advice.half_expiry_event !== null ? (
                  <em>
                    Current set expires at GW{decision.chip_advice.half_expiry_event}
                    {decision.chip_advice.events_until_expiry !== null
                      ? ` · ${decision.chip_advice.events_until_expiry} decisions remain`
                      : ''}
                  </em>
                ) : null}
                {decision.chip_advice.deadline_plan?.length ? (
                  <ul className="weekly-chip-statuses" aria-label="Chip plan before expiry">
                    {decision.chip_advice.deadline_plan.map((row) => (
                      <li key={`plan-${row.chip}`}>
                        <strong>{chipLabel(row.chip)}</strong>
                        <span>{row.play_now ? 'Play now' : `Planned GW${row.planned_event}`}</span>
                        {row.expected_gain != null ? (
                          <span>About {Math.round(row.expected_gain)} points</span>
                        ) : null}
                        <span>Latest safe GW{row.latest_safe_event}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {decision.chip_advice.next_opportunities.length ? (
                  <div className="chip-opportunity-strip" aria-label="Upcoming chip opportunities">
                    {decision.chip_advice.next_opportunities.slice(0, 4).map((opportunity) => (
                      <span key={`${opportunity.event}-${opportunity.chip}`}>
                        <small>GW{opportunity.event}</small>
                        <strong>{chipLabel(opportunity.chip)}</strong>
                        <em>
                          {opportunity.projected_uplift !== null
                            ? `+${opportunity.projected_uplift.toFixed(1)} projected`
                            : opportunity.schedule_note}
                        </em>
                      </span>
                    ))}
                  </div>
                ) : null}
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

      {retainedRoleWatch ? (
        <details className="weekly-guardrails weekly-role-challenge">
          <summary>
            <span>Role-risk challenge</span>
            <strong>
              {retainedRoleWatch.selected_action_sells_player
                ? `Sell ${retainedRoleWatch.player_name}`
                : `Why retain ${retainedRoleWatch.player_name}?`}
            </strong>
          </summary>
          <div className="weekly-guardrail-body">
            <div className={retainedRoleWatch.forced_sale_beats_selected ? 'is-attention' : ''}>
              <small>Live role evidence</small>
              <strong>
                {retainedRoleWatch.expected_minutes.toFixed(0)} expected minutes ·{' '}
                {formatPercent(retainedRoleWatch.play_probability)} appearance
              </strong>
              <span>
                The model forced an exact sale route into the same simulations:{' '}
                {retainedRoleWatch.best_forced_sale_transfers
                  .map((transfer) => `${transfer.outgoing_name} → ${transfer.incoming_name}`)
                  .join(' · ')}.
              </span>
              <em>
                Ranked #{retainedRoleWatch.best_forced_sale_rank} ·{' '}
                {retainedRoleWatch.forced_sale_delta_to_selected >= 0 ? '+' : ''}
                {retainedRoleWatch.forced_sale_delta_to_selected.toFixed(2)} points versus the selected route
              </em>
            </div>
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
