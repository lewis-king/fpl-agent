import {
  ArrowUpRightIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  ClockCountdownIcon,
  DatabaseIcon,
  MagnifyingGlassIcon,
  ShieldWarningIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'

import { formatObservedAt, formatPercent } from '../lib'
import type { Player, Workspace } from '../types'
import { SquadAssessment } from './SquadAssessment'
import { WeeklyDecisionPanel } from './WeeklyDecisionPanel'

interface DecisionRailProps {
  workspace: Workspace
  selectedPlayer: Player | null
  onSelectPlayer: (player: Player) => void
  onOpenEvidence: () => void
  onPreviewRecommendation: () => void
}

export function DecisionRail({
  workspace,
  selectedPlayer,
  onSelectPlayer,
  onOpenEvidence,
  onPreviewRecommendation,
}: DecisionRailProps) {
  const horizonMax = Math.max(...workspace.decision.horizon.map((event) => event.expected_points))
  const captainInitials = workspace.decision.captain.captain_name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
  const receiptStatus = !workspace.squad.confirmed
    ? 'Provisional'
    : workspace.squad.source === 'connected'
      ? 'FPL squad'
      : workspace.squad.source === 'uploaded'
        ? 'Draft confirmed'
        : 'Model proposal'
  const hasRecommendedChange = !workspace.decision.captain.lineup_recommendation_aligned
    || !workspace.decision.captain.recommendation_aligned

  return (
    <section className="decision-rail" id="decisions" aria-labelledby="decision-title">
      <div className="decision-heading">
        <span className="module-kicker">Decision receipt</span>
        <div className="heading-with-status">
          <h2 id="decision-title">Squad analysis</h2>
          <span className={`provisional-pill is-${workspace.freshness.status}`}>
            {workspace.freshness.status === 'stale' ? 'Model stale' : receiptStatus}
          </span>
        </div>
      </div>

      <WeeklyDecisionPanel
        decision={workspace.decision.weekly}
        phase={workspace.phase.phase}
      />

      {!workspace.decision.captain.lineup_recommendation_aligned ? (
        <div className="lineup-decision">
          <span>1</span>
          <div>
            <small>Starting XI change</small>
            <strong>Start {workspace.decision.captain.promoted_player_names.join(', ')}</strong>
            <p>Bench {workspace.decision.captain.benched_player_names.join(', ')} before setting the armband.</p>
          </div>
        </div>
      ) : null}

      <div className={`captain-decision ${workspace.decision.captain.recommendation_aligned ? 'is-aligned' : 'is-change'}`}>
        <div className="captain-monogram" aria-hidden="true">
          {captainInitials}
        </div>
        <div>
          <span>
            {workspace.decision.captain.recommendation_aligned
              ? 'Armband matches model'
              : `${workspace.decision.captain.lineup_recommendation_aligned ? '1' : '2'}. Armband change suggested`}
          </span>
          {workspace.decision.captain.recommendation_aligned ? (
            <strong>{workspace.decision.captain.captain_name}</strong>
          ) : (
            <strong className="captain-switch">
              {workspace.decision.captain.current_captain_name}
              <ArrowRightIcon size={12} aria-hidden="true" />
              {workspace.decision.captain.captain_name}
            </strong>
          )}
          <small>
            Recommended-XI lead +{workspace.decision.captain.score_edge.toFixed(2)} over{' '}
            {workspace.decision.captain.vice_captain_name}; current vice is{' '}
            {workspace.decision.captain.current_vice_captain_name}
          </small>
        </div>
        {workspace.decision.captain.recommendation_aligned ? (
          <CheckCircleIcon size={21} weight="fill" aria-hidden="true" />
        ) : (
          <WarningCircleIcon size={21} weight="fill" aria-hidden="true" />
        )}
      </div>

      {hasRecommendedChange ? (
        <button className="preview-lineup" type="button" onClick={onPreviewRecommendation}>
          Preview the recommended XI and armband
          <ArrowRightIcon size={14} aria-hidden="true" />
        </button>
      ) : null}

      {selectedPlayer ? (
        <div className="selected-player-insight">
          <div className="insight-title-row">
            <span>Player focus</span>
            <small>{selectedPlayer.position}</small>
          </div>
          <h3>{selectedPlayer.name}</h3>
          <p>
            {selectedPlayer.team} · {selectedPlayer.fixture?.label ?? 'Fixture unavailable'} · £
            {selectedPlayer.price.toFixed(1)}m
          </p>
          <div className="player-metrics">
            <div>
              <span>Robust xP</span>
              <strong>{selectedPlayer.robust_points.toFixed(2)}</strong>
            </div>
            <div>
              <span>Minutes</span>
              <strong>{selectedPlayer.expected_minutes.toFixed(1)}</strong>
            </div>
            <div>
              <span>Plays</span>
              <strong>{formatPercent(selectedPlayer.play_probability)}</strong>
            </div>
          </div>
        </div>
      ) : null}

      <SquadAssessment workspace={workspace} onSelectPlayer={onSelectPlayer} />

      <div className={`critique-block is-${workspace.critique.status}`}>
        <div className="critique-status-row">
          <MagnifyingGlassIcon size={16} aria-hidden="true" />
          <span>{workspace.squad.source === 'uploaded' ? 'Uploaded draft critique' : 'Candidate assessment'}</span>
          <strong>{workspace.critique.expected_points_delta >= 0 ? '+' : ''}{workspace.critique.expected_points_delta.toFixed(2)}</strong>
        </div>
        <h3>{workspace.critique.headline}</h3>
        <p>{workspace.critique.summary}</p>
        {workspace.critique.concerns.slice(0, 3).map((item) => (
          <div className="critique-point is-concern" key={item.code}>
            <WarningCircleIcon size={14} weight="fill" aria-hidden="true" />
            <span><strong>{item.title}</strong><small>{item.detail}</small></span>
          </div>
        ))}
        {!workspace.critique.concerns.length ? workspace.critique.strengths.slice(0, 1).map((item) => (
          <div className="critique-point" key={item.code}>
            <CheckCircleIcon size={14} weight="fill" aria-hidden="true" />
            <span><strong>{item.title}</strong><small>{item.detail}</small></span>
          </div>
        )) : null}
      </div>

      <div className={`freshness-warning is-${workspace.freshness.status}`}>
        <ClockCountdownIcon size={20} aria-hidden="true" />
        <div>
          <strong>
            {workspace.freshness.status === 'stale'
              ? 'Forecast inputs are stale'
              : workspace.freshness.status === 'attention'
                ? 'Forecast refresh approaching'
                : 'Forecast inputs are current'}
          </strong>
          <span>Inputs observed {formatObservedAt(workspace.freshness.observed_at)} · model built {formatObservedAt(workspace.freshness.model_generated_at)}</span>
          {workspace.freshness.squad_synced_at ? <small>FPL squad separately synced {formatObservedAt(workspace.freshness.squad_synced_at)}</small> : null}
          {workspace.freshness.refresh_required ? <small>Final deadline rerun still required before lock.</small> : null}
        </div>
      </div>

      <div className="horizon-block">
        <div className="insight-title-row">
          <span>Opening horizon</span>
          <small>GW1–{workspace.decision.horizon.at(-1)?.event ?? 1}</small>
        </div>
        <div className="horizon-list">
          {workspace.decision.horizon.map((event) => (
            <div className="horizon-row" key={event.event}>
              <span>GW{event.event}</span>
              <div className="horizon-track">
                <span
                  className="horizon-fill"
                  style={{ '--bar-scale': event.expected_points / horizonMax } as React.CSSProperties}
                />
              </div>
              <strong>{event.expected_points.toFixed(1)}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="receipt-line">
        <ShieldWarningIcon size={18} aria-hidden="true" />
        <div>
          <span>Main uncertainty</span>
          <p>{workspace.decision.captain.main_risk}</p>
        </div>
      </div>

      <button className="evidence-link" type="button" onClick={onOpenEvidence}>
        <DatabaseIcon size={17} aria-hidden="true" />
        Inspect sources and receipt
        <ArrowUpRightIcon size={16} aria-hidden="true" />
      </button>
    </section>
  )
}
