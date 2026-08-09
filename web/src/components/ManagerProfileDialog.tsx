import { FormEvent, useEffect, useRef, useState } from 'react'

import {
  ArrowRightIcon,
  ArrowUpRightIcon,
  CheckCircleIcon,
  IdentificationCardIcon,
  LinkSimpleIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
  XIcon,
} from '@phosphor-icons/react'

import {
  ApiError,
  beginMcpLogin,
  getMcpConnection,
  pollMcpLogin,
  saveManagerProfile,
  syncMcpSquad,
} from '../api'
import type { McpConnection, Workspace } from '../types'
import { useDialogAccessibility } from '../useDialogAccessibility'

interface ManagerProfileDialogProps {
  open: boolean
  workspace: Workspace
  onClose: () => void
  onComplete: () => Promise<void>
}

export function ManagerProfileDialog({
  open,
  workspace,
  onClose,
  onComplete,
}: ManagerProfileDialogProps) {
  const [entryId, setEntryId] = useState(workspace.user.fpl_entry_id?.toString() ?? '')
  const [displayName, setDisplayName] = useState(workspace.user.display_name)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [mcp, setMcp] = useState<McpConnection | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [needsAuthentication, setNeedsAuthentication] = useState(false)
  const [connectionCopy, setConnectionCopy] = useState('')
  const [loginFrameUrl, setLoginFrameUrl] = useState('')
  const pollTimerRef = useRef<number | null>(null)
  const autoStartRef = useRef(false)
  const dialogRef = useDialogAccessibility<HTMLElement>(open, close, saving)

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void getMcpConnection(controller.signal)
      .then((connection) => {
        setMcp(connection)
        if (autoStartRef.current) return
        autoStartRef.current = true
        if (connection.status === 'connected') {
          void syncExistingMcp()
        } else if (connection.status === 'ready' || connection.status === 'not_authenticated') {
          void connectMcp()
        }
      })
      .catch(() => setMcp({ status: 'offline', url: 'http://127.0.0.1:8021/mcp', tools_available: 0, message: 'The local FPL MCP server is not reachable.' }))
    return () => controller.abort()
    // This is deliberately a one-shot orchestration per dialog opening. Adding action
    // identities would restart an in-flight MCP login after every status render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => () => {
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current)
  }, [])

  async function connectMcp() {
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current)
    setConnecting(true)
    setError('')
    setLoginFrameUrl('')
    setConnectionCopy('Creating a local FPL login request…')
    try {
      const started = await beginMcpLogin()
      const embeddedLoginUrl = new URL(started.login_url)
      embeddedLoginUrl.searchParams.set('embed', '1')
      setLoginFrameUrl(embeddedLoginUrl.toString())
      setConnectionCopy('Waiting for you to connect. This workspace will detect the session automatically.')
      pollConnection(started.request_id)
    } catch (caught) {
      setConnecting(false)
      setError(caught instanceof ApiError ? caught.message : 'The MCP login could not start.')
    }
  }

  async function syncExistingMcp() {
    setConnecting(true)
    setError('')
    setConnectionCopy('Reading the latest authenticated FPL squad…')
    try {
      const sync = await syncMcpSquad()
      setEntryId(sync.entry_id.toString())
      await onComplete()
      setConnecting(false)
      setLoginFrameUrl('')
      setSaved(true)
    } catch (caught) {
      setConnecting(false)
      setNeedsAuthentication(true)
      setConnectionCopy('')
      setError(caught instanceof ApiError ? `${caught.message} Reconnect to authenticate this MCP process.` : 'The authenticated squad could not be synced. Reconnect and try again.')
    }
  }

  function close() {
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current)
    setEntryId(workspace.user.fpl_entry_id?.toString() ?? '')
    setDisplayName(workspace.user.display_name)
    setSaved(false)
    setError('')
    setConnectionCopy('')
    setLoginFrameUrl('')
    setConnecting(false)
    setNeedsAuthentication(false)
    autoStartRef.current = false
    onClose()
  }

  function cancelLogin() {
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current)
    setLoginFrameUrl('')
    setConnecting(false)
    setConnectionCopy('')
    setError('')
  }

  function pollConnection(requestId: string) {
    pollTimerRef.current = window.setTimeout(async () => {
      try {
        const status = await pollMcpLogin(requestId)
        if (status.status === 'pending') {
          pollConnection(requestId)
          return
        }
        if (status.status === 'failed') {
          setConnecting(false)
          setError(status.error ?? 'FPL authentication failed.')
          setConnectionCopy('The connection was not completed. Start a fresh local login request to try again.')
          return
        }
        setConnectionCopy('Authenticated. Reading the current squad into the workspace…')
        const sync = await syncMcpSquad()
        setEntryId(sync.entry_id.toString())
        await onComplete()
        setConnecting(false)
        setLoginFrameUrl('')
        setSaved(true)
      } catch (caught) {
        setConnecting(false)
        setError(caught instanceof ApiError ? caught.message : 'The authenticated squad could not be synced.')
      }
    }, 1800)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const numericId = Number(entryId)
    if (!Number.isInteger(numericId) || numericId < 1) {
      setError('Enter the numeric entry ID from your FPL points-page URL.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await saveManagerProfile(displayName.trim() || 'Lewis', numericId)
      await onComplete()
      setSaved(true)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The manager profile could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !saving && close()}>
      <section ref={dialogRef} className="profile-shell" role="dialog" aria-modal="true" aria-labelledby="profile-title">
        <div className="profile-dialog">
          <header className="dialog-header">
            <div>
              <span className="module-kicker">Season continuity</span>
              <h2 id="profile-title">{loginFrameUrl ? 'Connect FPL without leaving the workspace.' : 'Give this workspace your FPL identity.'}</h2>
              <p className="dialog-intro">{loginFrameUrl ? 'Your credentials go directly to the local MCP login service. FPLAgent only receives the authenticated squad snapshot.' : 'The pitch can then follow the same manager through every deadline instead of relying on screenshots each week.'}</p>
            </div>
            <button className="icon-button" type="button" onClick={close} disabled={saving} aria-label="Close manager profile">
              <XIcon size={18} aria-hidden="true" />
            </button>
          </header>

          {saved ? (
            <div className="profile-saved">
              <span><CheckCircleIcon size={30} weight="fill" aria-hidden="true" /></span>
              <div><strong>Entry {entryId} is saved locally.</strong><p>{workspace.user.sync_state === 'mcp_connected' ? 'The authenticated FPL squad is now the active workspace.' : 'This identity can anchor future public history and authenticated squad refreshes.'}</p></div>
              <button className="primary-button" type="button" onClick={close}>Return to squad <span className="button-island"><ArrowRightIcon size={14} /></span></button>
            </div>
          ) : (
            loginFrameUrl ? (
              <div className="embedded-login-stage">
                <div className="embedded-login-toolbar">
                  <div>
                    <span className="local-service-pill"><span />127.0.0.1:8020 · local MCP</span>
                    <strong>Sign in to Fantasy Premier League</strong>
                    <small>The email and password fields below belong to the MCP page, not the React application.</small>
                  </div>
                  <button className="secondary-button" type="button" onClick={connecting ? cancelLogin : () => void connectMcp()}>
                    {connecting ? 'Cancel' : 'Start again'}
                  </button>
                </div>

                <div className="embedded-login-frame-shell">
                  <iframe
                    className="embedded-login-frame"
                    src={loginFrameUrl}
                    title="Local FPL MCP account login"
                    referrerPolicy="no-referrer"
                    sandbox="allow-forms allow-scripts"
                  />
                </div>

                <div className={`embedded-login-status${connecting ? ' is-active' : ' is-failed'}`} aria-live="polite">
                  <span className="connection-pulse" aria-hidden="true" />
                  <div>
                    <strong>{connecting ? 'Waiting for authenticated session' : 'Connection needs attention'}</strong>
                    <small>{connectionCopy}</small>
                  </div>
                  <ShieldCheckIcon size={20} aria-hidden="true" />
                </div>
                {error ? <p className="profile-error"><WarningCircleIcon size={16} weight="fill" />{error}</p> : null}
              </div>
            ) : (
            <>
              <div className={`mcp-connect-panel is-${mcp?.status ?? 'checking'}`}>
                <span className="mcp-mark"><LinkSimpleIcon size={20} aria-hidden="true" /></span>
                <div>
                  <small>Authenticated local sync</small>
                  <strong>{mcp?.status === 'ready' || mcp?.status === 'not_authenticated' ? 'FPL MCP is running' : mcp?.status === 'connected' ? 'FPL MCP is connected' : mcp?.status === 'offline' ? 'FPL MCP is not running' : 'Checking the local MCP server'}</strong>
                  <p>{connectionCopy || mcp?.message || 'Credentials are entered in a protected local MCP panel; FPLAgent never stores them.'}</p>
                  {mcp?.status === 'offline' ? <code>cd ../fpl-mcp-server &amp;&amp; FPL_MCP_TRANSPORT=streamable-http PYTHONPATH=src uv run python -m fpl_server.main</code> : null}
                </div>
                {mcp?.status === 'ready' || mcp?.status === 'not_authenticated' || mcp?.status === 'connected' ? (
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => void (workspace.user.sync_state === 'mcp_connected' && !needsAuthentication ? syncExistingMcp() : connectMcp())}
                    disabled={connecting}
                  >
                    {connecting
                      ? workspace.user.sync_state === 'mcp_connected' && !needsAuthentication ? 'Syncing squad…' : 'Waiting for login…'
                      : workspace.user.sync_state === 'mcp_connected' && !needsAuthentication ? 'Sync latest squad' : needsAuthentication ? 'Reconnect and sync' : 'Connect and sync'}
                    <span className="button-island"><ArrowUpRightIcon size={14} /></span>
                  </button>
                ) : null}
              </div>

              <div className="manual-divider"><span>or identify the public manager without signing in</span></div>

              <form onSubmit={submit}>
              <div className="profile-grid">
                <div className="profile-form-fields">
                  <label>
                    <span>Your name</span>
                    <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={80} autoComplete="name" />
                  </label>
                  <label>
                    <span>FPL entry ID</span>
                    <input value={entryId} onChange={(event) => setEntryId(event.target.value.replace(/\D/g, ''))} inputMode="numeric" placeholder="For example, 431892" aria-describedby="entry-id-help" />
                    <small id="entry-id-help">Optional when connecting MCP: it is detected and verified after login. For public-only setup, copy the number after <code>/entry/</code> in your FPL URL.</small>
                  </label>
                  {error ? <p className="profile-error"><WarningCircleIcon size={16} weight="fill" />{error}</p> : null}
                </div>

                <aside className="identity-explainer">
                  <div><IdentificationCardIcon size={19} /><span><strong>Entry ID</strong><small>Identifies the public manager record and gameweek history.</small></span></div>
                  <div><LinkSimpleIcon size={19} /><span><strong>MCP session</strong><small>Reads the private pre-deadline squad and verifies which entry actually signed in.</small></span></div>
                  <div><ShieldCheckIcon size={19} /><span><strong>Credentials isolated</strong><small>Email and password are handled only by the local MCP page. FPLAgent does not receive them.</small></span></div>
                </aside>
              </div>
              <footer className="dialog-footer">
                <span>You can generate or import a squad before adding an entry ID.</span>
                <div><button className="primary-button" type="submit" disabled={saving || !entryId}>{saving ? 'Saving…' : 'Save manager identity'} <span className="button-island"><ArrowRightIcon size={14} /></span></button></div>
              </footer>
              </form>
            </>
            )
          )}
        </div>
      </section>
    </div>
  )
}
