import { useEffect, useMemo, useState } from 'react'

import {
  ArrowRightIcon,
  ChartLineUpIcon,
  CheckCircleIcon,
  LockIcon,
  ShieldCheckIcon,
  SparkleIcon,
  TimerIcon,
  WarningCircleIcon,
  XIcon,
} from '@phosphor-icons/react'

import {
  ApiError,
  activatePublishedSquad,
  generateSquad,
  getPreseasonOptions,
} from '../api'
import { shortPlayerName } from '../lib'
import { useDialogAccessibility } from '../useDialogAccessibility'
import type {
  GenerateSquadResult,
  PreseasonOptions,
  Workspace,
} from '../types'

interface GenerateSquadDialogProps {
  open: boolean
  workspace: Workspace
  onClose: () => void
  onComplete: () => Promise<void>
}

type RiskProfile = 'balanced' | 'safer' | 'upside'
type Horizon = 3 | 5 | 8

const profiles: Array<{
  id: RiskProfile
  title: string
  detail: string
  icon: typeof ChartLineUpIcon
}> = [
  {
    id: 'balanced',
    title: 'Balanced opening run',
    detail: 'Optimise expected points while keeping the next few transfers in view.',
    icon: ChartLineUpIcon,
  },
  {
    id: 'safer',
    title: 'Safer minutes',
    detail: 'Prefer the robust forecast and reduce exposure to uncertain starters.',
    icon: ShieldCheckIcon,
  },
  {
    id: 'upside',
    title: 'More upside',
    detail: 'Accept a little more forecast variance in exchange for ceiling.',
    icon: SparkleIcon,
  },
]

export function GenerateSquadDialog({
  open,
  workspace,
  onClose,
  onComplete,
}: GenerateSquadDialogProps) {
  const [options, setOptions] = useState<PreseasonOptions | null>(null)
  const [riskProfile, setRiskProfile] = useState<RiskProfile>('balanced')
  const [horizon, setHorizon] = useState<Horizon>(5)
  const [locked, setLocked] = useState<number[]>(workspace.squad.locked_player_ids)
  const [club, setClub] = useState('')
  const [clubCount, setClubCount] = useState<2 | 3>(3)
  const [busy, setBusy] = useState<'custom' | 'published' | null>(null)
  const [result, setResult] = useState<GenerateSquadResult | null>(null)
  const [error, setError] = useState('')
  const dialogRef = useDialogAccessibility<HTMLElement>(open, close, Boolean(busy))

  const players = useMemo(
    () => [...workspace.squad.starters, ...workspace.squad.bench],
    [workspace],
  )

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void getPreseasonOptions(controller.signal)
      .then(setOptions)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(caught instanceof ApiError ? caught.message : 'Build options are unavailable.')
      })
    return () => controller.abort()
  }, [open])

  function close() {
    setLocked(workspace.squad.locked_player_ids)
    setRiskProfile('balanced')
    setHorizon(5)
    setClub('')
    setClubCount(3)
    setResult(null)
    setError('')
    onClose()
  }

  function toggleLock(playerId: number) {
    setLocked((current) =>
      current.includes(playerId)
        ? current.filter((value) => value !== playerId)
        : [...current, playerId],
    )
  }

  async function buildCustom() {
    setBusy('custom')
    setError('')
    try {
      const next = await generateSquad({
        risk_profile: riskProfile,
        horizon,
        locked_player_ids: locked,
        excluded_player_ids: [],
        club_minimums: club ? [{ team_short_name: club, count: clubCount }] : [],
      })
      setResult(next)
      await onComplete()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The squad could not be generated.')
    } finally {
      setBusy(null)
    }
  }

  async function choosePublished() {
    setBusy('published')
    setError('')
    try {
      const next = await activatePublishedSquad()
      setResult(next)
      await onComplete()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The published squad is unavailable.')
    } finally {
      setBusy(null)
    }
  }

  if (!open) return null

  return (
    <div
      className="dialog-layer"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && !busy && close()}
    >
      <section ref={dialogRef} className="builder-shell" role="dialog" aria-modal="true" aria-labelledby="builder-title">
        <div className="builder-dialog">
          <header className="dialog-header">
            <div>
              <span className="module-kicker">Candidate builder</span>
              <h2 id="builder-title">Build the squad around your rules.</h2>
              <p className="dialog-intro">
                Start from the published recommendation or run a fast variation. Every result is
                legal, scored and becomes the squad that chat can see.
              </p>
            </div>
            <button className="icon-button" type="button" onClick={close} disabled={Boolean(busy)} aria-label="Close squad builder">
              <XIcon size={18} aria-hidden="true" />
            </button>
          </header>

          {result ? (
            <div className="builder-complete">
              <span className="completion-mark"><CheckCircleIcon size={31} weight="fill" aria-hidden="true" /></span>
              <div>
                <span className="module-kicker">Active candidate</span>
                <h3>{result.formation} · {result.expected_points.toFixed(1)} projected GW1</h3>
                <p>
                  £{result.budget_spent.toFixed(1)}m spent · {result.changed_player_ids.length / 2} player
                  {result.changed_player_ids.length === 2 ? '' : 's'} changed · generated in {(result.duration_ms / 1000).toFixed(1)}s
                </p>
                <code>{result.receipt_id}</code>
              </div>
              <button className="primary-button" type="button" onClick={close}>
                Review squad <span className="button-island"><ArrowRightIcon size={14} /></span>
              </button>
            </div>
          ) : (
            <>
              <div className="published-lane">
                <div className="published-mark"><SparkleIcon size={21} weight="duotone" aria-hidden="true" /></div>
                <div>
                  <span>Ready immediately</span>
                  <strong>Use the published robust recommendation</strong>
                  <p>
                    The expensive model tournament has already run. This is the current promoted
                    baseline, not a cached random answer.
                  </p>
                </div>
                <button className="secondary-button" type="button" onClick={() => void choosePublished()} disabled={Boolean(busy)}>
                  {busy === 'published' ? 'Loading…' : 'Use best available'}
                </button>
              </div>

              <div className="builder-grid">
                <div className="builder-main">
                  <fieldset className="strategy-fieldset">
                    <legend>1. Choose the decision posture</legend>
                    <div className="profile-options">
                      {profiles.map(({ id, title, detail, icon: Icon }) => (
                        <label className={riskProfile === id ? 'is-selected' : ''} key={id}>
                          <input type="radio" name="risk" value={id} checked={riskProfile === id} onChange={() => setRiskProfile(id)} />
                          <Icon size={18} aria-hidden="true" />
                          <span><strong>{title}</strong><small>{detail}</small></span>
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <fieldset className="horizon-fieldset">
                    <legend>2. Set the planning horizon</legend>
                    <div className="horizon-options">
                      {([3, 5, 8] as const).map((value) => (
                        <button type="button" className={horizon === value ? 'is-selected' : ''} onClick={() => setHorizon(value)} key={value}>
                          <strong>GW1–{value}</strong>
                          <small>{value === 3 ? 'fastest' : value === 5 ? 'recommended' : 'long view'}</small>
                        </button>
                      ))}
                    </div>
                  </fieldset>

                  <fieldset className="club-fieldset">
                    <legend>3. Add an optional club rule</legend>
                    <div className="club-controls">
                      <label>
                        <span>Club</span>
                        <select value={club} onChange={(event) => setClub(event.target.value)}>
                          <option value="">No club minimum</option>
                          {options?.teams.map((team) => (
                            <option value={team.short_name} key={team.team_id}>{team.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Minimum players</span>
                        <select value={clubCount} onChange={(event) => setClubCount(Number(event.target.value) as 2 | 3)} disabled={!club}>
                          <option value={2}>2 players</option>
                          <option value={3}>3 players</option>
                        </select>
                      </label>
                    </div>
                    <small className="field-help">For example: require three Liverpool players while respecting the normal club cap.</small>
                  </fieldset>
                </div>

                <aside className="lock-panel">
                  <div className="lock-heading">
                    <span><LockIcon size={16} aria-hidden="true" /></span>
                    <div><strong>Keep players</strong><small>{locked.length} locked into the next build</small></div>
                  </div>
                  <div className="lock-list">
                    {players.map((player) => (
                      <label className={locked.includes(player.player_id) ? 'is-locked' : ''} key={player.player_id}>
                        <input type="checkbox" checked={locked.includes(player.player_id)} onChange={() => toggleLock(player.player_id)} />
                        <span>{player.position}</span>
                        <strong>{shortPlayerName(player.name)}</strong>
                        <small>{player.team_short_name}</small>
                      </label>
                    ))}
                  </div>
                </aside>
              </div>

              {busy === 'custom' ? (
                <div className="builder-running" aria-live="polite">
                  <TimerIcon size={19} aria-hidden="true" />
                  <div><strong>Solving a legal squad across GW1–{horizon}</strong><span>Applying prices, positions, club limits, your locks and the forecast objective.</span></div>
                  <span className="running-track"><span /></span>
                </div>
              ) : null}

              {error ? <div className="builder-error"><WarningCircleIcon size={17} weight="fill" /><span>{error}</span></div> : null}

              <footer className="dialog-footer">
                <span>{options?.custom_build_estimate_seconds ?? 'The optimiser runs locally.'} · nothing is written to FPL.</span>
                <div>
                  <button className="primary-button" type="button" onClick={() => void buildCustom()} disabled={Boolean(busy)}>
                    {busy === 'custom' ? 'Building candidate…' : 'Generate variation'}
                    <span className="button-island"><ArrowRightIcon size={14} /></span>
                  </button>
                </div>
              </footer>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
