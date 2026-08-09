import {
  ChartDonutIcon,
  ChatCircleDotsIcon,
  DatabaseIcon,
  GearSixIcon,
  SoccerBallIcon,
} from '@phosphor-icons/react'

interface AppRailProps {
  active: string
  onChange: (section: string) => void
  onOpenSettings: () => void
}

const items = [
  { id: 'squad', label: 'Squad', icon: SoccerBallIcon },
  { id: 'decisions', label: 'Decisions', icon: ChartDonutIcon },
  { id: 'chat', label: 'Chat', icon: ChatCircleDotsIcon },
  { id: 'evidence', label: 'Evidence', icon: DatabaseIcon },
]

export function AppRail({ active, onChange, onOpenSettings }: AppRailProps) {
  return (
    <aside className="app-rail" aria-label="Application navigation">
      <button className="brand-seal" type="button" aria-label="FPLAgent home" onClick={() => onChange('squad')}>
        <span>FA</span>
      </button>
      <nav className="rail-nav">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`rail-button ${active === id ? 'is-active' : ''}`}
            type="button"
            aria-label={label}
            aria-current={active === id ? 'page' : undefined}
            onClick={() => onChange(id)}
          >
            <Icon size={20} weight={active === id ? 'fill' : 'regular'} aria-hidden="true" />
            <span className="rail-tooltip">{label}</span>
          </button>
        ))}
      </nav>
      <button className="rail-button rail-settings" type="button" aria-label="Manager settings" onClick={onOpenSettings}>
        <GearSixIcon size={20} aria-hidden="true" />
        <span className="rail-tooltip">Settings</span>
      </button>
    </aside>
  )
}
