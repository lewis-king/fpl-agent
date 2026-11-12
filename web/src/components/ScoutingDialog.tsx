import { useEffect, useMemo, useState } from 'react'
import { ArrowClockwiseIcon, MagnifyingGlassIcon, XIcon } from '@phosphor-icons/react'
import { useDialogAccessibility } from '../useDialogAccessibility'
import { formatObservedAt } from '../lib'
import '../scouting.css'

interface Summary {
  events: number; fixtures: number; minutes: number; minutes_per_fixture: number | null
  starts: number | null; start_rate: number | null; points: number; goals: number; assists: number
  xg: number | null; xa: number | null; xgi_per90: number | null; xgi_minutes: number
  goals_minus_xg: number | null; defcon_hits: number | null; defcon_played_fixtures: number
  defcon_hit_rate: number | null; defcon_points: number | null
}
interface Forecast {
  event: number; fixtures: { opponent: string; venue: string; kickoff: string | null }[]
  xp: number | null; p_play: number | null; p_short: number | null; p60: number | null
  forecast_at: string | null; team_goals: number | null; clean_sheet_probability: number | null
}
interface ScoutPlayer {
  id: number; name: string; team: string; position: string; price: number; news: string
  penalty_order: number | null; corner_order: number | null
  season: Summary; recent: Summary; earlier: Summary; horizon: Forecast[]; warnings: string[]
  score_risk?: { blank_probability: number; haul_probability: number; p10: number; p90: number; source: string } | null
}
interface Board { status: string; observed_at: string | null; decision_event: number; completed_events: number[]; players: ScoutPlayer[]; notes: string[] }

const number = (v: number | null | undefined, digits = 1) => v == null ? '—' : v.toFixed(digits)
const percent = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v * 100)}%`
async function fetchBoard(refresh: boolean, signal?: AbortSignal): Promise<Board> {
  const response = await fetch(`/api/v1/scouting${refresh ? '/refresh' : ''}`, { method: refresh ? 'POST' : 'GET', signal })
  if (!response.ok) throw new Error('Scouting could not be verified. Your saved board and team are unchanged. Try refreshing completed results first.')
  return response.json()
}

function PlayerEvidence({ player, now }: { player: ScoutPlayer; now: number }) {
  const next = player.horizon[0]
  if (!next) return <article className="scout-player"><h3>{player.name}</h3><p>No future forecast horizon is available.</p></article>
  const oldForecast = !next.forecast_at || now - Date.parse(next.forecast_at) > 6 * 3600_000
  const windows: [string, Summary][] = [['Last 3 GWs', player.recent], ['Earlier GWs', player.earlier], ['Full season', player.season]]
  return <article className="scout-player">
    <header><span className="module-kicker">{player.team} · {player.position}</span><h3>{player.name}</h3><span className="scout-price">£{player.price.toFixed(1)}m</span></header>
    <div className="scout-evidence-table"><table><caption>Underlying production · non-overlapping recent / earlier windows</caption><thead><tr><th>Metric</th>{windows.map(([label]) => <th key={label}>{label}</th>)}</tr></thead><tbody>
      <tr><th>Minutes</th>{windows.map(([label, w]) => <td key={label}>{w.minutes}</td>)}</tr>
      <tr><th>Minutes / fixture</th>{windows.map(([label, w]) => <td key={label}>{number(w.minutes_per_fixture, 0)}</td>)}</tr>
      <tr><th>Starts / fixtures</th>{windows.map(([label, w]) => <td key={label}>{w.starts ?? '—'} / {w.fixtures}</td>)}</tr>
      <tr><th>xG + xA / 90</th>{windows.map(([label, w]) => <td key={label}>{number(w.xgi_per90, 2)}</td>)}</tr>
      <tr><th>Goals / xG</th>{windows.map(([label, w]) => <td key={label}>{w.goals} / {number(w.xg, 2)}</td>)}</tr>
      <tr><th>Assists / xA</th>{windows.map(([label, w]) => <td key={label}>{w.assists} / {number(w.xa, 2)}</td>)}</tr>
      <tr><th>FPL points</th>{windows.map(([label, w]) => <td key={label}>{w.points}</td>)}</tr>
      <tr><th>DEFCON awards*</th>{windows.map(([label, w]) => <td key={label}>{w.defcon_hits ?? '—'} / {w.defcon_played_fixtures}</td>)}</tr>
    </tbody></table></div>
    <p className="scout-footnote">*Per played fixture with complete scoring explanations. Uses actual awards, including double gameweeks. xG/xA are FPL’s, include penalties, and may differ from other providers.</p>
    <div className="scout-set-pieces"><span>Penalty order <strong>{player.penalty_order ?? '—'}</strong></span><span>Corner order <strong>{player.corner_order ?? '—'}</strong></span><small>Official listed order is not a guarantee of taking the next one.</small></div>
    <h4>GW{next.event}: model role estimate</h4>
    <div className="scout-role"><div><span>Any minutes</span><strong>{percent(next.p_play)}</strong></div><div><span>1–59 minutes</span><strong>{percent(next.p_short)}</strong></div><div><span>60+ minutes</span><strong>{percent(next.p60)}</strong></div></div>
    <p className={oldForecast ? 'scout-warning' : 'scout-footnote'}>{next.forecast_at ? `Forecast built ${formatObservedAt(next.forecast_at)}.` : 'No saved forecast.'} {oldForecast && 'Out of date: refresh decisions before acting. These are not fresh recommendations.'}</p>
    {player.score_risk && <div className="scout-score-risk"><h4>What the average can hide</h4><p>Two points or fewer: <strong>{percent(player.score_risk.blank_probability)}</strong> · 10+ points: <strong>{percent(player.score_risk.haul_probability)}</strong></p><p>Nominal 80% range: <strong>{player.score_risk.p10}–{player.score_risk.p90} points</strong></p><small>Undoubled player score, including DNP. Historically tested marginal estimate—not the joint optimiser simulation or a guarantee. Uses the dated forecast above.</small></div>}
    <h4>The next six gameweeks</h4>
    <div className="scout-fixtures">{player.horizon.map(row => <div key={row.event}><span>GW{row.event}</span><strong>{row.fixtures.length ? row.fixtures.map(f => `${f.opponent} (${f.venue})`).join(' · ') : 'Blank / unassigned'}</strong><span>{number(row.xp)} <small>xP</small></span></div>)}</div>
    <p className="scout-footnote">{player.horizon.filter(r => r.xp !== null).length} / {player.horizon.length} forecast events covered. Missing xP is not zero. Fixture changes can invalidate an older forecast.</p>
    {player.news && <p className="scout-news"><strong>Official news</strong>{player.news}</p>}
    {player.warnings.filter(w => !w.startsWith('Forecast is')).map(w => <p className="scout-warning" key={w}>{w}</p>)}
  </article>
}

export function ScoutingDialog({ open, onClose, initialPlayerId }: { open: boolean; onClose: () => void; initialPlayerId?: number | null }) {
  const ref = useDialogAccessibility<HTMLElement>(open, onClose)
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [position, setPosition] = useState('ALL')
  const [minimum, setMinimum] = useState(300)
  const [sortBy, setSortBy] = useState('xgi')
  const [leftId, setLeftId] = useState<number | null>(null)
  const [rightId, setRightId] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!open) return
    const abort = new AbortController()
    void fetchBoard(false, abort.signal).then(result => { if (!abort.signal.aborted) { setBoard(result); setError(''); setNow(Date.now()) } }).catch((cause: unknown) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load scouting.') })
    const tick = window.setInterval(() => setNow(Date.now()), 60000)
    return () => { abort.abort(); window.clearInterval(tick) }
  }, [open])
  const players = useMemo(() => [...(board?.players ?? [])].sort((a, b) => (b.season.xgi_per90 ?? -1) - (a.season.xgi_per90 ?? -1)), [board])
  const metric = (p: ScoutPlayer) => sortBy === 'minutes' ? p.season.minutes_per_fixture : sortBy === 'defcon' ? p.season.defcon_hit_rate : p.season.xgi_per90
  const eligible = players.filter(p => p.season.minutes >= minimum && (position === 'ALL' || p.position === position) && `${p.name} ${p.team}`.toLowerCase().includes(search.toLowerCase())).sort((a, b) => (metric(b) ?? -1) - (metric(a) ?? -1))
  const left = players.find(p => p.id === (leftId ?? initialPlayerId)) ?? eligible[0]
  const right = players.find(p => p.id === rightId) ?? eligible.find(p => p.id !== left?.id && p.position === left?.position) ?? eligible.find(p => p.id !== left?.id)
  if (!open) return null
  const update = async () => {
    setBusy(true); setError('')
    try { setBoard(await fetchBoard(true)) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update scouting.') } finally { setBusy(false) }
  }
  return <div className="dialog-layer" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <section ref={ref} className="evidence-shell scout-dialog" role="dialog" aria-modal="true" aria-labelledby="scouting-title">
      <header className="dialog-header"><div><span className="module-kicker">The scouting room</span><h2 id="scouting-title">Compare the evidence.</h2></div><button className="icon-button" aria-label="Close scouting" onClick={onClose}><XIcon size={20} /></button></header>
      <div className="scout-intro"><p>Look beyond last week’s points. Compare chance creation, actual minutes, defensive returns and the fixtures ahead.</p><button className="secondary-button" onClick={() => void update()} disabled={busy}><ArrowClockwiseIcon size={16} />{busy ? 'Updating evidence…' : 'Update scouting'}</button></div>
      <p className="scout-footnote">{board?.observed_at ? `Official catalogue checked ${formatObservedAt(board.observed_at)} · completed GW${board.completed_events.at(-1) ?? '—'}` : 'Read-only official evidence. This does not run the optimiser or change your team.'}</p>
      {error && <p className="scout-warning" role="alert">{error}</p>}
      {!board && !error && <div className="scout-loading" aria-label="Loading scouting" />}
      {board && !players.length && <div className="scout-empty"><h3>Start with verified evidence.</h3><p>Update scouting to collect the catalogue and fixtures, then join your archived completed-gameweek results.</p></div>}
      {players.length > 0 && <>
        <div className="scout-filters"><label>Find a player<div className="scout-search"><MagnifyingGlassIcon size={16} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Player or club" /></div></label><label>Position<select value={position} onChange={e => setPosition(e.target.value)}>{['ALL', 'GK', 'DEF', 'MID', 'FWD'].map(p => <option key={p}>{p}</option>)}</select></label><label>Minimum season minutes<select value={minimum} onChange={e => setMinimum(Number(e.target.value))}><option value={0}>Any minutes</option><option value={180}>180 minutes</option><option value={300}>300 minutes</option><option value={450}>450 minutes</option></select></label><label>Order shortlist by<select value={sortBy} onChange={e => setSortBy(e.target.value)}><option value="xgi">Chance creation / 90</option><option value="minutes">Minutes / fixture</option><option value="defcon">DEFCON hit rate</option></select></label></div>
        <div className="scout-selector"><p>{eligible.length} players · season evidence, not a transfer ranking</p><div className="scout-shortlist" aria-label="Player shortlist">{eligible.slice(0, 20).map(p => <div key={p.id}><span><strong>{p.name}</strong><small>{p.team} · {p.position} · £{p.price.toFixed(1)}m · {sortBy === 'defcon' ? `${percent(p.season.defcon_hit_rate)} DEFCON` : sortBy === 'minutes' ? `${number(p.season.minutes_per_fixture, 0)} min/fixture` : `${number(p.season.xgi_per90, 2)} xGI/90`}</small></span><button aria-label={`Compare ${p.name} on left`} onClick={() => setLeftId(p.id)}>A</button><button aria-label={`Compare ${p.name} on right`} onClick={() => setRightId(p.id)}>B</button></div>)}</div>{eligible.length === 0 && <p>No players match. Reduce the minutes filter or change your search.</p>}</div>
        {left && right && <><div className="scout-comparison-label"><span>A / B comparison</span><p>{left.position !== right.position ? 'Different positions: not a legal one-for-one swap.' : `Current-price difference: £${Math.abs(right.price - left.price).toFixed(1)}m. Selling prices, bank, club limits and hits still need the optimiser.`}</p></div><div className="scout-comparison"><PlayerEvidence player={left} now={now} /><PlayerEvidence player={right} now={now} /></div></>}
        <details className="scout-method"><summary>Sources, limits and how to use this</summary>{board?.notes.map(note => <p key={note}>{note}</p>)}<p>Use these comparisons to challenge a model assumption, not to turn recent form into a guaranteed forecast. No paid Scout or Understat numbers are represented as connected inputs here.</p></details>
      </>}
    </section>
  </div>
}
