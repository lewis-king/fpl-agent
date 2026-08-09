import { ArrowUpRightIcon, DatabaseIcon, XIcon } from '@phosphor-icons/react'

import type { Workspace } from '../types'
import { useDialogAccessibility } from '../useDialogAccessibility'

interface EvidenceDialogProps {
  open: boolean
  workspace: Workspace
  onClose: () => void
}

export function EvidenceDialog({ open, workspace, onClose }: EvidenceDialogProps) {
  const dialogRef = useDialogAccessibility<HTMLElement>(open, onClose)
  if (!open) return null

  return (
    <div className="dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="evidence-shell" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <div className="evidence-dialog">
          <header className="dialog-header">
            <div>
              <span className="module-kicker">Provenance</span>
              <h2 id="evidence-title">The trail behind this decision.</h2>
            </div>
            <button className="icon-button" type="button" onClick={onClose} aria-label="Close evidence dialog">
              <XIcon size={18} aria-hidden="true" />
            </button>
          </header>
          <div className="receipt-feature">
            <DatabaseIcon size={22} aria-hidden="true" />
            <div>
              <span>
                {workspace.decision.weekly.status === 'ready'
                  ? `GW${workspace.decision.weekly.event} action receipt`
                  : 'Captain decision receipt'}
              </span>
              <code>
                {workspace.decision.weekly.receipt_sha256
                  ?? workspace.decision.captain.receipt_id}
              </code>
            </div>
          </div>
          <div className="evidence-list">
            {workspace.decision.evidence.map((item, index) => (
              <article key={item.sha256}>
                <span>0{index + 1}</span>
                <div><h3>{item.label}</h3><p>{item.path}</p><code>{item.sha256}</code></div>
                <ArrowUpRightIcon size={17} aria-hidden="true" />
              </article>
            ))}
          </div>
          <div className="evidence-caveat">
            <strong>Current boundary</strong>
            <p>{workspace.decision.caveat}</p>
          </div>
        </div>
      </section>
    </div>
  )
}
