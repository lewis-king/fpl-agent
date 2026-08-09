import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  ArrowClockwiseIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  CloudArrowUpIcon,
  ShieldWarningIcon,
  SparkleIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'

import {
  ApiError,
  getMcpConnection,
  getWorkspace,
  getWorkspaceRefresh,
  startWorkspaceRefresh,
  syncMcpSquad,
} from './api'
import { AppRail } from './components/AppRail'
import { ChatPanel } from './components/ChatPanel'
import { DecisionRail } from './components/DecisionRail'
import { EvidenceDialog } from './components/EvidenceDialog'
import { GenerateSquadDialog } from './components/GenerateSquadDialog'
import { ImportTeamDialog } from './components/ImportTeamDialog'
import { ManagerProfileDialog } from './components/ManagerProfileDialog'
import { PreseasonEntry } from './components/PreseasonEntry'
import { SquadPitch } from './components/SquadPitch'
import { WorkspaceSkeleton } from './components/WorkspaceSkeleton'
import { formatObservedAt } from './lib'
import type { Player, Workspace, WorkspaceRefresh } from './types'

type LoadState = 'loading' | 'ready' | 'error'
type SyncState = 'idle' | 'syncing' | 'success' | 'attention' | 'error'

function pollDelay(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, 1_500)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer)
      resolve()
    }, { once: true })
  })
}

function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [loadError, setLoadError] = useState('')
  const [activeSection, setActiveSection] = useState('squad')
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [pitchView, setPitchView] = useState<'pitch' | 'list'>('pitch')
  const [squadMode, setSquadMode] = useState<'current' | 'recommended'>('current')
  const [importOpen, setImportOpen] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [builderOpen, setBuilderOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [syncState, setSyncState] = useState<SyncState>('idle')
  const [syncMessage, setSyncMessage] = useState('')
  const [refreshRun, setRefreshRun] = useState<WorkspaceRefresh | null>(null)
  const connectionCheckedRef = useRef(false)

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadState('loading')
    setLoadError('')
    try {
      const next = await getWorkspace(signal)
      setWorkspace(next)
      setSelectedPlayerId(next.decision.captain.captain_player_id)
      setLoadState('ready')
    } catch (error) {
      if (signal?.aborted) return
      setLoadError(error instanceof ApiError ? error.message : 'The workspace could not be loaded.')
      setLoadState('error')
    }
  }, [])

  const refreshWorkspace = useCallback(async (signal?: AbortSignal) => {
    const next = await getWorkspace(signal)
    setWorkspace(next)
    setSelectedPlayerId((current) => {
      const stillPresent = [...next.squad.starters, ...next.squad.bench].some(
        (player) => player.player_id === current,
      )
      return stillPresent ? current : next.decision.captain.captain_player_id
    })
    setLoadState('ready')
  }, [])

  const runDecisionRefresh = useCallback(async (
    reason: 'app_open' | 'manual',
    signal?: AbortSignal,
  ) => {
    setSyncState('syncing')
    setRefreshRun(null)
    setSyncMessage('Checking current FPL evidence and rebuilding only the stages that changed…')
    let run = await startWorkspaceRefresh(reason, signal)
    setRefreshRun(run)
    setSyncMessage(run.message)
    while (run.status === 'running' && !signal?.aborted) {
      await pollDelay(signal)
      if (signal?.aborted) return
      run = await getWorkspaceRefresh(signal)
      setRefreshRun(run)
      setSyncMessage(run.message)
    }
    if (signal?.aborted) return
    await refreshWorkspace(signal)
    if (run.status === 'published') {
      setSyncState('success')
      setSyncMessage('Fresh evidence produced a new validated decision receipt.')
      return
    }
    if (run.status === 'reused') {
      setSyncState('success')
      setSyncMessage('The sources were checked and the existing decision receipt is still exact.')
      return
    }
    if (run.status === 'not_ready' || run.status === 'blocked') {
      setSyncState('attention')
      setSyncMessage(run.message)
      return
    }
    setSyncState('error')
    setSyncMessage(run.message)
  }, [refreshWorkspace])

  const syncLatestSquad = useCallback(async () => {
    setSyncState('syncing')
    setSyncMessage('Reading the latest squad from your authenticated FPL session…')
    try {
      if (workspace?.user.sync_state === 'mcp_connected') {
        const result = await syncMcpSquad()
        await refreshWorkspace()
        setSyncMessage(
          `Entry ${result.entry_id} is synced. Starting the decision refresh…`,
        )
      } else {
        await refreshWorkspace()
      }
      await runDecisionRefresh('manual')
      setSquadMode('current')
    } catch (error) {
      setSyncMessage(error instanceof ApiError ? error.message : 'The FPL squad could not be synced.')
      setSyncState('error')
    }
  }, [refreshWorkspace, runDecisionRefresh, workspace])

  useEffect(() => {
    const controller = new AbortController()
    getWorkspace(controller.signal)
      .then((next) => {
        setWorkspace(next)
        setSelectedPlayerId(next.decision.captain.captain_player_id)
        setLoadState('ready')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setLoadError(error instanceof ApiError ? error.message : 'The workspace could not be loaded.')
        setLoadState('error')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (loadState !== 'ready' || connectionCheckedRef.current) return
    connectionCheckedRef.current = true
    const controller = new AbortController()
    void (async () => {
      setSyncState('syncing')
      setSyncMessage('Checking the authenticated squad before refreshing this decision…')
      try {
        const connection = await getMcpConnection(controller.signal)
        if (connection.status === 'connected') {
          await syncMcpSquad(controller.signal)
          await refreshWorkspace(controller.signal)
        } else if (connection.status === 'ready' || connection.status === 'not_authenticated') {
          setProfileOpen(true)
        }
      } catch (error) {
        if (controller.signal.aborted) return
        setSyncMessage(
          error instanceof ApiError
            ? `${error.message} Public evidence will still be checked.`
            : 'The MCP check failed. Public evidence will still be checked.',
        )
      }
      try {
        await runDecisionRefresh('app_open', controller.signal)
      } catch (error) {
        if (controller.signal.aborted) return
        setSyncState('error')
        setSyncMessage(
          error instanceof ApiError
            ? error.message
            : 'The decision refresh could not be started. The last valid workspace is unchanged.',
        )
      }
    })()
    return () => controller.abort()
  }, [loadState, refreshWorkspace, runDecisionRefresh])

  const selectedPlayer = useMemo(() => {
    if (!workspace || selectedPlayerId === null) return null
    return [...workspace.squad.starters, ...workspace.squad.bench].find(
      (player) => player.player_id === selectedPlayerId,
    ) ?? null
  }, [selectedPlayerId, workspace])

  function changeSection(section: string) {
    setActiveSection(section)
    if (section === 'evidence') {
      setEvidenceOpen(true)
      return
    }
    document.getElementById(section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function focusChat() {
    setActiveSection('chat')
    requestAnimationFrame(() => document.getElementById('chat')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  function showRecommendedSquad() {
    setSquadMode('recommended')
    if (workspace) setSelectedPlayerId(workspace.decision.captain.captain_player_id)
    requestAnimationFrame(() => document.getElementById('squad')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  if (loadState === 'loading') return <WorkspaceSkeleton />

  if (loadState === 'error' || !workspace) {
    return (
      <main className="fatal-state">
        <span><WarningCircleIcon size={28} weight="fill" aria-hidden="true" /></span>
        <p className="module-kicker">Application API unavailable</p>
        <h1>The decision room could not open.</h1>
        <p>{loadError}</p>
        <code>uv run fplagent-web --reload</code>
        <button className="primary-button" type="button" onClick={() => void load()}>
          Try again <ArrowRightIcon size={16} aria-hidden="true" />
        </button>
      </main>
    )
  }

  const isPreseason = workspace.phase.phase === 'preseason'
  const connectedPreseason = isPreseason && workspace.squad.source === 'connected'
  const workspaceTitle = connectedPreseason
    ? 'Make your GW1 squad deadline-ready.'
    : workspace.phase.title
  const workspaceNarrative = connectedPreseason
    ? 'Your FPL team is synced. Compare it with the modelled XI, fix the biggest edge first, then use chat to challenge any player or constraint.'
    : workspace.phase.narrative
  const laterAction = workspace.phase.phase === 'pre_deadline'
    ? 'Plan my moves'
    : workspace.phase.phase === 'live_gameweek'
      ? 'Plan next gameweek'
      : 'Review the gameweek'
  const stateLabel = workspace.squad.source === 'connected'
    ? {
        strong: 'FPL synced',
        small: `squad ${formatObservedAt(workspace.freshness.squad_synced_at ?? workspace.generated_at)}`,
      }
    : workspace.squad.confirmed
      ? { strong: 'Draft confirmed', small: 'still advisory' }
      : { strong: 'Not locked', small: 'refresh at deadline' }
  const recommendedStarterIds = new Set(
    workspace.squad.starters
      .map((player) => player.player_id)
      .filter((playerId) => !workspace.decision.captain.benched_player_ids.includes(playerId))
      .concat(workspace.decision.captain.promoted_player_ids),
  )
  const recommendationMetric = workspace.decision.captain.score_metric === 'expected_points'
    ? 'expected_points'
    : 'robust_points'
  const recommendedPlayers = [...workspace.squad.starters, ...workspace.squad.bench]
    .filter((player) => recommendedStarterIds.has(player.player_id))
  const recommendedProjection = recommendedPlayers.reduce(
    (total, player) => total + player[recommendationMetric],
    0,
  ) + (recommendedPlayers.find(
    (player) => player.player_id === workspace.decision.captain.captain_player_id,
  )?.[recommendationMetric] ?? 0)

  return (
    <div className="app-layout">
      <AppRail active={activeSection} onChange={changeSection} onOpenSettings={() => setProfileOpen(true)} />

      <main className="workspace-column">
        <header className="workspace-header">
          <div className="phase-line">
            <span className="phase-pill"><span aria-hidden="true" />{workspace.phase.label}</span>
            <span className="deadline-copy">{workspace.phase.deadline_label}</span>
          </div>
          <div className="workspace-title-row">
            <div>
              <h1>{workspaceTitle}</h1>
              <p>{workspaceNarrative}</p>
            </div>
            <div className="header-actions">
              {isPreseason ? (
                workspace.squad.source === 'connected' ? (
                  <>
                    <button className="secondary-button" type="button" onClick={() => void syncLatestSquad()} disabled={syncState === 'syncing'}>
                      <ArrowClockwiseIcon size={17} aria-hidden="true" />
                      {syncState === 'syncing' ? 'Syncing FPL…' : 'Sync FPL squad'}
                    </button>
                    <button className="primary-button" type="button" onClick={showRecommendedSquad}>
                      <SparkleIcon size={16} aria-hidden="true" />
                      Show best XI
                      <span className="button-island"><ArrowRightIcon size={14} aria-hidden="true" /></span>
                    </button>
                  </>
                ) : (
                  <>
                    <button className="secondary-button" type="button" onClick={() => setImportOpen(true)}>
                      <CloudArrowUpIcon size={17} aria-hidden="true" />
                      Import team
                    </button>
                    <button className="primary-button" type="button" onClick={() => setBuilderOpen(true)}>
                      <SparkleIcon size={16} aria-hidden="true" />
                      Build my GW1 squad
                      <span className="button-island"><ArrowRightIcon size={14} aria-hidden="true" /></span>
                    </button>
                  </>
                )
              ) : (
                <>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => workspace.user.sync_state === 'mcp_connected'
                      ? void syncLatestSquad()
                      : setProfileOpen(true)}
                    disabled={syncState === 'syncing'}
                  >
                    <ArrowClockwiseIcon size={17} aria-hidden="true" />
                    {syncState === 'syncing' ? 'Syncing FPL…' : 'Sync FPL squad'}
                  </button>
                  <button className="primary-button" type="button" onClick={focusChat}>
                    <SparkleIcon size={16} aria-hidden="true" />
                    {laterAction}
                    <span className="button-island"><ArrowRightIcon size={14} aria-hidden="true" /></span>
                  </button>
                </>
              )}
            </div>
          </div>
        </header>

        {syncState !== 'idle' ? (
          <div className={`run-notice is-${syncState}`} role="status" aria-live="polite">
            {syncState === 'error' || syncState === 'attention' ? (
              <WarningCircleIcon size={20} weight="fill" aria-hidden="true" />
            ) : syncState === 'success' ? (
              <CheckCircleIcon size={20} weight="fill" aria-hidden="true" />
            ) : (
              <ArrowClockwiseIcon className="is-spinning" size={20} aria-hidden="true" />
            )}
            <div className="run-notice-copy">
              <strong>{syncState === 'syncing' ? 'Refreshing decision evidence' : syncState === 'success' ? 'Decision workspace is current' : syncState === 'attention' ? 'Decision refresh needs input' : 'Decision refresh failed'}</strong>
              <span>{syncMessage}</span>
              {syncState === 'syncing' && refreshRun?.total_stages ? (
                <div className="run-progress-row">
                  <div
                    className="run-progress-track"
                    role="progressbar"
                    aria-label="Decision refresh progress"
                    aria-valuemin={0}
                    aria-valuemax={refreshRun.total_stages}
                    aria-valuenow={refreshRun.completed_stage_count}
                  >
                    <span style={{ width: `${refreshRun.progress_percent ?? 0}%` }} />
                  </div>
                  <small>{refreshRun.completed_stage_count}/{refreshRun.total_stages} stages</small>
                </div>
              ) : null}
            </div>
            {syncState !== 'syncing' ? <button type="button" onClick={() => setSyncState('idle')}>Dismiss</button> : null}
          </div>
        ) : null}

        {workspace.phase.phase === 'preseason' ? (
          <PreseasonEntry
            workspace={workspace}
            onGenerate={() => setBuilderOpen(true)}
            onImport={() => setImportOpen(true)}
            onProfile={() => setProfileOpen(true)}
          />
        ) : null}

        <div className="workspace-summary" aria-label="Squad summary">
          <div><span>{squadMode === 'recommended' ? `Recommended GW${workspace.phase.event}` : `Current GW${workspace.phase.event}`}</span><strong>{(squadMode === 'recommended' ? recommendedProjection : workspace.squad.expected_points).toFixed(1)}</strong><small>{squadMode === 'recommended' ? `${recommendationMetric.replace('_', ' ')} incl. captain` : 'expected points incl. captain'}</small></div>
          <div><span>Squad cost</span><strong>£{workspace.squad.budget_spent.toFixed(1)}</strong><small>£{workspace.squad.bank.toFixed(1)}m bank</small></div>
          <div><span>Build</span><strong>{squadMode === 'recommended' ? workspace.decision.captain.recommended_formation : workspace.squad.formation}</strong><small>{squadMode === 'recommended' ? 'Best legal XI from your full squad' : workspace.squad.source_label}</small></div>
          <div className="summary-warning"><ShieldWarningIcon size={18} aria-hidden="true" /><span><strong>{stateLabel.strong}</strong><small>{stateLabel.small}</small></span></div>
        </div>

        <SquadPitch
          workspace={workspace}
          selectedPlayerId={selectedPlayerId}
          onSelectPlayer={(player: Player) => setSelectedPlayerId(player.player_id)}
          view={pitchView}
          onViewChange={setPitchView}
          squadMode={squadMode}
          onSquadModeChange={setSquadMode}
        />

        <footer className="workspace-footer">
          <span>Local research build · no FPL account writes</span>
          <button type="button" onClick={() => void syncLatestSquad()} disabled={syncState === 'syncing'}>
            <ArrowClockwiseIcon size={15} aria-hidden="true" /> {workspace.squad.source === 'connected' ? 'Sync latest FPL squad' : 'Refresh workspace'}
          </button>
        </footer>
      </main>

      <aside className="intelligence-column">
        <DecisionRail
          workspace={workspace}
          selectedPlayer={selectedPlayer}
          onSelectPlayer={(player: Player) => setSelectedPlayerId(player.player_id)}
          onOpenEvidence={() => setEvidenceOpen(true)}
          onPreviewRecommendation={() => setSquadMode('recommended')}
        />
          <ChatPanel workspace={workspace} focused={activeSection === 'chat'} onWorkspaceChanged={refreshWorkspace} />
      </aside>

      <ImportTeamDialog open={importOpen} onClose={() => setImportOpen(false)} onConfirmed={refreshWorkspace} onAddIdentity={() => setProfileOpen(true)} />
      <GenerateSquadDialog open={builderOpen} workspace={workspace} onClose={() => setBuilderOpen(false)} onComplete={refreshWorkspace} />
      <ManagerProfileDialog open={profileOpen} workspace={workspace} onClose={() => setProfileOpen(false)} onComplete={refreshWorkspace} />
      <EvidenceDialog open={evidenceOpen} workspace={workspace} onClose={() => setEvidenceOpen(false)} />
    </div>
  )
}

export default App
