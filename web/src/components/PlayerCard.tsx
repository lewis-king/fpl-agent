import type { CSSProperties } from 'react'

import { CheckCircleIcon, WarningCircleIcon } from '@phosphor-icons/react'

import { shortPlayerName, teamPalette } from '../lib'
import type { Player } from '../types'

interface PlayerCardProps {
  player: Player
  selected: boolean
  onSelect: (player: Player) => void
  compact?: boolean
  change?: 'in' | 'out'
}

type PaletteStyle = CSSProperties & {
  '--kit-primary': string
  '--kit-secondary': string
  '--kit-detail': string
}

export function PlayerCard({ player, selected, onSelect, compact = false, change }: PlayerCardProps) {
  const [primary, secondary, detail] = teamPalette(player.team_short_name)
  const style: PaletteStyle = {
    '--kit-primary': primary,
    '--kit-secondary': secondary,
    '--kit-detail': detail,
  }
  const available = player.play_probability >= 0.85
  const fixtureLabel = player.fixtures.length
    ? player.fixtures.map((fixture) => fixture.label).join(' · ')
    : 'No fixture'

  return (
    <button
      className={`player-card ${selected ? 'is-selected' : ''} ${compact ? 'is-compact' : ''}`}
      type="button"
      onClick={() => onSelect(player)}
      aria-label={`${player.name}, ${player.team}, ${fixtureLabel}`}
      style={style}
    >
      <span className="player-kit" aria-hidden="true">
        <span>{player.team_short_name}</span>
      </span>
      <span className="player-label">
        <span className="player-name-row">
          <strong>{shortPlayerName(player.name)}</strong>
          {player.captain ? <span className="role-badge captain-badge">C</span> : null}
          {player.vice_captain ? <span className="role-badge">V</span> : null}
        </span>
        <span className={`player-fixture ${player.fixtures.length > 1 ? 'is-double' : ''}`}>
          <span className="fixture-copy">
            {player.fixtures.length
              ? player.fixtures.map((fixture) => <span key={`${fixture.kickoff_time}-${fixture.label}`}>{fixture.label}</span>)
              : <span>No fixture</span>}
          </span>
          <span className={`availability-mark ${available ? 'is-ready' : 'is-risk'}`}>
            {available ? (
              <CheckCircleIcon size={10} weight="fill" aria-hidden="true" />
            ) : (
              <WarningCircleIcon size={10} weight="fill" aria-hidden="true" />
            )}
          </span>
        </span>
      </span>
      <span className="player-xp">{player.robust_points.toFixed(1)}</span>
      {change ? <span className={`lineup-move is-${change}`}>{change === 'in' ? 'IN' : 'OUT'}</span> : null}
    </button>
  )
}
