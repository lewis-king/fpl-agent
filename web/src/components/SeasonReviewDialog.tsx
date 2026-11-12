import { useEffect, useState } from 'react'
import { ArrowClockwiseIcon, XIcon } from '@phosphor-icons/react'
import { useDialogAccessibility } from '../useDialogAccessibility'
import { formatObservedAt } from '../lib'
import '../seasonReview.css'

interface ReviewPlayer {
  element: number; name: string; slot: number; multiplier: number; captain: boolean
  actual_points: number; actual_minutes: number; contribution: number
  expected_points: number | null; expected_minutes: number | null
}
interface ReviewEvent {
  event: number; net_points: number; hit_cost: number; average_points: number
  overall_rank: number; chip: string | null; bench_points: number
  recommendation_net_points: number | null; ordinary_projection: number | null
  recommendation_chip: string | null; decision_created_at: string | null
  hindsight_configuration_gap: number | null; hindsight_captain_gap: number | null
  players: ReviewPlayer[]; review_status: string
}
interface BenchmarkWeek { event: number; net_points: number; top_manager_median: number; gap: number; season_gap: number }
interface Benchmark {
  managers: number; sample_event: number; weeks: BenchmarkWeek[]; window: number
  recent_gap: number; review_gap: number; season_gap: number; status: 'too_early' | 'on_pace' | 'review'
  thresholds: Record<string, { rank: number; total: number }>
  widely_owned_missing: { element: number; name: string; field_ownership: number }[]
}
const signed = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(Math.round(value))}`
const benchmarkVerdict = (benchmark: Benchmark) => benchmark.status === 'review'
  ? `Trailing by ${Math.abs(Math.round(benchmark.recent_gap))} over ${benchmark.window} weeks, more than luck usually explains. Time to review the decisions.`
  : benchmark.status === 'on_pace'
    ? `Within normal luck of top-manager pace over the last ${benchmark.window} weeks.`
    : `Needs ${benchmark.window} finished weeks before it can say anything.`

function TopManagerScoreboard({ benchmark, total }: { benchmark: Benchmark; total?: number }) {
  const scale = Math.max(20, ...benchmark.weeks.map(week => Math.abs(week.gap)))
  const line = benchmark.thresholds.top_10k
  return (
    <section className="review-benchmark" aria-labelledby="benchmark-title">
      <header>
        <div><span className="module-kicker">Against top managers</span><h3 id="benchmark-title">{benchmarkVerdict(benchmark)}</h3></div>
        <dl>
          <div><dt>Last {Math.min(benchmark.window, benchmark.weeks.length)} weeks</dt><dd>{signed(benchmark.recent_gap)}</dd></div>
          <div><dt>Season</dt><dd>{signed(benchmark.season_gap)}</dd></div>
          {line && total !== undefined && <div><dt>To the top 10k</dt><dd>{signed(total - line.total)}</dd></div>}
        </dl>
      </header>
      <ol className="benchmark-weeks" aria-label="Weekly points against the top-manager median">
        {benchmark.weeks.map(week => (
          <li key={week.event} title={`GW${week.event}: you ${week.net_points}, top managers ${week.top_manager_median}`}>
            <span className="benchmark-bar"><i className={week.gap < 0 ? 'behind' : 'ahead'} style={{ height: `${Math.max(4, 50 * Math.abs(week.gap) / scale)}%` }} /></span>
            <b>{signed(week.gap)}</b><small>GW{week.event}</small>
          </li>
        ))}
      </ol>
      <p className="benchmark-note">Your weekly points minus the median of {benchmark.managers} managers ranked around 1,000 and 10,000, sampled after GW{benchmark.sample_event}. This is a health check. It flags a review at {signed(benchmark.review_gap)} over {benchmark.window} weeks and never changes a pick.{benchmark.widely_owned_missing.length > 0 && ` Most-owned players you don't have: ${benchmark.widely_owned_missing.map(player => `${player.name} ${Math.round(100 * player.field_ownership)}%`).join(', ')}.`}</p>
    </section>
  )
}

interface Review {
  status: string; observed_at: string | null; total_points?: number; overall_rank?: number
  events: ReviewEvent[]
  benchmark?: Benchmark | null
  forecast_health?: { player_outcomes: number; interval_80_coverage: number | null; captain_outcomes: number; captain_interval_80_coverage: number | null }
}

async function requestReview(refresh: boolean, signal?: AbortSignal): Promise<Review> {
  const response = await fetch(`/api/v1/review${refresh ? '/refresh' : ''}`, {
    method: refresh ? 'POST' : 'GET', signal,
  })
  if (!response.ok) throw new Error('Results could not be verified. Your saved decisions have not changed.')
  return response.json()
}

export function SeasonReviewDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialogRef = useDialogAccessibility<HTMLElement>(open, onClose)
  const [review, setReview] = useState<Review | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void requestReview(false, controller.signal).then(result => {
      if (!controller.signal.aborted) { setReview(result); setError('') }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load results.')
    })
    return () => controller.abort()
  }, [open])
  if (!open) return null
  const event = review?.events.find(row => row.event === selectedEvent) ?? review?.events.at(-1)
  const refresh = async () => {
    setBusy(true); setError('')
    try { setReview(await requestReview(true)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not refresh results.') }
    finally { setBusy(false) }
  }
  return (
    <div className="dialog-layer" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <section ref={dialogRef} className="evidence-shell season-review" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <header className="dialog-header">
          <div><span className="module-kicker">The season so far</span><h2 id="review-title">What actually happened.</h2></div>
          <button className="icon-button" aria-label="Close season review" onClick={onClose}><XIcon size={20} /></button>
        </header>
        <div className="review-toolbar">
          <p>Official results against the advice frozen before each deadline. No hindsight rewriting.</p>
          <button className="secondary-button" onClick={() => void refresh()} disabled={busy || review?.status === 'manager_required'}>
            <ArrowClockwiseIcon size={16} /> {busy ? 'Verifying results…' : 'Refresh results'}
          </button>
        </div>
        <p className="review-observed">{review?.observed_at ? `Checked ${formatObservedAt(review.observed_at)} · read-only FPL data` : 'Refreshing results never starts a squad optimisation or changes your FPL team.'}</p>
        {error && <p className="review-error" role="alert">{error}</p>}
        {!review && !error && <div className="review-skeleton" aria-label="Loading season review" />}
        {review && !event && <div className="review-empty"><h3>{review.status === 'manager_required' ? 'Add your FPL entry ID.' : 'Your results belong here.'}</h3><p>{review.status === 'manager_required' ? 'Save it in Manager settings, then reopen this review.' : 'Refresh results to compare completed gameweeks with our saved recommendations. In-progress events are excluded.'}</p></div>}
        {event && <>
          <div className="review-headline">
            <div><span className="module-kicker">Your season</span><strong>{review?.total_points} <small>points</small></strong><p>Overall rank {review?.overall_rank?.toLocaleString('en-GB')}</p></div>
            <label>Review gameweek<select value={event.event} onChange={e => setSelectedEvent(Number(e.target.value))}>{review?.events.map(row => <option key={row.event} value={row.event}>GW{row.event} · {row.net_points} points</option>)}</select></label>
          </div>
          {review?.benchmark && review.benchmark.weeks.length > 0 && <TopManagerScoreboard benchmark={review.benchmark} total={review.total_points} />}
          <div className="review-score-strip">
            <div><span>Your GW{event.event}</span><strong>{event.net_points}</strong><small>net points · {event.hit_cost} hit</small></div>
            <div><span>FPL average</span><strong>{event.average_points}</strong><small>reported event average</small></div>
            <div><span>Saved advice scored</span><strong>{event.recommendation_net_points ?? '—'}</strong><small>{event.recommendation_net_points === null ? 'frozen evidence unavailable' : 'same outcomes, recommended team'}</small></div>
            <div><span>Ordinary forecast</span><strong>{event.ordinary_projection?.toFixed(1) ?? '—'}</strong><small>risk-adjusted · excludes chips</small></div>
          </div>
          <div className="review-context"><strong>{event.chip ? `Played: ${event.chip.replaceAll('_', ' ')}` : 'No chip played'}</strong><span>{event.bench_points} points on the bench · not all were legally recoverable</span></div>
          {review?.forecast_health && review.forecast_health.player_outcomes > 0 && <div className="review-health"><strong>Forecast reliability · all reviewed weeks</strong><p>Our nominal 80% player score ranges contained {(100 * (review.forecast_health.interval_80_coverage ?? 0)).toFixed(0)}% of {review.forecast_health.player_outcomes} outcomes. For the {review.forecast_health.captain_outcomes} recommended captains: {review.forecast_health.captain_interval_80_coverage === null ? 'not measured' : `${(100 * review.forecast_health.captain_interval_80_coverage).toFixed(0)}%`}.</p><small>Outcomes share players and matches, so this is not an independent sample. A large shortfall warns of miscalibration; it does not establish the cause or justify chasing last week’s scorers.</small></div>}
          <div className="review-table-scroll" tabIndex={0} aria-label="Player forecast and outcome comparison">
            <table className="review-table"><caption>Your locked team · points are per player before captain doubling</caption><thead><tr><th scope="col">Player</th><th scope="col">Forecast</th><th scope="col">Actual</th><th scope="col">Minutes: expected / actual</th><th scope="col">Counted</th></tr></thead><tbody>
              {event.players.map(player => <tr key={player.element} className={player.multiplier === 0 ? 'review-benched' : ''}><th scope="row">{player.name} {player.captain && <span className="review-captain">C</span>}<small>{player.slot > 11 ? 'Submitted bench' : 'Submitted XI'}{player.multiplier === 0 ? ' · not counted' : ''}</small></th><td>{player.expected_points?.toFixed(1) ?? '—'}</td><td>{player.actual_points}</td><td>{player.expected_minutes?.toFixed(0) ?? '—'} / {player.actual_minutes}</td><td>{player.contribution}</td></tr>)}
            </tbody></table>
          </div>
          <details className="review-caveats"><summary>What this review can—and cannot—tell us</summary><p>These are real outcomes, not proof that one noisy week makes a strategy good or bad. A short substitute appearance counts as playing, so a high playing probability alone does not make a safe captain.</p><p>Perfect hindsight could improve the saved squad’s XI and captain by {event.hindsight_configuration_gap ?? 'an unmeasured number of'} points. The captain gap within its XI was {event.hindsight_captain_gap ?? 'unmeasured'}. Those figures overlap: never add them together or treat them as points we should certainly have won.</p><p>The recommendation and your actual picks are scored separately. Forecast labels are frozen; missing forecasts remain missing. Advice frozen {event.decision_created_at ? formatObservedAt(event.decision_created_at) : 'at an unavailable time'}.</p></details>
        </>}
      </section>
    </div>
  )
}
