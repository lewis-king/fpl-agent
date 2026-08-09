import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from 'react'

import {
  ArrowRightIcon,
  CheckCircleIcon,
  FileImageIcon,
  ScanIcon,
  ShieldCheckIcon,
  UploadSimpleIcon,
  WarningCircleIcon,
  XIcon,
} from '@phosphor-icons/react'

import {
  ApiError,
  analyseUpload,
  confirmUpload,
  getUploadStatus,
  uploadTeam,
} from '../api'
import type { UploadStatus } from '../types'
import { useDialogAccessibility } from '../useDialogAccessibility'

interface ImportTeamDialogProps {
  open: boolean
  onClose: () => void
  onConfirmed: () => Promise<void>
  onAddIdentity: () => void
}

type ImportStep = 'choose' | 'uploading' | 'analysing' | 'review' | 'confirmed' | 'error'

const acceptedTypes = ['image/jpeg', 'image/png', 'image/webp']

export function ImportTeamDialog({ open, onClose, onConfirmed, onAddIdentity }: ImportTeamDialogProps) {
  const [file, setFile] = useState<File | null>(null)
  const [step, setStep] = useState<ImportStep>('choose')
  const [job, setJob] = useState<UploadStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const pollRef = useRef<number | null>(null)
  const dialogRef = useDialogAccessibility<HTMLElement>(open, close)

  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview)
    }
  }, [preview])

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearTimeout(pollRef.current)
    }
  }, [])

  function reset() {
    if (pollRef.current) window.clearTimeout(pollRef.current)
    setFile(null)
    setStep('choose')
    setJob(null)
    setError(null)
  }

  function close() {
    if (step === 'uploading' || step === 'analysing') {
      onClose()
      return
    }
    reset()
    onClose()
  }

  function acceptFile(candidate: File | undefined) {
    setError(null)
    if (!candidate) return
    if (!acceptedTypes.includes(candidate.type)) {
      setError('Choose a JPEG, PNG or WebP screenshot.')
      return
    }
    if (candidate.size > 10 * 1024 * 1024) {
      setError('The screenshot must be 10 MB or smaller.')
      return
    }
    setFile(candidate)
    setStep('choose')
  }

  function onFileInput(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.target.files?.[0])
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    acceptFile(event.dataTransfer.files[0])
  }

  async function beginAnalysis() {
    if (!file) return
    setStep('uploading')
    setError(null)
    try {
      const accepted = await uploadTeam(file)
      await analyseUpload(accepted.upload_id)
      setStep('analysing')
      poll(accepted.upload_id)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The screenshot could not be uploaded.')
      setStep('error')
    }
  }

  function poll(uploadId: string) {
    pollRef.current = window.setTimeout(async () => {
      try {
        const status = await getUploadStatus(uploadId)
        setJob(status)
        if (status.status === 'ready_for_review') {
          setStep('review')
          return
        }
        if (status.status === 'failed') {
          setError(status.error ?? 'Vision analysis failed.')
          setStep('error')
          return
        }
        poll(uploadId)
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : 'The analysis status was unavailable.')
        setStep('error')
      }
    }, 1800)
  }

  async function confirm() {
    if (!job) return
    try {
      await confirmUpload(job.upload_id)
      await onConfirmed()
      setStep('confirmed')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The squad could not be confirmed.')
    }
  }

  if (!open) return null

  const proposal = job?.result?.proposal
  const valid = job?.result?.team_valid ?? false

  return (
    <div className="dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}>
      <section ref={dialogRef} className="import-shell" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="import-dialog">
          <header className="dialog-header">
            <div>
              <span className="module-kicker">Vision import</span>
              <h2 id="import-title">Bring your FPL team into the room.</h2>
            </div>
            <button className="icon-button" type="button" onClick={close} aria-label="Close import dialog">
              <XIcon size={18} aria-hidden="true" />
            </button>
          </header>

          <div className="import-progress" aria-label="Import progress">
            {[
              ['01', 'Screenshot'],
              ['02', 'Resolve'],
              ['03', 'Confirm'],
            ].map(([number, label], index) => {
              const currentIndex = step === 'choose' || step === 'uploading' ? 0 : step === 'analysing' ? 1 : 2
              return (
                <div className={index <= currentIndex ? 'is-active' : ''} key={number}>
                  <span>{number}</span>
                  <strong>{label}</strong>
                </div>
              )
            })}
          </div>

          {step === 'choose' || step === 'uploading' ? (
            <div className="import-grid">
              <div
                className={`drop-zone ${preview ? 'has-preview' : ''}`}
                onDragOver={(event) => event.preventDefault()}
                onDrop={onDrop}
              >
                {preview ? (
                  <img src={preview} alt="Selected FPL team screenshot preview" />
                ) : (
                  <div className="drop-copy">
                    <span className="upload-mark"><UploadSimpleIcon size={25} aria-hidden="true" /></span>
                    <h3>Drop your Pick Team screenshot</h3>
                    <p>Mobile and desktop captures both work. Keep all 15 players visible where possible.</p>
                  </div>
                )}
                <input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={onFileInput} hidden />
                <button type="button" className="secondary-button" onClick={() => inputRef.current?.click()}>
                  <FileImageIcon size={17} aria-hidden="true" />
                  {file ? 'Choose another image' : 'Browse files'}
                </button>
              </div>
              <div className="import-guidance">
                <span className="guidance-index">A clearer screenshot gives a faster review</span>
                <ul>
                  <li><CheckCircleIcon size={17} weight="fill" aria-hidden="true" />Include starters and the full bench.</li>
                  <li><CheckCircleIcon size={17} weight="fill" aria-hidden="true" />Leave captain and vice badges visible.</li>
                  <li><CheckCircleIcon size={17} weight="fill" aria-hidden="true" />Avoid overlays across player names.</li>
                </ul>
                <div className="privacy-note">
                  <ShieldCheckIcon size={19} aria-hidden="true" />
                  <p>The image stays on this machine. Extraction remains provisional until you confirm it.</p>
                </div>
              </div>
            </div>
          ) : null}

          {step === 'analysing' ? (
            <div className="analysis-state">
              <div className="scanner-visual">
                {preview ? <img src={preview} alt="Screenshot being analysed" /> : null}
                <span className="scan-line" aria-hidden="true" />
              </div>
              <div>
                <span className="analysis-icon"><ScanIcon size={25} aria-hidden="true" /></span>
                <h3>Reading the pitch, names and badges.</h3>
                <p>Qwen vision is extracting visible evidence. The current player catalog will resolve names next. This usually takes 30–90 seconds on the local GPU.</p>
                <div className="analysis-checks">
                  <span className="is-complete">Image accepted</span>
                  <span className="is-active">Vision extraction</span>
                  <span>Squad legality</span>
                </div>
                <small className="analysis-leave-note">You can close this panel while it runs. Reopen Import team to continue the review.</small>
              </div>
            </div>
          ) : null}

          {step === 'review' && proposal ? (
            <div className="review-state">
              <div className="review-summary">
                <span className={`review-status ${valid ? 'is-valid' : 'is-invalid'}`}>
                  {valid ? <CheckCircleIcon size={18} weight="fill" /> : <WarningCircleIcon size={18} weight="fill" />}
                  {valid ? 'Legal squad found' : 'Review needed'}
                </span>
                <h3>{job.result?.resolved_players ?? 0}/15 players resolved</h3>
                <p>Formation {proposal.formation ?? 'unresolved'} · every value below came from the image and current catalog.</p>
              </div>
              <div className="resolved-list">
                {proposal.players.map((player) => (
                  <div key={`${player.squad_role}-${player.order}`}>
                    <span>{player.position ?? '—'}</span>
                    <strong>{player.source_text}</strong>
                    <small>{player.player_id ? `${Math.round(player.confidence * 100)}% match` : 'Unresolved'}</small>
                  </div>
                ))}
              </div>
              {job.result?.validation_issues.length || job.result?.parse_issues.length ? (
                <div className="validation-issues">
                  {[...(job.result?.parse_issues ?? []), ...(job.result?.validation_issues ?? [])].map((issue) => (
                    <p key={issue}><WarningCircleIcon size={15} weight="fill" />{issue}</p>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 'confirmed' ? (
            <div className="confirmed-state">
              <span><CheckCircleIcon size={32} weight="fill" aria-hidden="true" /></span>
              <h3>Your draft is now on the pitch.</h3>
              <p>It has become the active manager state, with a forecast-backed critique ready beside it. Add your FPL entry ID once and later gameweeks can sync through the manager connection instead of another screenshot.</p>
            </div>
          ) : null}

          {step === 'error' ? (
            <div className="import-error">
              <WarningCircleIcon size={24} weight="fill" aria-hidden="true" />
              <div><h3>Import paused</h3><p>{error}</p></div>
            </div>
          ) : null}

          {error && step !== 'error' ? <p className="inline-error">{error}</p> : null}

          <footer className="dialog-footer">
            <span>Nothing changes in your FPL account.</span>
            <div>
              {step === 'error' ? <button className="secondary-button" type="button" onClick={reset}>Try again</button> : null}
              {step === 'confirmed' ? (
                <>
                  <button className="secondary-button" type="button" onClick={() => { close(); onAddIdentity() }}>Add FPL entry ID</button>
                  <button className="primary-button" type="button" onClick={close}>Review critique <ArrowRightIcon size={16} /></button>
                </>
              ) : step === 'review' ? (
                <button className="primary-button" type="button" disabled={!valid} onClick={() => void confirm()}>
                  Confirm imported squad <ArrowRightIcon size={16} />
                </button>
              ) : (
                <button
                  className="primary-button"
                  type="button"
                  disabled={!file || step === 'uploading' || step === 'analysing'}
                  onClick={() => void beginAnalysis()}
                >
                  {step === 'uploading' ? 'Uploading…' : step === 'analysing' ? 'Analysing screenshot…' : 'Analyse screenshot'}
                  <ArrowRightIcon size={16} aria-hidden="true" />
                </button>
              )}
            </div>
          </footer>
        </div>
      </section>
    </div>
  )
}
