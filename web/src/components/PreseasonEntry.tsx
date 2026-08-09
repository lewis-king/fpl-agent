import {
  ArrowRightIcon,
  CloudArrowUpIcon,
  IdentificationCardIcon,
  SparkleIcon,
} from '@phosphor-icons/react'

import type { Workspace } from '../types'

interface PreseasonEntryProps {
  workspace: Workspace
  onGenerate: () => void
  onImport: () => void
  onProfile: () => void
}

export function PreseasonEntry({ workspace, onGenerate, onImport, onProfile }: PreseasonEntryProps) {
  const connected = workspace.squad.source === 'connected'
  return (
    <section className="entry-paths" aria-labelledby="entry-path-title">
      <div className="entry-path-heading">
        <span className="module-kicker">Your route into GW1</span>
        <h2 id="entry-path-title">{connected ? 'Your FPL squad is in. Pressure-test it before GW1.' : 'Start with the model or bring your own thinking.'}</h2>
      </div>
      <button className="entry-path entry-path-primary" type="button" onClick={onGenerate}>
        <span className="entry-icon"><SparkleIcon size={19} weight="duotone" aria-hidden="true" /></span>
        <span>
          <small>{connected ? 'Improve this squad' : 'Generate a squad'}</small>
          <strong>{connected ? 'Build a stronger variation' : 'Best available, then make it yours'}</strong>
          <em>{connected ? 'Keep players · change strategy · add a club rule' : 'Published baseline is instant · constrained builds take seconds'}</em>
        </span>
        <span className="entry-arrow"><ArrowRightIcon size={15} /></span>
      </button>
      <button className="entry-path" type="button" onClick={onImport}>
        <span className="entry-icon"><CloudArrowUpIcon size={19} aria-hidden="true" /></span>
        <span><small>{connected ? 'Compare another draft' : 'Already made a draft?'}</small><strong>Upload, score and critique it</strong><em>Screenshot extraction · legal checks · suggested changes</em></span>
        <span className="entry-arrow"><ArrowRightIcon size={15} /></span>
      </button>
      <button className={`identity-path ${workspace.user.fpl_entry_id ? 'is-saved' : ''}`} type="button" onClick={onProfile}>
        <IdentificationCardIcon size={18} aria-hidden="true" />
        <span>
          <small>Season identity</small>
          <strong>{workspace.user.fpl_entry_id ? `Entry ${workspace.user.fpl_entry_id}` : 'Add FPL entry ID'}</strong>
        </span>
        <em>{workspace.user.fpl_entry_id ? 'Saved locally' : 'Keeps this squad with you after GW1'}</em>
      </button>
    </section>
  )
}
