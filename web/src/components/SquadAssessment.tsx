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
    .filter((player) => ['lineup_watch', 'verify_role', 'official_attention', 'uncovered'].includes(
      player.participation.evidence_status,
    ))
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
  const officiallyClear = workspace.participation.official_clear_players
  const favourableStarters = workspace.squad.starters.filter((player) =>
    player.fixtures.some((fixture) => fixture.difficulty <= 2),
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
    if (player.participation.evidence_status !== 'clear') {
      return player.participation.headline
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
          <strong>{officiallyClear}/15</strong>
          <span>officially clear</span>
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

      <details className={`participation-disclosure is-${workspace.participation.status}`}>
        <summary>
          <span>
            {workspace.participation.official_attention ? (
              <WarningCircleIcon size={14} weight="fill" aria-hidden="true" />
            ) : (
              <CheckCircleIcon size={14} weight="fill" aria-hidden="true" />
            )}
            <span>
              <strong>{workspace.participation.headline}</strong>
              <small>{workspace.participation.detail}</small>
            </span>
          </span>
          <em>
            {workspace.participation.role_verification
              + workspace.participation.official_attention
              + workspace.participation.uncovered_club_feed
              + workspace.participation.predicted_bench_flags
              + workspace.participation.predicted_disagreements}{' '}
            checks
          </em>
          <CaretDownIcon size={14} aria-hidden="true" />
        </summary>
        <div className="participation-body">
          {workspace.participation.teams_total !== null ? (
            <p className="participation-coverage">
              Confirmed lineup coverage for{' '}
              <strong>{workspace.participation.teams_with_confirmed_lineups}/
                {workspace.participation.teams_total} clubs</strong>. Missing coverage remains an
              explicit unknown and is never treated as a negative.
            </p>
          ) : null}
          {workspace.participation.predicted_lineup_captured_sources ? (
            <p className="participation-coverage is-predicted">
              Predicted XI evidence includes{' '}
              <strong>{workspace.participation.predicted_start_support}/15 selected players</strong>
              {' '}from {workspace.participation.predicted_lineup_eligible_sources} of{' '}
              {workspace.participation.predicted_lineup_captured_sources} captured providers.
              {workspace.participation.predicted_bench_flags
                ? ` ${workspace.participation.predicted_bench_flags} two-source bench flags need review.`
                : ' No selected player has a two-source bench flag.'}
              {' '}This feed remains zero-weight until its prospective replay passes.
            </p>
          ) : null}
          <p className="participation-coverage">
            Friendly lineups have zero production weight. Post-tournament returns and experimental
            teams do not directly change projected minutes, expected points or the selected squad;
            they only identify questions to resolve with official or attributable deadline news.
          </p>
          {availabilityRisks.map((player) => (
            <button
              className={`participation-player is-${player.participation.evidence_status}`}
              type="button"
              key={player.player_id}
              onClick={() => onSelectPlayer(player)}
            >
              <span>
                <strong>{player.name}</strong>
                <small>{player.participation.detail}</small>
              </span>
              <em>{formatPercent(player.participation.states.dnp)} DNP</em>
            </button>
          ))}
          {workspace.participation.alternatives.slice(0, 1).map((alternative) => (
            <div className="participation-alternative" key={alternative.scenario}>
              <span>Supported stress alternative · {alternative.scenario.replaceAll('_', ' ')}</span>
              <strong>
                {alternative.incoming.length
                  ? `Bring in ${alternative.incoming.join(', ')}`
                  : `Switch to ${alternative.formation}`}
              </strong>
              {alternative.outgoing.length ? (
                <small>Instead of {alternative.outgoing.join(', ')}</small>
              ) : null}
              <p>
                This is a sensitivity result, not a prediction. It becomes actionable only when
                attributable deadline evidence supports the scenario.
              </p>
              {alternative.why_not_selected ? <p>{alternative.why_not_selected}</p> : null}
            </div>
          ))}
        </div>
      </details>

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

      <details className="assessment-disclosure">
        <summary>
          <span>Explore the full squad breakdown</span>
          <CaretDownIcon size={14} aria-hidden="true" />
        </summary>
        <div className="assessment-disclosure-body">
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
        </div>
      </details>
    </section>
  )
}
