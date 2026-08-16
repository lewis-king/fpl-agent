import {
  ArrowUpRightIcon,
  ArrowRightIcon,
  CaretDownIcon,
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
  squadMode: 'current' | 'model' | 'recommended'
  selectedPlayer: Player | null
  onSelectPlayer: (player: Player) => void
  onOpenEvidence: () => void
  onPreviewRecommendation: () => void
}

export function DecisionRail({
  workspace,
  squadMode,
  selectedPlayer,
  onSelectPlayer,
  onOpenEvidence,
  onPreviewRecommendation,
}: DecisionRailProps) {
  const modelPreview = squadMode === 'model' ? workspace.decision.model_squad : null
  const modelCaptain = modelPreview
    ? [...modelPreview.starters, ...modelPreview.bench].find((player) => player.captain)
    : null
  const horizonMax = Math.max(...workspace.decision.horizon.map((event) => event.expected_points))
  const captainInitials = workspace.decision.captain.captain_name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
  const receiptStatus = modelPreview
    ? 'Validated recommendation'
    : !workspace.squad.confirmed
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
          <h2 id="decision-title">{modelPreview ? 'Why this is the recommendation' : 'Your squad analysis'}</h2>
          <span className={`provisional-pill is-${workspace.freshness.status}`}>
            {workspace.freshness.status === 'stale' ? 'Model stale' : receiptStatus}
          </span>
        </div>
      </div>

      <WeeklyDecisionPanel
        decision={workspace.decision.weekly}
        phase={workspace.phase.phase}
      />

      {!modelPreview && !workspace.decision.captain.lineup_recommendation_aligned ? (
        <div className="lineup-decision">
          <span>1</span>
          <div>
            <small>Starting XI change</small>
            <strong>Start {workspace.decision.captain.promoted_player_names.join(', ')}</strong>
            <p>Bench {workspace.decision.captain.benched_player_names.join(', ')} before setting the armband.</p>
          </div>
        </div>
      ) : null}

      <div className={`captain-decision ${modelPreview || workspace.decision.captain.recommendation_aligned ? 'is-aligned' : 'is-change'}`}>
        <div className="captain-monogram" aria-hidden="true">
          {modelPreview && modelCaptain
            ? modelCaptain.name.split(' ').map((part) => part[0]).join('').slice(0, 2)
            : captainInitials}
        </div>
        <div>
          <span>
            {modelPreview
              ? 'Recommended armband'
              : workspace.decision.captain.recommendation_aligned
              ? 'Armband matches model'
              : `${workspace.decision.captain.lineup_recommendation_aligned ? '1' : '2'}. Armband change suggested`}
          </span>
          {modelPreview || workspace.decision.captain.recommendation_aligned ? (
            <strong>{modelCaptain?.name ?? workspace.decision.captain.captain_name}</strong>
          ) : (
            <strong className="captain-switch">
              {workspace.decision.captain.current_captain_name}
              <ArrowRightIcon size={12} aria-hidden="true" />
              {workspace.decision.captain.captain_name}
            </strong>
          )}
          <small>
            {modelPreview
              ? `GW${modelPreview.event} captain in published candidate ${modelPreview.candidate_id}`
              : <>Recommended-XI lead +{workspace.decision.captain.score_edge.toFixed(2)} over{' '}
                  {workspace.decision.captain.vice_captain_name}; current vice is{' '}
                  {workspace.decision.captain.current_vice_captain_name}</>}
          </small>
        </div>
        {modelPreview || workspace.decision.captain.recommendation_aligned ? (
          <CheckCircleIcon size={21} weight="fill" aria-hidden="true" />
        ) : (
          <WarningCircleIcon size={21} weight="fill" aria-hidden="true" />
        )}
      </div>

      {!modelPreview && hasRecommendedChange ? (
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
            {selectedPlayer.team} · {selectedPlayer.fixtures.length
              ? selectedPlayer.fixtures.map((fixture) => fixture.label).join(' · ')
              : 'Fixture unavailable'} · £
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
          <div className={`participation-focus is-${selectedPlayer.participation.evidence_status}`}>
            <div>
              <strong>{selectedPlayer.participation.headline}</strong>
              <small>{selectedPlayer.participation.detail}</small>
            </div>
            <div className="appearance-bands" aria-label="Modelled minutes distribution">
              <span><small>DNP</small><strong>{formatPercent(selectedPlayer.participation.states.dnp)}</strong></span>
              <span><small>1–59</small><strong>{formatPercent(selectedPlayer.participation.states.minutes_1_59)}</strong></span>
              <span><small>60–89</small><strong>{formatPercent(selectedPlayer.participation.states.minutes_60_89)}</strong></span>
              <span><small>90+</small><strong>{formatPercent(selectedPlayer.participation.states.minutes_90_plus)}</strong></span>
            </div>
          </div>
        </div>
      ) : null}

      {modelPreview ? (
        <div className="model-preview-receipt">
          <span>Authoritative 15-player decision</span>
          <strong>{modelPreview.formation} · £{modelPreview.budget_spent.toFixed(1)}m</strong>
          <p>{modelPreview.selection_basis}</p>
          <small>This is the squad to enter in FPL. The app remains read-only, so your synced team is unchanged until you make the moves there.</small>
        </div>
      ) : (
        <SquadAssessment workspace={workspace} onSelectPlayer={onSelectPlayer} />
      )}

      {workspace.phase.phase === 'preseason' && !modelPreview ? <details className="rail-disclosure critique-disclosure">
        <summary>
          <span>
            <MagnifyingGlassIcon size={15} aria-hidden="true" />
            {workspace.squad.source === 'uploaded' ? 'Draft critique' : 'Why this squad?'}
          </span>
          <strong>{workspace.critique.expected_points_delta >= 0 ? '+' : ''}{workspace.critique.expected_points_delta.toFixed(2)}</strong>
          <CaretDownIcon size={14} aria-hidden="true" />
        </summary>
        <div className={`critique-block is-${workspace.critique.status}`}>
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
      </details> : null}

      {workspace.freshness.status !== 'fresh' ? (
        <div className={`freshness-warning is-${workspace.freshness.status}`}>
          <ClockCountdownIcon size={20} aria-hidden="true" />
          <div>
            <strong>
              {workspace.freshness.status === 'stale'
                ? 'Forecast inputs are stale'
                : 'Forecast refresh approaching'}
            </strong>
            <span>Inputs observed {formatObservedAt(workspace.freshness.observed_at)} · model built {formatObservedAt(workspace.freshness.model_generated_at)}</span>
            {workspace.freshness.squad_synced_at ? <small>FPL squad separately synced {formatObservedAt(workspace.freshness.squad_synced_at)}</small> : null}
            {workspace.freshness.refresh_required ? <small>Final deadline rerun still required before lock.</small> : null}
          </div>
        </div>
      ) : null}

      <details className="rail-disclosure evidence-disclosure">
        <summary>
          <span><DatabaseIcon size={15} aria-hidden="true" />Model evidence</span>
          <strong>{workspace.freshness.status}</strong>
          <CaretDownIcon size={14} aria-hidden="true" />
        </summary>
        <div className="evidence-disclosure-body">
          {workspace.freshness.status === 'fresh' ? (
            <div className={`freshness-warning is-${workspace.freshness.status}`}>
              <ClockCountdownIcon size={20} aria-hidden="true" />
              <div>
                <strong>Forecast inputs are current</strong>
                <span>Inputs observed {formatObservedAt(workspace.freshness.observed_at)} · model built {formatObservedAt(workspace.freshness.model_generated_at)}</span>
                {workspace.freshness.squad_synced_at ? <small>FPL squad separately synced {formatObservedAt(workspace.freshness.squad_synced_at)}</small> : null}
                {workspace.freshness.refresh_required ? <small>Final deadline rerun still required before lock.</small> : null}
              </div>
            </div>
          ) : null}

          <div className="horizon-block">
            <div className="insight-title-row">
              <span>Opening horizon</span>
              <small>
                GW{workspace.decision.horizon[0]?.event ?? (workspace.phase.decision_event ?? workspace.phase.event)}–
                {workspace.decision.horizon.at(-1)?.event ?? (workspace.phase.decision_event ?? workspace.phase.event)}
              </small>
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
        </div>
      </details>
    </section>
  )
}
