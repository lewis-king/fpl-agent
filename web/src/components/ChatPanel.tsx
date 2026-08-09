import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'

import {
  ArrowUpIcon,
  BrainIcon,
  CheckCircleIcon,
  CopyIcon,
  DatabaseIcon,
  WarningCircleIcon,
} from '@phosphor-icons/react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { ApiError, sendChat } from '../api'
import type { Workspace } from '../types'

interface Message {
  id: string
  role: 'assistant' | 'user'
  text: string
  receipts?: string[]
  tools?: string[]
  status?: 'sending' | 'error'
}

interface ChatPanelProps {
  workspace: Workspace
  focused: boolean
  onWorkspaceChanged: () => Promise<void>
}

function welcomeMessage(workspace: Workspace): Message {
  const allPlayers = [...workspace.squad.starters, ...workspace.squad.bench]
  const likelyAvailable = allPlayers.filter((player) => player.play_probability >= 0.85).length
  const captainContext = workspace.decision.captain.recommendation_aligned
    ? `${workspace.decision.captain.captain_name} is both the current and modelled captain.`
    : `Your current captain is ${workspace.decision.captain.current_captain_name}; the full-squad review currently prefers ${workspace.decision.captain.captain_name}.`
  const lineupContext = workspace.decision.captain.lineup_recommendation_aligned
    ? 'The current starting XI is also the strongest legal XI from this squad on the selected policy.'
    : `I would start ${workspace.decision.captain.promoted_player_names.join(', ')} and bench ${workspace.decision.captain.benched_player_names.join(', ')} before reviewing the armband.`
  return {
    id: `welcome-${workspace.squad.candidate_id}`,
    role: 'assistant',
    text: `I’ve audited all 15 players in this ${workspace.squad.formation}. ${likelyAvailable}/15 clear the current 85% appearance threshold. ${lineupContext} ${captainContext} Ask me to unpack the structure, any player, bench cover or the priority changes.`,
    receipts: [workspace.decision.captain.receipt_id],
    tools: ['manager state', 'captain comparison'],
  }
}

export function ChatPanel({ workspace, focused, onWorkspaceChanged }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>(() => [welcomeMessage(workspace)])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [serviceState, setServiceState] = useState<'unknown' | 'ready' | 'offline'>('unknown')
  const [copied, setCopied] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const candidateRef = useRef(workspace.squad.candidate_id)
  const preserveNextCandidateRef = useRef(false)
  const messageStreamRef = useRef<HTMLDivElement>(null)
  const streamEndRef = useRef<HTMLDivElement>(null)
  const copyTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const stream = messageStreamRef.current
    if (!stream) return
    stream.scrollTo({
      top: stream.scrollHeight,
      behavior: messages.length > 1 ? 'smooth' : 'auto',
    })
  }, [isSending, messages])

  useEffect(() => {
    if (candidateRef.current === workspace.squad.candidate_id) return
    candidateRef.current = workspace.squad.candidate_id
    if (preserveNextCandidateRef.current) {
      preserveNextCandidateRef.current = false
      return
    }
    abortRef.current?.abort()
    setMessages([welcomeMessage(workspace)])
    setSessionId(null)
    setInput('')
    setIsSending(false)
  }, [workspace])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
    }
  }, [])

  const statusLabel = useMemo(() => {
    if (serviceState === 'offline') return 'Sidecar offline'
    if (serviceState === 'ready') return 'Qwen ready'
    return 'Local model'
  }, [serviceState])
  const suggestions = useMemo(
    () => {
      if (workspace.phase.phase === 'preseason') {
        return [
          ...workspace.critique.suggested_questions.slice(0, 2),
          'Rebuild this squad with three Liverpool players.',
        ]
      }
      if (workspace.phase.phase === 'pre_deadline') {
        return [
          'Should I roll my transfer this gameweek?',
          'What is the strongest transfer bundle without a hit?',
          'Check my starting XI, captain and bench order.',
        ]
      }
      if (workspace.phase.phase === 'live_gameweek') {
        return [
          'How are my submitted decisions doing?',
          'What autosub or minutes risks remain?',
          'What should go on my next-gameweek watchlist?',
        ]
      }
      return [
        'Which decisions helped or hurt this gameweek?',
        'Where did the forecast miss?',
        'What should I prioritise before the next deadline?',
      ]
    },
    [workspace.critique.suggested_questions, workspace.phase.phase],
  )

  async function submit(messageText: string) {
    const text = messageText.trim()
    if (!text || isSending) return
    const userMessage: Message = { id: crypto.randomUUID(), role: 'user', text }
    setMessages((current) => [...current, userMessage])
    setInput('')
    setIsSending(true)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await sendChat(text, sessionId, controller.signal)
      setSessionId(result.session_id)
      setServiceState('ready')
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: result.response,
          receipts: result.receipt_ids,
          tools: result.tool_names,
        },
      ])
      if (result.tool_names.includes('optimize_squad')) {
        preserveNextCandidateRef.current = true
        await onWorkspaceChanged()
      }
    } catch (error) {
      if (controller.signal.aborted) return
      const message = error instanceof ApiError ? error.message : 'The local model request failed.'
      setServiceState(error instanceof ApiError && error.code === 'model_sidecar_offline' ? 'offline' : 'unknown')
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          status: 'error',
          text: message,
        },
      ])
    } finally {
      setIsSending(false)
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submit(input)
  }

  async function copyLatestAnswer() {
    const latest = [...messages].reverse().find((message) => message.role === 'assistant')
    if (!latest) return
    await navigator.clipboard.writeText(latest.text)
    setCopied(true)
    if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
    copyTimerRef.current = window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <section className={`chat-bezel ${focused ? 'is-focused' : ''}`} id="chat" aria-labelledby="chat-title">
      <div className="chat-panel">
        <header className="chat-header">
          <div className="chat-agent-mark">
            <BrainIcon size={19} weight="duotone" aria-hidden="true" />
          </div>
          <div>
            <h2 id="chat-title">Ask FPLAgent</h2>
            <span className={`model-status is-${serviceState}`}>
              <span aria-hidden="true" />
              {statusLabel}
            </span>
          </div>
          <button className="icon-button" type="button" aria-label="Copy latest answer" onClick={() => void copyLatestAnswer()}>
            {copied ? <CheckCircleIcon size={17} weight="fill" aria-hidden="true" /> : <CopyIcon size={17} aria-hidden="true" />}
          </button>
        </header>

        <div className="chat-context-line">
          <DatabaseIcon size={14} aria-hidden="true" />
          <span>Context: GW{workspace.phase.event} · {workspace.squad.candidate_id} · {workspace.squad.source.replaceAll('_', ' ')}</span>
        </div>

        <div className="message-stream" aria-live="polite" ref={messageStreamRef}>
          {messages.map((message) => (
            <article className={`message message-${message.role} ${message.status === 'error' ? 'is-error' : ''}`} key={message.id}>
              <div className="message-role">
                {message.role === 'assistant' ? (
                  message.status === 'error' ? (
                    <WarningCircleIcon size={15} weight="fill" aria-hidden="true" />
                  ) : (
                    <CheckCircleIcon size={15} weight="fill" aria-hidden="true" />
                  )
                ) : null}
                <span>{message.role === 'assistant' ? 'FPLAgent' : 'You'}</span>
              </div>
              {message.role === 'assistant' ? (
                <div className="message-copy">
                  <Markdown remarkPlugins={[remarkGfm]}>{message.text}</Markdown>
                </div>
              ) : (
                <p>{message.text}</p>
              )}
              {message.tools?.length ? (
                <div className="tool-disclosure">
                  {message.tools.map((tool) => (
                    <span key={tool}>{tool.replaceAll('_', ' ')}</span>
                  ))}
                </div>
              ) : null}
              {message.receipts?.map((receipt) => (
                <code className="receipt-chip" key={receipt}>{receipt}</code>
              ))}
            </article>
          ))}
          {isSending ? (
            <article className="message message-assistant is-thinking">
              <div className="message-role">
                <BrainIcon size={15} aria-hidden="true" />
                <span>Checking evidence</span>
              </div>
              <div className="thinking-lines" aria-label="FPLAgent is answering">
                <span />
                <span />
                <span />
              </div>
            </article>
          ) : null}
          <div ref={streamEndRef} />
        </div>

        <div className="prompt-suggestions" aria-label="Suggested questions">
          {suggestions.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => void submit(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>

        <form className="chat-composer" onSubmit={onSubmit}>
          <label htmlFor="chat-message">Ask about this squad</label>
          <div className="composer-control">
            <textarea
              id="chat-message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void submit(input)
                }
              }}
              placeholder="Compare two players, explain a pick, test a concern…"
              rows={2}
              maxLength={4000}
            />
            <button type="submit" disabled={!input.trim() || isSending} aria-label="Send message">
              <ArrowUpIcon size={18} weight="bold" aria-hidden="true" />
            </button>
          </div>
          <small>Current facts and decisions must come from tools. Press Shift + Enter for a new line.</small>
        </form>
      </div>
    </section>
  )
}
