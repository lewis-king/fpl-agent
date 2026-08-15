import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  ArrowClockwiseIcon,
  ArrowRightIcon,
  ArrowsLeftRightIcon,
  ChartDonutIcon,
  ChatCircleDotsIcon,
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
type SquadMode = 'current' | 'model' | 'recommended'

function pollDelay(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, 1_500)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer)
      resolve()
    }, { once: true })
  })
}

function squadDecisionSignature(workspace: Workspace): string {
  return JSON.stringify(
    [...workspace.squad.starters, ...workspace.squad.bench].map((player) => [
      player.player_id,
      player.role,
      player.order,
      player.captain,
      player.vice_captain,
    ]),
  )
}

function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [loadError, setLoadError] = useState('')
  const [activeSection, setActiveSection] = useState('squad')
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [pitchView, setPitchView] = useState<'pitch' | 'list'>('pitch')
  const [squadMode, setSquadMode] = useState<SquadMode>('current')
  const [importOpen, setImportOpen] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [builderOpen, setBuilderOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [syncState, setSyncState] = useState<SyncState>('idle')
  const [syncMessage, setSyncMessage] = useState('')
  const [refreshRun, setRefreshRun] = useState<WorkspaceRefresh | null>(null)
  const connectionCheckedRef = useRef(false)
  const workspaceSquadSignatureRef = useRef<string | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadState('loading')
    setLoadError('')
    try {
      const next = await getWorkspace(signal)
      workspaceSquadSignatureRef.current = squadDecisionSignature(next)
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
    workspaceSquadSignatureRef.current = squadDecisionSignature(next)
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
      setSyncMessage(run.message || 'The recent validated decision receipt is still current.')
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
        workspaceSquadSignatureRef.current = squadDecisionSignature(next)
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
      let refreshReason: 'app_open' | 'manual' = 'app_open'
      setSyncState('syncing')
      setSyncMessage('Checking the authenticated squad before refreshing this decision…')
      try {
        const connection = await getMcpConnection(controller.signal)
        if (connection.status === 'connected') {
          const previousSquadSignature = workspaceSquadSignatureRef.current
          await syncMcpSquad(controller.signal)
          await refreshWorkspace(controller.signal)
          if (
            previousSquadSignature
            && workspaceSquadSignatureRef.current !== previousSquadSignature
          ) {
            refreshReason = 'manual'
          }
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
        await runDecisionRefresh(refreshReason, controller.signal)
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
    return [
      ...(workspace.decision.model_squad?.starters ?? []),
      ...(workspace.decision.model_squad?.bench ?? []),
      ...workspace.decision.recommended_squad.starters,
      ...workspace.decision.recommended_squad.bench,
      ...workspace.squad.starters,
      ...workspace.squad.bench,
    ].find(
      (player) => player.player_id === selectedPlayerId,
    ) ?? null
  }, [selectedPlayerId, workspace])

  function changeSection(section: string) {
    setActiveSection(section)
    if (section === 'evidence') {
      setEvidenceOpen(true)
      return
    }
    requestAnimationFrame(() => {
      const target = section === 'decisions' || section === 'chat' ? 'assistant' : section
      document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  function focusChat() {
    setActiveSection('chat')
    requestAnimationFrame(() => document.getElementById('assistant')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  function selectPlayer(player: Player) {
    setSelectedPlayerId(player.player_id)
    setActiveSection('decisions')
  }

  function changeSquadMode(mode: SquadMode) {
    setSquadMode(mode)
    if (!workspace) return
    const players = mode === 'model' && workspace.decision.model_squad
      ? [...workspace.decision.model_squad.starters, ...workspace.decision.model_squad.bench]
      : mode === 'recommended'
        ? [
            ...workspace.decision.recommended_squad.starters,
            ...workspace.decision.recommended_squad.bench,
          ]
        : [...workspace.squad.starters, ...workspace.squad.bench]
    setSelectedPlayerId(
      players.find((player) => player.captain)?.player_id
        ?? players[0]?.player_id
        ?? null,
    )
  }

  function showModelSquad() {
    changeSquadMode(workspace?.decision.model_squad ? 'model' : 'recommended')
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
  const decisionEvent = workspace.phase.decision_event ?? workspace.phase.event
  const connectedPreseason = isPreseason && workspace.squad.source === 'connected'
  const workspaceTitle = connectedPreseason
    ? 'Make your GW1 squad deadline-ready.'
    : workspace.phase.title
  const workspaceNarrative = connectedPreseason
    ? 'Your FPL team is synced. Compare all 15 players with the published model squad, inspect every change, then use chat to challenge any pick or constraint.'
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
  const recommendationMetric = workspace.decision.captain.score_metric === 'expected_points'
    ? 'expected_points'
    : 'robust_points'
  const recommendedProjection = workspace.decision.recommended_squad.expected_points
  const recommendationLabel = workspace.decision.recommended_squad.source === 'weekly_decision'
    ? 'shared-scenario points incl. captain'
    : `${recommendationMetric.replace('_', ' ')} incl. captain`
  const modelSquad = workspace.decision.model_squad
  const modelPreview = squadMode === 'model' ? modelSquad : null
  const recommendedPreview = squadMode === 'recommended'
  const summaryProjection = modelPreview?.expected_points
    ?? (recommendedPreview ? recommendedProjection : workspace.squad.expected_points)
  const summaryCost = modelPreview?.budget_spent ?? workspace.squad.budget_spent
  const summaryBank = modelPreview?.bank ?? workspace.squad.bank
  const summaryFormation = modelPreview?.formation
    ?? (recommendedPreview
      ? workspace.decision.recommended_squad.formation
      : workspace.squad.formation)
  const summaryTitle = modelPreview
    ? `Model squad · GW${modelPreview.event}`
    : recommendedPreview
      ? `Best XI · GW${decisionEvent}`
      : `Your squad · GW${decisionEvent}`
  const summaryProjectionLabel = modelPreview
    ? 'GW1 xP incl. captain · horizon-selected'
    : recommendedPreview
      ? recommendationLabel
      : 'GW1 xP incl. captain'
  const summaryBuildLabel = modelPreview
    ? 'Published 15-player optimiser result'
    : recommendedPreview
      ? (workspace.decision.recommended_squad.source === 'weekly_decision'
        ? 'Selected transfer route and legal XI'
        : 'Best legal XI from your full squad')
      : workspace.squad.source_label
  const currentSquadPlayers = [...workspace.squad.starters, ...workspace.squad.bench]
  const currentSquadIds = new Set(currentSquadPlayers.map((player) => player.player_id))
  const modelSquadPlayers = modelSquad ? [...modelSquad.starters, ...modelSquad.bench] : []
  const modelSquadIds = new Set(modelSquadPlayers.map((player) => player.player_id))
  const modelIncoming = modelSquadPlayers.filter((player) => !currentSquadIds.has(player.player_id))
  const modelOutgoing = currentSquadPlayers.filter((player) => !modelSquadIds.has(player.player_id))
  const modelGw1Delta = modelSquad ? modelSquad.expected_points - workspace.squad.expected_points : 0
  const intelligenceMode = activeSection === 'chat' ? 'chat' : 'analysis'

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
                    <button className="primary-button" type="button" onClick={showModelSquad}>
                      <SparkleIcon size={16} aria-hidden="true" />
                      Compare model squad
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
              <strong>{syncState === 'syncing' ? 'Refreshing decision evidence' : syncState === 'success' ? 'Decision workspace is current' : syncState === 'attention' ? 'Preseason roles need verification' : 'Decision refresh failed'}</strong>
              <span>
                {syncState === 'attention'
                  ? 'The previous validated workspace remains active while uncertain player roles are checked.'
                  : syncMessage}
              </span>
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
              {syncState === 'attention' || syncState === 'error' ? (
                <details className="run-notice-details">
                  <summary>View refresh details</summary>
                  <p>{syncMessage}</p>
                </details>
              ) : null}
            </div>
            {syncState !== 'syncing' ? <button type="button" onClick={() => setSyncState('idle')}>Dismiss</button> : null}
          </div>
        ) : null}

        {workspace.phase.phase === 'preseason' && !connectedPreseason ? (
          <PreseasonEntry
            workspace={workspace}
            onGenerate={() => setBuilderOpen(true)}
            onImport={() => setImportOpen(true)}
            onProfile={() => setProfileOpen(true)}
          />
        ) : null}

        <div className="workspace-summary" aria-label="Squad summary">
          <div><span>{summaryTitle}</span><strong>{summaryProjection.toFixed(1)}</strong><small>{summaryProjectionLabel}</small></div>
          <div><span>Squad cost</span><strong>£{summaryCost.toFixed(1)}</strong><small>£{summaryBank.toFixed(1)}m bank</small></div>
          <div><span>Build</span><strong>{summaryFormation}</strong><small>{summaryBuildLabel}</small></div>
          <div className="summary-warning"><ShieldWarningIcon size={18} aria-hidden="true" /><span><strong>{modelPreview ? 'Preview only' : stateLabel.strong}</strong><small>{modelPreview ? 'No changes sent to FPL' : stateLabel.small}</small></span></div>
        </div>

        {modelPreview ? (
          <section className="model-squad-comparison" aria-label="Model squad comparison">
            <div className="comparison-heading">
              <span className="comparison-icon"><ArrowsLeftRightIcon size={18} aria-hidden="true" /></span>
              <div>
                <span className="module-kicker">What changes</span>
                <strong>{modelIncoming.length} player{modelIncoming.length === 1 ? '' : 's'} differ from your FPL squad</strong>
              </div>
            </div>
            <div className="comparison-swaps">
              <p><span>In</span>{modelIncoming.length ? modelIncoming.map((player) => player.name).join(', ') : 'No player changes'}</p>
              <p><span>Out</span>{modelOutgoing.length ? modelOutgoing.map((player) => player.name).join(', ') : 'No player changes'}</p>
            </div>
            <div className="comparison-reason">
              <strong className={modelGw1Delta < 0 ? 'is-tradeoff' : 'is-positive'}>
                {modelGw1Delta >= 0 ? '+' : '−'}{Math.abs(modelGw1Delta).toFixed(1)} GW1 xP
              </strong>
              <p>
                {modelGw1Delta < 0
                  ? `The model accepts a ${Math.abs(modelGw1Delta).toFixed(1)}-point GW1 trade-off because this squad wins the multi-gameweek robustness tests.`
                  : 'The model improves GW1 projection and also wins the multi-gameweek robustness tests.'}
              </p>
              <small>{modelPreview.selection_basis} · {modelPreview.candidate_id}</small>
            </div>
          </section>
        ) : null}

        <SquadPitch
          workspace={workspace}
          selectedPlayerId={selectedPlayerId}
          onSelectPlayer={selectPlayer}
          view={pitchView}
          onViewChange={setPitchView}
          squadMode={squadMode}
          onSquadModeChange={changeSquadMode}
        />

        {connectedPreseason ? (
          <PreseasonEntry
            workspace={workspace}
            onGenerate={() => setBuilderOpen(true)}
            onImport={() => setImportOpen(true)}
            onProfile={() => setProfileOpen(true)}
          />
        ) : null}

        <footer className="workspace-footer">
          <span>Local research build · no FPL account writes</span>
          <button type="button" onClick={() => void syncLatestSquad()} disabled={syncState === 'syncing'}>
            <ArrowClockwiseIcon size={15} aria-hidden="true" /> {workspace.squad.source === 'connected' ? 'Sync latest FPL squad' : 'Refresh workspace'}
          </button>
        </footer>
      </main>

      <aside className="intelligence-column" id="assistant">
        <div className="intelligence-switcher" role="tablist" aria-label="Assistant view">
          <button
            className={intelligenceMode === 'analysis' ? 'is-active' : ''}
            type="button"
            role="tab"
            aria-selected={intelligenceMode === 'analysis'}
            onClick={() => changeSection('decisions')}
          >
            <ChartDonutIcon size={15} weight={intelligenceMode === 'analysis' ? 'fill' : 'regular'} aria-hidden="true" />
            Analysis
          </button>
          <button
            className={intelligenceMode === 'chat' ? 'is-active' : ''}
            type="button"
            role="tab"
            aria-selected={intelligenceMode === 'chat'}
            onClick={focusChat}
          >
            <ChatCircleDotsIcon size={15} weight={intelligenceMode === 'chat' ? 'fill' : 'regular'} aria-hidden="true" />
            Ask FPLAgent
          </button>
        </div>
        <div className="intelligence-view">
          <div className="intelligence-pane" hidden={intelligenceMode !== 'analysis'}>
            <DecisionRail
              workspace={workspace}
              squadMode={squadMode}
              selectedPlayer={selectedPlayer}
              onSelectPlayer={selectPlayer}
              onOpenEvidence={() => setEvidenceOpen(true)}
              onPreviewRecommendation={() => setSquadMode('recommended')}
            />
          </div>
          <div className="intelligence-pane" hidden={intelligenceMode !== 'chat'}>
            <ChatPanel workspace={workspace} focused onWorkspaceChanged={refreshWorkspace} />
          </div>
        </div>
      </aside>

      <ImportTeamDialog open={importOpen} onClose={() => setImportOpen(false)} onConfirmed={refreshWorkspace} onAddIdentity={() => setProfileOpen(true)} />
      <GenerateSquadDialog open={builderOpen} workspace={workspace} onClose={() => setBuilderOpen(false)} onComplete={refreshWorkspace} />
      <ManagerProfileDialog open={profileOpen} workspace={workspace} onClose={() => setProfileOpen(false)} onComplete={refreshWorkspace} />
      <EvidenceDialog open={evidenceOpen} workspace={workspace} onClose={() => setEvidenceOpen(false)} />
    </div>
  )
}

export default App
