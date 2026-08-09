import { Component, type ErrorInfo, type ReactNode } from 'react'

import { ArrowClockwiseIcon, WarningCircleIcon } from '@phosphor-icons/react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  failed: boolean
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('FPLAgent render failure', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="fatal-state" role="alert">
        <span><WarningCircleIcon size={28} weight="fill" aria-hidden="true" /></span>
        <p className="module-kicker">Workspace recovery</p>
        <h1>The decision room hit an unexpected client error.</h1>
        <p>
          Your local squad data has not been changed. Reload the workspace; if the error returns,
          restart the local app processes so the client and API use the same build.
        </p>
        <code>bash scripts/run_local_web.sh</code>
        <button className="primary-button" type="button" onClick={() => window.location.reload()}>
          <ArrowClockwiseIcon size={16} aria-hidden="true" /> Reload workspace
        </button>
      </main>
    )
  }
}
