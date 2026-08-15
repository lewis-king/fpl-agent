import { ListBulletsIcon, SoccerBallIcon } from '@phosphor-icons/react'

import { groupByPosition, positionOrder } from '../lib'
import type { Player, Workspace } from '../types'
import { PlayerCard } from './PlayerCard'

interface SquadPitchProps {
  workspace: Workspace
  selectedPlayerId: number | null
  onSelectPlayer: (player: Player) => void
  view: 'pitch' | 'list'
  onViewChange: (view: 'pitch' | 'list') => void
  squadMode: 'current' | 'model' | 'recommended'
  onSquadModeChange: (mode: 'current' | 'model' | 'recommended') => void
}

export function SquadPitch({
  workspace,
  selectedPlayerId,
  onSelectPlayer,
  view,
  onViewChange,
  squadMode,
  onSquadModeChange,
}: SquadPitchProps) {
  const recommendedStarters = workspace.decision.recommended_squad.starters
  const recommendedBench = workspace.decision.recommended_squad.bench
  const modelSquad = workspace.decision.model_squad
  const modelStarters = modelSquad?.starters ?? []
  const modelBench = modelSquad?.bench ?? []
  const displayedStarters = squadMode === 'model' && modelSquad
    ? modelStarters
    : squadMode === 'recommended'
      ? recommendedStarters
      : workspace.squad.starters
  const displayedBench = squadMode === 'model' && modelSquad
    ? modelBench
    : squadMode === 'recommended'
      ? recommendedBench
      : workspace.squad.bench
  const grouped = groupByPosition(displayedStarters)
  const hasRecommendationChanges = !workspace.decision.captain.lineup_recommendation_aligned
    || !workspace.decision.captain.recommendation_aligned
  const currentIds = new Set([...workspace.squad.starters, ...workspace.squad.bench].map((player) => player.player_id))
  const modelOnlyIds = new Set(
    [...modelStarters, ...modelBench]
      .filter((player) => !currentIds.has(player.player_id))
      .map((player) => player.player_id),
  )
  const decisionEvent = workspace.phase.decision_event ?? workspace.phase.event
  const displayFormation = squadMode === 'model' && modelSquad
    ? modelSquad.formation
    : squadMode === 'recommended'
      ? workspace.decision.captain.recommended_formation
      : workspace.squad.formation
  const currentCopy = workspace.squad.source === 'connected'
    ? { kicker: 'Current FPL team', title: `Your GW${workspace.phase.event} starting XI` }
    : { kicker: 'Current proposal', title: `GW${workspace.phase.event} starting XI` }
  const phaseCopy = squadMode === 'model' && modelSquad
    ? { kicker: 'Published model squad', title: `Best 15-player GW${modelSquad.event} build` }
    : squadMode === 'recommended'
    ? { kicker: 'Best XI from your squad', title: `Modelled GW${decisionEvent} lineup` }
    : workspace.phase.phase === 'live_gameweek'
    ? { kicker: 'Next-deadline baseline', title: `Current squad · planning GW${decisionEvent}` }
    : workspace.phase.phase === 'review'
      ? { kicker: 'Gameweek record', title: `GW${workspace.phase.event} submitted XI` }
      : workspace.phase.phase === 'pre_deadline'
        ? { kicker: 'Current team', title: `GW${workspace.phase.event} starting XI` }
        : currentCopy

  return (
    <section className="squad-module" id="squad" aria-labelledby="squad-title">
      <div className="module-toolbar">
        <div>
          <span className="module-kicker">{phaseCopy.kicker}</span>
          <h2 id="squad-title">{phaseCopy.title}</h2>
        </div>
        <div className="toolbar-actions">
          <div className="squad-mode-control" role="group" aria-label="Squad state">
            <button
              type="button"
              className={squadMode === 'current' ? 'is-active' : ''}
              aria-pressed={squadMode === 'current'}
              onClick={() => onSquadModeChange('current')}
            >
              {workspace.squad.source === 'connected' ? 'Your FPL squad' : 'Current squad'}
            </button>
            {modelSquad && workspace.phase.phase === 'preseason' ? (
              <button
                type="button"
                className={squadMode === 'model' ? 'is-active' : ''}
                aria-pressed={squadMode === 'model'}
                onClick={() => onSquadModeChange('model')}
              >
                Model squad
                {modelOnlyIds.size ? <span aria-label={`${modelOnlyIds.size} changes available`} /> : null}
              </button>
            ) : null}
            {(workspace.phase.phase !== 'preseason' || hasRecommendationChanges) ? (
              <button
                type="button"
                className={squadMode === 'recommended' ? 'is-active' : ''}
                aria-pressed={squadMode === 'recommended'}
                onClick={() => onSquadModeChange('recommended')}
              >
                Best XI
                {hasRecommendationChanges ? <span aria-label="Lineup changes available" /> : null}
              </button>
            ) : null}
          </div>
          <span className="formation-label">{displayFormation}</span>
          <div className="segmented-control" role="group" aria-label="Squad view">
            <button
              type="button"
              className={view === 'pitch' ? 'is-active' : ''}
              onClick={() => onViewChange('pitch')}
              aria-label="Pitch view"
            >
              <SoccerBallIcon size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className={view === 'list' ? 'is-active' : ''}
              onClick={() => onViewChange('list')}
              aria-label="List view"
            >
              <ListBulletsIcon size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <div className="pitch-bezel">
        {view === 'pitch' ? (
          <div className="pitch-field">
            <span className="pitch-centre-line" aria-hidden="true" />
            <span className="pitch-centre-circle" aria-hidden="true" />
            <span className="pitch-box pitch-box-top" aria-hidden="true" />
            <span className="pitch-box pitch-box-bottom" aria-hidden="true" />
            <div className="pitch-rows">
              {positionOrder.map((position) => (
                <div className={`pitch-row row-${position.toLowerCase()}`} key={position}>
                  {grouped[position].map((player) => (
                    <PlayerCard
                      key={player.player_id}
                      player={player}
                      selected={selectedPlayerId === player.player_id}
                      onSelect={onSelectPlayer}
                      change={squadMode === 'model' && modelOnlyIds.has(player.player_id)
                        ? 'in'
                        : squadMode === 'recommended' && workspace.decision.captain.promoted_player_ids.includes(player.player_id)
                          ? 'in'
                          : undefined}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="squad-list-view">
            {positionOrder.map((position) => (
              <div className="list-position" key={position}>
                <span>{position}</span>
                <div>
                  {grouped[position].map((player) => (
                    <PlayerCard
                      key={player.player_id}
                      player={player}
                      selected={selectedPlayerId === player.player_id}
                      onSelect={onSelectPlayer}
                      compact
                      change={squadMode === 'model' && modelOnlyIds.has(player.player_id)
                        ? 'in'
                        : squadMode === 'recommended' && workspace.decision.captain.promoted_player_ids.includes(player.player_id)
                          ? 'in'
                          : undefined}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bench-module">
        <div className="bench-heading">
          <span>Bench</span>
          <small>{squadMode === 'recommended' ? 'Outside the best XI' : 'Autosub order · left to right'}</small>
        </div>
        <div className="bench-grid">
          {displayedBench.map((player, index) => (
            <div className="bench-slot" key={player.player_id}>
              <span className="bench-order">{index === 0 ? '1' : index + 1}</span>
              <PlayerCard
                player={player}
                selected={selectedPlayerId === player.player_id}
                onSelect={onSelectPlayer}
                compact
                change={squadMode === 'model' && modelOnlyIds.has(player.player_id)
                  ? 'in'
                  : squadMode === 'recommended' && workspace.decision.captain.benched_player_ids.includes(player.player_id)
                    ? 'out'
                    : undefined}
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
