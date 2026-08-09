import {
  CaretDownIcon,
  CheckCircleIcon,
  MagnifyingGlassIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'

import { formatPercent } from '../lib'
import type { Player, Workspace } from '../types'

const positions: Player['position'][] = ['GK', 'DEF', 'MID', 'FWD']

interface SquadAssessmentProps {
  workspace: Workspace
  onSelectPlayer: (player: Player) => void
}

function uniquePlayers(players: Player[]) {
  return players.filter(
    (player, index) => players.findIndex((row) => row.player_id === player.player_id) === index,
  )
}

export function SquadAssessment({ workspace, onSelectPlayer }: SquadAssessmentProps) {
  const allPlayers = [...workspace.squad.starters, ...workspace.squad.bench]
  const rankedPlayers = [...allPlayers].sort(
    (left, right) => right.robust_points - left.robust_points,
  )
  const weakestStarters = [...workspace.squad.starters].sort(
    (left, right) => left.robust_points - right.robust_points,
  )
  const availabilityRisks = [...allPlayers]
    .filter((player) => player.play_probability < 0.85)
    .sort((left, right) => left.play_probability - right.play_probability)
  const currentCaptain = allPlayers.find(
    (player) => player.player_id === workspace.decision.captain.current_captain_player_id,
  )
  const promotedPlayers = workspace.decision.captain.promoted_player_ids
    .map((playerId) => allPlayers.find((player) => player.player_id === playerId))
    .filter((player): player is Player => Boolean(player))
  const reviewQueue = uniquePlayers([
    ...promotedPlayers,
    ...(!workspace.decision.captain.recommendation_aligned && currentCaptain
      ? [currentCaptain]
      : []),
    ...availabilityRisks,
    ...weakestStarters,
  ]).slice(0, 4)
  const likelyAvailable = allPlayers.filter((player) => player.play_probability >= 0.85).length
  const favourableStarters = workspace.squad.starters.filter(
    (player) => player.fixture && player.fixture.difficulty <= 2,
  ).length
  const benchRobustPoints = workspace.squad.bench.reduce(
    (total, player) => total + player.robust_points,
    0,
  )
  const benchSpend = workspace.squad.bench.reduce((total, player) => total + player.price, 0)

  function reviewReason(player: Player) {
    const promotionIndex = workspace.decision.captain.promoted_player_ids.indexOf(player.player_id)
    if (promotionIndex >= 0) {
      return 'Recommended for the best legal XI from the current bench'
    }
    if (
      player.player_id === workspace.decision.captain.current_captain_player_id
      && !workspace.decision.captain.recommendation_aligned
    ) {
      return `Current captain; ${workspace.decision.captain.captain_name} leads the recommended XI`
    }
    if (player.play_probability < 0.85) {
      return `${formatPercent(player.play_probability)} modelled chance of playing`
    }
    return `Starter floor of ${player.robust_points.toFixed(2)} robust points`
  }

  return (
    <section className="squad-assessment" aria-labelledby="squad-assessment-title">
      <div className="insight-title-row">
        <span id="squad-assessment-title">Whole squad read</span>
        <small>15-player audit</small>
      </div>

      <div className="assessment-metrics">
        <div>
          <strong>{likelyAvailable}/15</strong>
          <span>clear 85% availability</span>
        </div>
        <div>
          <strong>{favourableStarters}/11</strong>
          <span>favourable starters</span>
        </div>
        <div>
          <strong>{benchRobustPoints.toFixed(1)}</strong>
          <span>bench robust xP</span>
        </div>
        <div>
          <strong>£{benchSpend.toFixed(1)}m</strong>
          <span>allocated to bench</span>
        </div>
      </div>

      <div className="assessment-section">
        <div className="assessment-label">
          <CheckCircleIcon size={14} weight="fill" aria-hidden="true" />
          <span>Strongest model signals</span>
        </div>
        <div className="signal-list">
          {rankedPlayers.slice(0, 3).map((player, index) => (
            <button type="button" key={player.player_id} onClick={() => onSelectPlayer(player)}>
              <span>{index + 1}</span>
              <strong>{player.name}</strong>
              <small>{player.robust_points.toFixed(2)}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="assessment-section">
        <div className="assessment-label is-review">
          <WarningCircleIcon size={14} weight="fill" aria-hidden="true" />
          <span>Priority review</span>
        </div>
        <div className="review-list">
          {reviewQueue.map((player) => (
            <button type="button" key={player.player_id} onClick={() => onSelectPlayer(player)}>
              <span>
                <strong>{player.name}</strong>
                <small>{reviewReason(player)}</small>
              </span>
              <MagnifyingGlassIcon size={13} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>

      <div className="position-units" aria-label="Position unit assessment">
        {positions.map((position) => {
          const squadPlayers = allPlayers.filter((player) => player.position === position)
          const starters = squadPlayers.filter((player) => player.role === 'starter')
          const leader = [...squadPlayers].sort(
            (left, right) => right.robust_points - left.robust_points,
          )[0]
          const starterTotal = starters.reduce((total, player) => total + player.robust_points, 0)
          return (
            <div className="position-unit" key={position}>
              <strong>{position}</strong>
              <span>{starters.length} starting · {squadPlayers.length} owned</span>
              <small>{leader?.name ?? 'Unavailable'}</small>
              <em>{starterTotal.toFixed(1)}</em>
            </div>
          )
        })}
      </div>

      <details className="all-player-audit">
        <summary>
          <span>Inspect all 15 model scores</span>
          <CaretDownIcon size={14} aria-hidden="true" />
        </summary>
        <div>
          {rankedPlayers.map((player, index) => (
            <button type="button" key={player.player_id} onClick={() => onSelectPlayer(player)}>
              <span>{index + 1}</span>
              <strong>{player.name}</strong>
              <small>{player.role} · {formatPercent(player.play_probability)}</small>
              <em>{player.robust_points.toFixed(2)}</em>
            </button>
          ))}
        </div>
      </details>
    </section>
  )
}
