import { useDeferredValue, useEffect, useEffectEvent, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  ChevronDown,
  Clock3,
  CloudSun,
  Command,
  DollarSign,
  Eye,
  EyeOff,
  History,
  KeyRound,
  LogOut,
  MessageSquarePlus,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  SendHorizontal,
  ShieldUser,
  Trash2,
  Type,
  UserRound,
  Users,
  Wrench,
  X,
} from 'lucide-react'
import './App.css'
import {
  ApiError,
  createThread,
  createTurn,
  createTurnStream,
  createUser,
  deleteThread,
  deleteUser,
  fetchMe,
  fetchThread,
  fetchThreads,
  fetchUsers,
  login,
  logout,
  StreamUnavailableError,
} from './api'
import { BrandMark } from './components/BrandMark'
import type {
  AuthUser,
  CreateUserPayload,
  ExecutionStep,
  StreamCompletedEvent,
  StreamRetryScheduledEvent,
  StreamRunStartedEvent,
  StreamTraceStepEvent,
  ThreadDetail,
  ThreadSummary,
  TurnResponse,
  UserSummary,
} from './types'

type SessionStatus = 'loading' | 'authenticated' | 'unauthenticated'
type AppRoute =
  | { kind: 'home' }
  | { kind: 'admin' }
  | { kind: 'thread'; threadId: string }
type BannerTone = 'error' | 'info'

type BannerState = {
  message: string
  tone: BannerTone
}

type LoginErrors = {
  username?: string
  password?: string
  form?: string
}

type CreateUserErrors = {
  username?: string
  password?: string
  form?: string
}

type PendingTurn = {
  execution_steps: ExecutionStep[]
  task_text: string
  timestamp: string
  tools_used: string[]
  trace_id: string
}

const MAX_COMPOSER_CHARACTERS = 250
const MAX_THREADS_PER_USER = 5
const MAX_TASK_FLOWS_PER_THREAD = 3
const ROLE_LIMITS = {
  admin: 1,
  user: 2,
} as const
const EXAMPLE_TASKS = [
  { label: 'Text task', prompt: 'Convert "task buddy" to uppercase', icon: Type },
  { label: 'Weather task', prompt: 'What is the weather in Toronto?', icon: CloudSun },
  { label: 'Finance task', prompt: 'Categorize Starbucks transaction 45 CAD and convert to USD', icon: DollarSign },
]
const LOGIN_HERO_TILES = [
  {
    title: 'Multi task',
    description: 'Run up to 2 subtasks.',
    icon: Wrench,
  },
  {
    title: 'Secure',
    description: 'Protected local sign in.',
    icon: ShieldUser,
  },
  {
    title: 'Trace output',
    description: 'Inspect each execution step.',
    icon: Command,
  },
  {
    title: 'Saved history',
    description: 'Review past task threads.',
    icon: History,
  },
]
const INPUT_ERROR_CODES = new Set([
  'EMPTY_INPUT',
  'INPUT_TOO_LONG',
  'TASK_TOO_COMPLEX',
  'THREAD_FLOW_LIMIT_REACHED',
  'THREAD_LIMIT_REACHED',
])
const SUBTASK_SPLIT_PATTERN = /\s+(?:and|then)\s+/i

function getCurrentRoute(): AppRoute {
  const path = window.location.pathname
  if (path.startsWith('/admin')) {
    return { kind: 'admin' }
  }
  const threadMatch = path.match(/^\/threads\/([^/]+)$/)
  if (threadMatch) {
    return { kind: 'thread', threadId: decodeURIComponent(threadMatch[1]) }
  }
  return { kind: 'home' }
}

function formatRoute(route: AppRoute) {
  if (route.kind === 'admin') {
    return '/admin'
  }
  if (route.kind === 'thread') {
    return `/threads/${encodeURIComponent(route.threadId)}`
  }
  return '/'
}

function sameRoute(left: AppRoute, right: AppRoute) {
  if (left.kind !== right.kind) {
    return false
  }
  if (left.kind === 'thread' && right.kind === 'thread') {
    return left.threadId === right.threadId
  }
  return true
}

function setRouteState(route: AppRoute, replace = false) {
  const currentRoute = getCurrentRoute()
  if (sameRoute(currentRoute, route)) {
    return
  }
  const nextPath = formatRoute(route)
  if (replace) {
    window.history.replaceState(null, '', nextPath)
    return
  }
  window.history.pushState(null, '', nextPath)
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatDateLabel(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatHistoryTimestamp(value: string) {
  const date = new Date(value)
  const now = new Date()

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
  }

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

function buildThreadSummary(detail: ThreadDetail): ThreadSummary {
  return {
    thread_id: detail.thread_id,
    title: detail.title,
    last_message_preview: detail.turns.at(-1)?.task_text ?? '',
    updated_at: detail.updated_at,
  }
}

function cleanThreadLabel(value: string) {
  const cleaned = value.replace(/\s+/g, ' ').trim()
  if (!cleaned) {
    return 'Untitled task'
  }
  return cleaned.length > 46 ? `${cleaned.slice(0, 43).trimEnd()}...` : cleaned
}

function cleanPreview(value: string) {
  const cleaned = value.replace(/\s+/g, ' ').trim()
  if (!cleaned) {
    return 'No requests yet'
  }
  return cleaned.length > 76 ? `${cleaned.slice(0, 73).trimEnd()}...` : cleaned
}

function groupThreads(threads: ThreadSummary[]) {
  const groups: Record<string, ThreadSummary[]> = {
    Today: [],
    Yesterday: [],
    Earlier: [],
  }
  const now = new Date()

  threads.forEach((thread) => {
    const updatedAt = new Date(thread.updated_at)
    const ageInDays = Math.floor((now.getTime() - updatedAt.getTime()) / (1000 * 60 * 60 * 24))

    if (ageInDays < 1 && now.toDateString() === updatedAt.toDateString()) {
      groups.Today.push(thread)
      return
    }
    if (ageInDays < 2) {
      groups.Yesterday.push(thread)
      return
    }
    groups.Earlier.push(thread)
  })

  return Object.entries(groups).filter(([, items]) => items.length > 0)
}

function toolLabel(toolName: string) {
  const labels: Record<string, string> = {
    TextProcessorTool: 'Text',
    WeatherMockTool: 'Weather',
    CalculatorTool: 'Calculator',
    CurrencyConverterTool: 'Currency',
    TransactionCategorizerTool: 'Categorization',
  }
  return labels[toolName] ?? toolName.replace(/Tool$/, '')
}

function phaseLabel(phase: string) {
  const labels: Record<string, string> = {
    validation: 'Validation',
    planning: 'Planning',
    tool_execution: 'Tool execution',
    response_assembly: 'Response assembly',
    response: 'Response assembly',
    safety: 'Validation',
  }
  return labels[phase] ?? phase
}

function turnStatusLabel(status: string) {
  if (status === 'partial') {
    return 'Partial result'
  }
  if (status === 'unsupported') {
    return 'Unsupported'
  }
  if (status === 'failed') {
    return 'Needs attention'
  }
  return 'Completed'
}

function turnStatusTone(status: string) {
  if (status === 'completed') {
    return 'success'
  }
  if (status === 'partial') {
    return 'warning'
  }
  return 'danger'
}

function roleLimitMessage(role: 'admin' | 'user') {
  return role === 'admin'
    ? 'TaskBuddy supports only 1 admin account.'
    : 'TaskBuddy supports up to 2 standard user accounts.'
}

function threadLimitMessage() {
  return `TaskBuddy supports up to ${MAX_THREADS_PER_USER} chat threads per user. Delete an existing chat to create another one.`
}

function threadFlowLimitMessage() {
  return `Each chat supports up to ${MAX_TASK_FLOWS_PER_THREAD} task flows. Start a new chat or delete an old one to continue.`
}

function summarizeStructuredOutput(output: Record<string, unknown>) {
  const results = output.results
  if (Array.isArray(results)) {
    return `${results.length} tool result${results.length === 1 ? '' : 's'} returned in the execution payload.`
  }
  const issue = output.issue
  if (issue && typeof issue === 'object') {
    const issueRecord = issue as Record<string, unknown>
    return typeof issueRecord.message === 'string'
      ? issueRecord.message
      : 'Execution details are available in the structured payload.'
  }
  if (typeof output.city === 'string' && typeof output.condition === 'string') {
    return `Weather data returned for ${output.city}.`
  }
  if (typeof output.category === 'string') {
    return `Transaction classified as ${output.category}.`
  }
  if (typeof output.converted_amount === 'number' && typeof output.to_currency === 'string') {
    return `Converted amount returned in ${output.to_currency}.`
  }
  if (output.result !== undefined) {
    return 'A direct result value is included in the payload.'
  }
  return 'Structured data is available for inspection.'
}

function getSuggestions(output: Record<string, unknown>) {
  const issue = output.issue
  if (!issue || typeof issue !== 'object') {
    return []
  }
  const suggestions = (issue as Record<string, unknown>).suggestions
  if (!Array.isArray(suggestions)) {
    return []
  }
  return suggestions.filter((item): item is string => typeof item === 'string')
}

function mergePendingToolLabels(currentTools: string[], nextStep: ExecutionStep) {
  const nextTools = [...currentTools]

  const planningTools = nextStep.phase === 'planning' && Array.isArray(nextStep.payload?.tools_used)
    ? nextStep.payload.tools_used.filter((tool): tool is string => typeof tool === 'string')
    : []

  for (const tool of planningTools) {
    if (!nextTools.includes(tool)) {
      nextTools.push(tool)
    }
  }

  if (nextStep.tool_name) {
    const label = toolLabel(nextStep.tool_name)
    if (!nextTools.includes(label)) {
      nextTools.push(label)
    }
  }

  return nextTools
}

function getSubtaskCount(value: string) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (!normalized) {
    return 0
  }
  return normalized.split(SUBTASK_SPLIT_PATTERN).filter(Boolean).length
}

function getComposerValidation(value: string) {
  const trimmed = value.trim()
  if (!trimmed) {
    return ''
  }
  if (value.length > MAX_COMPOSER_CHARACTERS) {
    return `Use ${MAX_COMPOSER_CHARACTERS} characters or fewer.`
  }
  if (getSubtaskCount(value) > 2) {
    return 'Use up to 2 subtasks in a single request.'
  }
  return ''
}

function getPasswordValidation(password: string) {
  if (password.length < 6) {
    return 'Use at least 6 characters.'
  }
  if (!/[A-Z]/.test(password)) {
    return 'Include at least 1 uppercase letter.'
  }
  if (!/\d/.test(password)) {
    return 'Include at least 1 number.'
  }
  return ''
}

function isInputError(error: ApiError) {
  return INPUT_ERROR_CODES.has(error.code)
}

function InlineMessage({ message }: { message: string }) {
  return (
    <p className="inline-message" role="alert">
      <AlertCircle size={14} />
      <span>{message}</span>
    </p>
  )
}

function PageBanner({ banner, onDismiss }: { banner: BannerState; onDismiss: () => void }) {
  return (
    <div className={`page-banner page-banner--${banner.tone}`} role="alert">
      <span>{banner.message}</span>
      <button type="button" onClick={onDismiss} aria-label="Dismiss system notice">
        <X size={15} />
      </button>
    </div>
  )
}

function TraceList({ steps, turnId }: { steps: ExecutionStep[]; turnId: string }) {
  return (
    <div className="trace-list">
      {steps.map((step) => (
        <div key={`${turnId}-${step.step_number}`} className="trace-step">
          <div className="trace-step__badge">{String(step.step_number).padStart(2, '0')}</div>
          <div className="trace-step__content">
            <div className="trace-step__header">
              <strong>{phaseLabel(step.phase)}</strong>
            </div>
            {step.tool_name ? <span className="trace-step__tool">{toolLabel(step.tool_name)}</span> : null}
            <p>{step.message}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function StructuredOutputSection({ turn }: { turn: TurnResponse }) {
  const suggestions = getSuggestions(turn.output_data)
  const showSummary = turn.status !== 'completed' || suggestions.length > 0

  return (
    <section className="structured-output">
      {showSummary ? <p className="structured-output__summary">{summarizeStructuredOutput(turn.output_data)}</p> : null}
      {suggestions.length > 0 ? (
        <div className="structured-output__suggestions">
          {suggestions.map((suggestion) => (
            <span key={suggestion}>{suggestion}</span>
          ))}
        </div>
      ) : null}
      <pre>{JSON.stringify(turn.output_data, null, 2)}</pre>
    </section>
  )
}

function TurnCard({ turn }: { turn: TurnResponse }) {
  const tools = turn.tools_used.map(toolLabel)
  const tone = turnStatusTone(turn.status)
  const isMultilineOutput = turn.final_output.includes('\n')

  return (
    <div className="turn-group">
      <div className="turn-request">
        <div className="message message--user">
          <p>{turn.task_text}</p>
        </div>
        <time className="message__timestamp">{formatTimestamp(turn.timestamp)}</time>
      </div>

      <article className={`assistant-card assistant-card--${tone}`}>
        <div className="assistant-card__eyebrow">
          <span>TaskBuddy</span>
          {turn.status !== 'completed' ? <span className={`status-pill status-pill--${tone}`}>{turnStatusLabel(turn.status)}</span> : null}
        </div>

        <div className="assistant-card__output">
          <p className="section-label">Final output</p>
          <h2 className={`assistant-card__output-value ${isMultilineOutput ? 'assistant-card__output-value--multiline' : ''}`}>
            {turn.final_output}
          </h2>
        </div>

        <div className="assistant-card__meta">
          <div className="assistant-card__meta-group">
            <div className="assistant-card__meta-label">
              <Wrench size={14} />
              <span>Tools used</span>
            </div>
            <div className="tool-chip-row">
              {tools.length > 0
                ? tools.map((tool) => (
                    <span key={tool} className="tool-chip">
                      {tool}
                    </span>
                  ))
                : <span className="tool-chip tool-chip--muted">No tool matched</span>}
            </div>
          </div>

          <div className="assistant-card__timestamp">
            <Clock3 size={14} />
            <time>{formatTimestamp(turn.timestamp)}</time>
          </div>
        </div>

        <details className="detail-card">
          <summary>
            <span className="detail-summary__label">
              <History size={14} />
              <span>Execution trace</span>
            </span>
            <ChevronDown size={14} />
          </summary>
          <TraceList steps={turn.execution_steps} turnId={turn.turn_id} />
        </details>

        <details className="detail-card">
          <summary>
            <span className="detail-summary__label">
              <Command size={14} />
              <span>Structured output</span>
            </span>
            <ChevronDown size={14} />
          </summary>
          <StructuredOutputSection turn={turn} />
        </details>
      </article>
    </div>
  )
}

function PendingTurnCard({ pendingTurn }: { pendingTurn: PendingTurn }) {
  return (
    <div className="turn-group">
      <div className="turn-request">
        <div className="message message--user">
          <p>{pendingTurn.task_text}</p>
        </div>
        <time className="message__timestamp">{formatTimestamp(pendingTurn.timestamp)}</time>
      </div>

      <article className="assistant-card assistant-card--pending">
        <div className="assistant-card__eyebrow">
          <span>TaskBuddy</span>
          <span className="status-pill status-pill--soft">Running</span>
        </div>

        <div className="assistant-card__output">
          <p className="section-label">Processing</p>
          <h2 className="assistant-card__output-value">Executing tools and assembling trace details.</h2>
        </div>

        <div className="assistant-card__meta">
          <div className="assistant-card__meta-group">
            <div className="assistant-card__meta-label">
              <Wrench size={14} />
              <span>Tools used</span>
            </div>
            <div className="tool-chip-row">
              {pendingTurn.tools_used.length > 0
                ? pendingTurn.tools_used.map((tool) => (
                    <span key={tool} className="tool-chip">
                      {tool}
                    </span>
                  ))
                : <span className="tool-chip tool-chip--muted">Planning in progress</span>}
            </div>
          </div>

          <div className="assistant-card__timestamp">
            <Clock3 size={14} />
            <time>{formatTimestamp(pendingTurn.timestamp)}</time>
          </div>
        </div>

        <details className="detail-card" open>
          <summary>
            <span className="detail-summary__label">
              <History size={14} />
              <span>Execution trace</span>
            </span>
            <ChevronDown size={14} />
          </summary>
          {pendingTurn.execution_steps.length > 0 ? (
            <TraceList steps={pendingTurn.execution_steps} turnId={pendingTurn.trace_id || 'pending'} />
          ) : (
            <div className="trace-list trace-list--placeholder">
              <p>Awaiting execution steps...</p>
            </div>
          )}
        </details>
      </article>
    </div>
  )
}

function Sidebar({
  currentUser,
  groupedThreads,
  isCollapsed,
  isLoadingThreads,
  isThreadLimitReached,
  route,
  searchValue,
  threadCount,
  onDeleteThread,
  onLogout,
  onNavigate,
  onNewChat,
  onSearchChange,
  onSelectThread,
  onToggleCollapse,
}: {
  currentUser: AuthUser | null
  groupedThreads: Array<[string, ThreadSummary[]]>
  isCollapsed: boolean
  isLoadingThreads: boolean
  isThreadLimitReached: boolean
  route: AppRoute
  searchValue: string
  threadCount: number
  onDeleteThread: (threadId: string, title: string) => void
  onLogout: () => void
  onNavigate: (route: AppRoute) => void
  onNewChat: () => void
  onSearchChange: (value: string) => void
  onSelectThread: (threadId: string) => void
  onToggleCollapse: () => void
}) {
  return (
    <div className={`sidebar-shell ${isCollapsed ? 'sidebar-shell--collapsed' : ''}`}>
      <aside className="sidebar-rail">
        <div className="rail-stack">
          <button
            type="button"
            className="rail-button rail-button--toggle"
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? 'Expand history panel' : 'Collapse history panel'}
            title={isCollapsed ? 'Expand history panel' : 'Collapse history panel'}
          >
            {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>

          <button
            type="button"
            className={`rail-button ${route.kind !== 'admin' ? 'rail-button--active' : ''}`}
            onClick={() => onNavigate({ kind: 'home' })}
            aria-label="Workspace"
            title="Workspace"
          >
            <MessagesSquare size={18} />
          </button>

          {currentUser?.role === 'admin' ? (
            <button
              type="button"
              className={`rail-button ${route.kind === 'admin' ? 'rail-button--active' : ''}`}
              onClick={() => onNavigate({ kind: 'admin' })}
              aria-label="Admin"
              title="Admin"
            >
              <ShieldUser size={18} />
            </button>
          ) : null}
        </div>

        <div className="rail-stack rail-stack--footer">
          <button
            type="button"
            className="rail-button rail-button--avatar"
            aria-label={currentUser?.username ? `Account ${currentUser.username}` : 'Account'}
            title={currentUser?.username}
          >
            <UserRound size={18} />
          </button>

          <button type="button" className="rail-button" onClick={onLogout} aria-label="Sign out" title="Sign out">
            <LogOut size={18} />
          </button>
        </div>
      </aside>

      {!isCollapsed ? (
        <aside className="thread-panel">
          <div className="thread-panel__header">
            <div className="thread-panel__brand">
              <BrandMark size="sm" />
              <div className="brand-copy brand-copy--compact">
                <strong>TaskBuddy</strong>
                <span>Multi Task studio</span>
              </div>
            </div>

            <button type="button" className="panel-action" onClick={onNewChat} disabled={isThreadLimitReached}>
              <MessageSquarePlus size={16} />
              <span>Start new chat</span>
            </button>

            <p className={`sidebar-note ${isThreadLimitReached ? 'sidebar-note--limit' : ''}`}>
              {isThreadLimitReached ? threadLimitMessage() : `${threadCount} / ${MAX_THREADS_PER_USER} chats used`}
            </p>

            <label className="search-field">
              <Search size={15} />
              <input
                value={searchValue}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder="Search chat threads"
              />
            </label>
          </div>

          <div className="thread-panel__content">
            {isLoadingThreads ? <p className="sidebar-note">Refreshing history...</p> : null}
            {groupedThreads.length === 0 ? <p className="sidebar-note">No saved requests yet.</p> : null}

            {groupedThreads.map(([label, items]) => (
              <section key={label} className="thread-group">
                <div className="thread-group__header">
                  <h2>{label}</h2>
                </div>

                <div className="thread-group__list">
                  {items.map((thread) => (
                    <article
                      key={thread.thread_id}
                      className={`thread-item ${route.kind === 'thread' && route.threadId === thread.thread_id ? 'thread-item--active' : ''}`}
                    >
                      <button type="button" className="thread-item__main" onClick={() => onSelectThread(thread.thread_id)}>
                        <div className="thread-item__topline">
                          <span className="thread-item__title">{cleanThreadLabel(thread.title)}</span>
                          <span className="thread-item__time">
                            <Clock3 size={11} />
                            <span>{formatHistoryTimestamp(thread.updated_at)}</span>
                          </span>
                        </div>
                        <span className="thread-item__preview">{cleanPreview(thread.last_message_preview)}</span>
                      </button>
                      <button
                        type="button"
                        className="thread-item__delete"
                        onClick={() => onDeleteThread(thread.thread_id, thread.title)}
                        aria-label={`Delete thread ${thread.title}`}
                        title="Delete thread"
                      >
                        <Trash2 size={14} />
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <div className="thread-panel__footer">
            <div className="account-card">
              <div className="account-card__header">
                <UserRound size={16} />
                <span>{currentUser?.username}</span>
              </div>
              <span className="account-card__meta">{currentUser?.role}</span>
            </div>
          </div>
        </aside>
      ) : null}
    </div>
  )
}

function WorkspaceView({
  composerError,
  composerDisabledReason,
  composerValue,
  isSubmitting,
  onComposerChange,
  onExampleSelect,
  onSubmit,
  pendingTurn,
  selectedThread,
}: {
  composerError: string
  composerDisabledReason: string
  composerValue: string
  isSubmitting: boolean
  onComposerChange: (value: string) => void
  onExampleSelect: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  pendingTurn: PendingTurn | null
  selectedThread: ThreadDetail | null
}) {
  const hasTurns = Boolean(selectedThread?.turns.length || pendingTurn)
  const turns = selectedThread?.turns ?? []
  const remainingCharacters = MAX_COMPOSER_CHARACTERS - composerValue.length
  const composerValidation = getComposerValidation(composerValue)
  const visibleComposerError = composerDisabledReason || composerError || composerValidation
  const helperMetaText =
    remainingCharacters >= 0
      ? `${remainingCharacters} characters left \u2022 Up to 2 subtasks`
      : `${Math.abs(remainingCharacters)} characters over limit \u2022 Up to 2 subtasks`
  /* Legacy helper text fallback removed.
    remainingCharacters >= 0
      ? `${remainingCharacters} characters left • Up to 2 subtasks`
      : `${Math.abs(remainingCharacters)} characters over limit • Up to 2 subtasks`

  helperText = helperText.replace('â€¢', '\u2022')

  */

  return (
    <section className="page-shell page-shell--workspace">
      <div className="workspace-stage">
        <div className="workspace-scroll">
          {hasTurns ? (
            <div className="turn-stack">
              {turns.map((turn) => (
                <TurnCard key={turn.turn_id} turn={turn} />
              ))}
              {pendingTurn ? <PendingTurnCard pendingTurn={pendingTurn} /> : null}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state__logo">
                <BrandMark size="lg" />
              </div>
              <span className="empty-state__eyebrow">Multi Task studio for your workflows.</span>
              <h1>TaskBuddy</h1>
              <p>Run tasks, inspect trace steps, and review saved chats.</p>

              <div className="example-grid">
                {EXAMPLE_TASKS.map((example) => {
                  const ExampleIcon = example.icon

                  return (
                    <button key={example.prompt} type="button" className="example-card" onClick={() => onExampleSelect(example.prompt)}>
                      <div className="example-card__icon">
                        <ExampleIcon size={18} />
                      </div>
                      <span className="example-card__label">{example.label}</span>
                      <p>{example.prompt}</p>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <form className={`composer ${hasTurns ? 'composer--thread' : 'composer--home'} ${visibleComposerError ? 'composer--error' : ''}`} onSubmit={onSubmit}>
          <div className="composer__input">
            <textarea
              value={composerValue}
              onChange={(event) => onComposerChange(event.target.value)}
              placeholder="Ask TaskBuddy to run up to 2 supported subtasks."
              rows={3}
              aria-invalid={Boolean(visibleComposerError)}
              disabled={Boolean(composerDisabledReason)}
            />
          </div>

          <div className="composer__footer">
            <div className="composer__meta">
              <span>{helperMetaText}</span>
              {visibleComposerError ? <InlineMessage message={visibleComposerError} /> : null}
            </div>

            <button
              type="submit"
              className="send-button"
              disabled={isSubmitting || !composerValue.trim() || Boolean(composerValidation) || Boolean(composerDisabledReason)}
              aria-label={isSubmitting ? 'Running task' : 'Run task'}
            >
              <SendHorizontal size={16} />
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}

function LoginView({
  errors,
  isAuthenticating,
  loginPassword,
  loginUsername,
  onPasswordChange,
  onSubmit,
  onUsernameChange,
}: {
  errors: LoginErrors
  isAuthenticating: boolean
  loginPassword: string
  loginUsername: string
  onPasswordChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onUsernameChange: (value: string) => void
}) {
  return (
    <div className="screen screen--login">
      <div className="login-shell">
        <section className="login-panel login-panel--hero">
          <div className="login-hero">
            <div className="login-hero__glow login-hero__glow--one" />
            <div className="login-hero__glow login-hero__glow--two" />

            <div className="brand-lockup brand-lockup--hero">
              <BrandMark size="lg" />
              <div className="brand-copy brand-copy--hero">
                <h1>TaskBuddy</h1>
                <p>Multi Task studio for your workflows.</p>
              </div>
            </div>

            <p className="login-hero__copy">Sign in to run tasks, inspect trace steps, and review saved chats.</p>

            <div className="login-feature-grid">
              {LOGIN_HERO_TILES.map((tile) => {
                const TileIcon = tile.icon

                return (
                  <article key={tile.title} className="login-feature-card">
                    <div className="login-feature-card__icon">
                      <TileIcon size={16} />
                    </div>
                    <strong>{tile.title}</strong>
                    <p>{tile.description}</p>
                  </article>
                )
              })}
            </div>
          </div>
        </section>

        <section className="login-panel login-panel--form">
          <div className="login-access-chip" aria-hidden="true" />
          <div className="login-panel__brand-row">
            <div className="brand-lockup">
              <BrandMark size="sm" />
              <div className="brand-copy brand-copy--compact">
                <strong>TaskBuddy</strong>
                <span>Multi Task studio for your workflows.</span>
              </div>
            </div>
            <span className="toolbar-chip toolbar-chip--soft">Secure</span>
          </div>

          <div className="login-panel__header">
            <h2>Welcome back</h2>
            <p>Sign in to continue into your workspace.</p>
          </div>

          <form className="login-form" onSubmit={onSubmit}>
            <label>
              <span>Username</span>
              <input value={loginUsername} onChange={(event) => onUsernameChange(event.target.value)} placeholder="Enter username" />
              {errors.username ? <InlineMessage message={errors.username} /> : null}
            </label>

            <label>
              <span>Password</span>
              <input
                type="password"
                value={loginPassword}
                onChange={(event) => onPasswordChange(event.target.value)}
                placeholder="Enter password"
              />
              {errors.password ? <InlineMessage message={errors.password} /> : null}
            </label>

            {errors.form ? <InlineMessage message={errors.form} /> : null}

            <button type="submit" className="primary-button" disabled={isAuthenticating}>
              {isAuthenticating ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}

function AdminView({
  currentUser,
  form,
  formErrors,
  isCreatingUser,
  isDeletingUser,
  isLoadingUsers,
  notice,
  onBack,
  onCreateUser,
  onDeleteUser,
  onFormChange,
  onTogglePasswordVisibility,
  passwordVisibility,
  sessionPasswords,
  users,
}: {
  currentUser: AuthUser
  form: CreateUserPayload
  formErrors: CreateUserErrors
  isCreatingUser: boolean
  isDeletingUser: string | null
  isLoadingUsers: boolean
  notice: string
  onBack: () => void
  onCreateUser: (event: FormEvent<HTMLFormElement>) => void
  onDeleteUser: (user: UserSummary) => void
  onFormChange: (next: CreateUserPayload) => void
  onTogglePasswordVisibility: (userId: string) => void
  passwordVisibility: Record<string, boolean>
  sessionPasswords: Record<string, string>
  users: UserSummary[]
}) {
  const adminCount = users.filter((user) => user.role === 'admin').length
  const standardUserCount = users.filter((user) => user.role === 'user').length
  const isSelectedRoleFull = form.role === 'admin' ? adminCount >= ROLE_LIMITS.admin : standardUserCount >= ROLE_LIMITS.user
  const selectedRoleNotice = isSelectedRoleFull
    ? `${roleLimitMessage(form.role)} Delete an existing ${form.role === 'admin' ? 'admin' : 'user'} to free a slot.`
    : roleLimitMessage(form.role)

  return (
    <section className="page-shell page-shell--admin">
      <header className="page-header page-header--split">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>Admin - User Management</h1>
          <p className="page-copy">Manage local users and roles for TaskBuddy.</p>
        </div>

        <div className="page-header__actions">
          <span className="toolbar-chip toolbar-chip--soft">
            <Users size={14} />
            <span>{users.length} users</span>
          </span>
          <button type="button" className="secondary-button" onClick={onBack}>
            <ArrowLeft size={16} />
            <span>Back to workspace</span>
          </button>
        </div>
      </header>

      <div className="admin-layout">
        <section className="admin-card admin-card--form">
          <div className="admin-card__header">
            <KeyRound size={18} />
            <div>
              <h2>Create user</h2>
              <p>Add a local account for this workspace.</p>
            </div>
          </div>

          <div className="admin-capacity">
            <span className="toolbar-chip toolbar-chip--soft">
              <ShieldUser size={14} />
              <span>{adminCount} / {ROLE_LIMITS.admin} admin</span>
            </span>
            <span className="toolbar-chip toolbar-chip--soft">
              <Users size={14} />
              <span>{standardUserCount} / {ROLE_LIMITS.user} users</span>
            </span>
          </div>

          <form className="admin-form admin-form--inline" onSubmit={onCreateUser}>
            <label>
              <span>Username</span>
              <input
                value={form.username}
                onChange={(event) => onFormChange({ ...form, username: event.target.value })}
                placeholder="Enter username"
              />
              {formErrors.username ? <InlineMessage message={formErrors.username} /> : null}
            </label>

            <label>
              <span>Password</span>
              <input
                type="password"
                value={form.password}
                onChange={(event) => onFormChange({ ...form, password: event.target.value })}
                placeholder="Enter password"
              />
              <small>Minimum 6 characters, with at least 1 uppercase letter and 1 number.</small>
              {formErrors.password ? <InlineMessage message={formErrors.password} /> : null}
            </label>

            <label>
              <span>Role</span>
              <select
                value={form.role}
                onChange={(event) => onFormChange({ ...form, role: event.target.value as 'admin' | 'user' })}
              >
                <option value="admin">admin (1 max)</option>
                <option value="user">user (2 max)</option>
              </select>
            </label>

            <div className="admin-form__actions">
              {formErrors.form ? <InlineMessage message={formErrors.form} /> : null}
              <p className="admin-notice">{notice || selectedRoleNotice}</p>

              <button type="submit" className="primary-button" disabled={isCreatingUser || isSelectedRoleFull}>
                {isCreatingUser ? 'Creating user...' : 'Create user'}
              </button>
            </div>
          </form>
        </section>

        <section className="admin-card admin-card--table">
          <div className="admin-card__header">
            <Users size={18} />
            <div>
              <h2>Local users</h2>
              <p>Manage local access accounts. Passwords are only visible for users created in this admin session.</p>
            </div>
          </div>

          {isLoadingUsers ? (
            <p className="sidebar-note">Loading users...</p>
          ) : (
            <div className="table-shell">
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Password</th>
                    <th>Status</th>
                    <th>Created at</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const isCurrentUser = currentUser.user_id === user.user_id
                    const availablePassword = sessionPasswords[user.user_id]
                    const isPasswordVisible = Boolean(passwordVisibility[user.user_id])
                    const maskedPassword = availablePassword ? '*'.repeat(availablePassword.length) : 'Unavailable'

                    return (
                      <tr key={user.user_id}>
                        <td>{user.username}</td>
                        <td>{user.role}</td>
                        <td>
                          <div className="password-cell">
                            <span>{availablePassword ? (isPasswordVisible ? availablePassword : maskedPassword) : 'Unavailable'}</span>
                            {availablePassword ? (
                              <button
                                type="button"
                                className="table-action table-action--icon"
                                onClick={() => onTogglePasswordVisibility(user.user_id)}
                                aria-label={`${isPasswordVisible ? 'Hide' : 'Show'} password for ${user.username}`}
                              >
                                {isPasswordVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                              </button>
                            ) : (
                              <span className="password-cell__hint">session only</span>
                            )}
                          </div>
                        </td>
                        <td>Active</td>
                        <td>{formatDateLabel(user.created_at)}</td>
                        <td>
                          <button
                            type="button"
                            className="table-action"
                            onClick={() => onDeleteUser(user)}
                            disabled={isCurrentUser || isDeletingUser === user.user_id}
                            aria-label={isCurrentUser ? `Current session ${user.username}` : `Delete ${user.username}`}
                          >
                            {isCurrentUser ? (
                              <>
                                <UserRound size={14} />
                                <span>Current session</span>
                              </>
                            ) : (
                              <>
                                <Trash2 size={14} />
                                <span>{isDeletingUser === user.user_id ? 'Removing...' : 'Delete'}</span>
                              </>
                            )}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </section>
  )
}

function App() {
  const [route, setRoute] = useState<AppRoute>(getCurrentRoute())
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('loading')
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [systemBanner, setSystemBanner] = useState<BannerState | null>(null)
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [totalThreadCount, setTotalThreadCount] = useState(0)
  const [selectedThread, setSelectedThread] = useState<ThreadDetail | null>(null)
  const [searchValue, setSearchValue] = useState('')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const deferredSearch = useDeferredValue(searchValue)
  const [composerValue, setComposerValue] = useState('')
  const [composerError, setComposerError] = useState('')
  const [pendingTurn, setPendingTurn] = useState<PendingTurn | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isLoadingThreads, setIsLoadingThreads] = useState(false)
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginErrors, setLoginErrors] = useState<LoginErrors>({})
  const [isAuthenticating, setIsAuthenticating] = useState(false)
  const [users, setUsers] = useState<UserSummary[]>([])
  const [isLoadingUsers, setIsLoadingUsers] = useState(false)
  const [createUserForm, setCreateUserForm] = useState<CreateUserPayload>({
    username: '',
    password: '',
    role: 'user',
  })
  const [createUserErrors, setCreateUserErrors] = useState<CreateUserErrors>({})
  const [adminNotice, setAdminNotice] = useState('')
  const [isCreatingUser, setIsCreatingUser] = useState(false)
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null)
  const [sessionPasswords, setSessionPasswords] = useState<Record<string, string>>({})
  const [passwordVisibility, setPasswordVisibility] = useState<Record<string, boolean>>({})

  const groupedThreads = useMemo(() => groupThreads(threads), [threads])
  const isThreadLimitReached = totalThreadCount >= MAX_THREADS_PER_USER
  const composerDisabledReason = selectedThread && selectedThread.turns.length >= MAX_TASK_FLOWS_PER_THREAD
    ? threadFlowLimitMessage()
    : ''

  const initializeSessionEffect = useEffectEvent(() => {
    void initializeSession()
  })

  const refreshThreadsEffect = useEffectEvent(() => {
    void loadThreads(deferredSearch)
  })

  const loadRouteThreadEffect = useEffectEvent((threadId: string) => {
    void loadRouteThread(threadId)
  })

  const refreshUsersEffect = useEffectEvent(() => {
    void loadUsers()
  })

  useEffect(() => {
    document.title = route.kind === 'admin' ? 'TaskBuddy Admin' : 'TaskBuddy'
  }, [route.kind])

  useEffect(() => {
    const handlePopState = () => {
      setRoute(getCurrentRoute())
    }

    window.addEventListener('popstate', handlePopState)
    initializeSessionEffect()

    return () => {
      window.removeEventListener('popstate', handlePopState)
    }
  }, [])

  useEffect(() => {
    if (sessionStatus !== 'authenticated' || !currentUser) {
      return
    }
    refreshThreadsEffect()
  }, [sessionStatus, currentUser?.user_id, deferredSearch])

  useEffect(() => {
    if (sessionStatus !== 'authenticated' || route.kind !== 'thread') {
      return
    }
    if (selectedThread?.thread_id === route.threadId) {
      return
    }
    loadRouteThreadEffect(route.threadId)
  }, [sessionStatus, route, selectedThread?.thread_id])

  useEffect(() => {
    if (route.kind !== 'thread' && selectedThread) {
      setSelectedThread(null)
    }
  }, [route.kind, selectedThread])

  useEffect(() => {
    if (sessionStatus !== 'authenticated' || route.kind !== 'admin' || currentUser?.role !== 'admin') {
      return
    }
    refreshUsersEffect()
  }, [sessionStatus, route.kind, currentUser?.role])

  useEffect(() => {
    if (sessionStatus !== 'authenticated' || route.kind !== 'admin' || currentUser?.role === 'admin') {
      return
    }
    navigate({ kind: 'home' })
    setSystemBanner({ message: 'Administrator access is required to open the admin page.', tone: 'info' })
  }, [sessionStatus, currentUser?.role, route.kind])

  function navigate(nextRoute: AppRoute, replace = false) {
    setRouteState(nextRoute, replace)
    setRoute(nextRoute)
  }

  function resetSession() {
    setSessionStatus('unauthenticated')
    setCurrentUser(null)
    setThreads([])
    setTotalThreadCount(0)
    setSelectedThread(null)
    setPendingTurn(null)
    setIsSidebarCollapsed(false)
    setUsers([])
    setComposerValue('')
    setComposerError('')
    setCreateUserErrors({})
    setAdminNotice('')
    setSessionPasswords({})
    setPasswordVisibility({})
  }

  async function initializeSession() {
    setSystemBanner(null)
    try {
      const me = await fetchMe()
      setCurrentUser(me)
      setSessionStatus('authenticated')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setSessionStatus('unauthenticated')
        return
      }
      setSessionStatus('unauthenticated')
      setSystemBanner({ message: error instanceof Error ? error.message : 'Unable to load TaskBuddy.', tone: 'error' })
    }
  }

  async function loadThreads(search = '') {
    if (!currentUser) {
      return
    }

    setIsLoadingThreads(true)
    try {
      const items = await fetchThreads(search)
      setThreads(items)
      if (!search) {
        setTotalThreadCount(items.length)
      }
    } catch (error) {
      handleSystemError(error, 'Unable to load task history.')
    } finally {
      setIsLoadingThreads(false)
    }
  }

  async function loadRouteThread(threadId: string) {
    try {
      const detail = await fetchThread(threadId)
      setSelectedThread(detail)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setSelectedThread(null)
        navigate({ kind: 'home' }, true)
        setSystemBanner({ message: 'The requested chat could not be found.', tone: 'info' })
        await loadThreads(deferredSearch)
        return
      }
      handleSystemError(error, 'Unable to load this chat.')
    }
  }

  async function loadUsers() {
    if (currentUser?.role !== 'admin') {
      return
    }

    setIsLoadingUsers(true)
    setCreateUserErrors({})
    try {
      const items = await fetchUsers()
      setUsers(items)
    } catch (error) {
      handleSystemError(error, 'Unable to load local users.')
    } finally {
      setIsLoadingUsers(false)
    }
  }

  function handleSystemError(error: unknown, fallbackMessage: string) {
    if (error instanceof ApiError && error.status === 401) {
      resetSession()
      return
    }
    setSystemBanner({ message: error instanceof Error ? error.message : fallbackMessage, tone: 'error' })
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const errors: LoginErrors = {}
    if (!loginUsername.trim()) {
      errors.username = 'Enter a username.'
    }
    if (!loginPassword) {
      errors.password = 'Enter a password.'
    }
    if (errors.username || errors.password) {
      setLoginErrors(errors)
      return
    }

    setLoginErrors({})
    setSystemBanner(null)
    setIsAuthenticating(true)
    try {
      const me = await login({ username: loginUsername.trim(), password: loginPassword })
      setCurrentUser(me)
      setSessionStatus('authenticated')
      if (route.kind === 'admin' && me.role !== 'admin') {
        navigate({ kind: 'home' }, true)
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setLoginErrors({ form: error.message })
      } else {
        handleSystemError(error, 'Unable to sign in.')
      }
    } finally {
      setIsAuthenticating(false)
    }
  }

  async function handleLogout() {
    try {
      await logout()
    } finally {
      resetSession()
      navigate({ kind: 'home' }, true)
    }
  }

  async function handleNewChat() {
    setComposerError('')
    setSystemBanner(null)
    if (isThreadLimitReached) {
      setSystemBanner({ message: threadLimitMessage(), tone: 'info' })
      return
    }
    try {
      const detail = await createThread()
      setSelectedThread(detail)
      setTotalThreadCount((current) => current + 1)
      setThreads((current) => [buildThreadSummary(detail), ...current.filter((item) => item.thread_id !== detail.thread_id)])
      setComposerValue('')
      navigate({ kind: 'thread', threadId: detail.thread_id })
    } catch (error) {
      handleSystemError(error, 'Unable to create a new chat.')
    }
  }

  async function handleSelectThread(threadId: string) {
    setSystemBanner(null)
    navigate({ kind: 'thread', threadId })
    try {
      const detail = await fetchThread(threadId)
      setSelectedThread(detail)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        navigate({ kind: 'home' }, true)
        setSystemBanner({ message: 'The requested chat could not be found.', tone: 'info' })
      } else {
        handleSystemError(error, 'Unable to load this chat.')
      }
    }
  }

  async function handleDeleteThread(threadId: string, title: string) {
    if (!window.confirm(`Delete "${cleanThreadLabel(title)}"?`)) {
      return
    }

    setSystemBanner(null)
    try {
      await deleteThread(threadId)
      setTotalThreadCount((current) => Math.max(0, current - 1))
      const remainingThreads = await fetchThreads(deferredSearch)
      setThreads(remainingThreads)

      if (route.kind === 'thread' && route.threadId === threadId) {
        if (remainingThreads[0]) {
          const nextThreadId = remainingThreads[0].thread_id
          navigate({ kind: 'thread', threadId: nextThreadId }, true)
          setSelectedThread(await fetchThread(nextThreadId))
        } else {
          navigate({ kind: 'home' }, true)
          setSelectedThread(null)
        }
      }
    } catch (error) {
      handleSystemError(error, 'Unable to delete this chat.')
    }
  }

  function handleComposerChange(value: string) {
    setComposerValue(value)
    if (composerError) {
      setComposerError('')
    }
  }

  function handleStreamStarted(event: StreamRunStartedEvent) {
    setPendingTurn((current) => {
      if (!current) {
        return current
      }
      return {
        ...current,
        timestamp: event.timestamp,
        trace_id: event.trace_id,
      }
    })
  }

  function handleStreamStep(event: StreamTraceStepEvent | StreamRetryScheduledEvent) {
    setPendingTurn((current) => {
      if (!current) {
        return current
      }

      const existingSteps = current.execution_steps.filter((step) => step.step_number !== event.step.step_number)
      const nextSteps = [...existingSteps, event.step].sort((left, right) => left.step_number - right.step_number)

      return {
        ...current,
        execution_steps: nextSteps,
        tools_used: mergePendingToolLabels(current.tools_used, event.step),
      }
    })
  }

  async function persistCompletedStream(event: StreamCompletedEvent) {
    setPendingTurn(null)
    setSelectedThread(event.thread)
    const refreshedThreads = await fetchThreads(deferredSearch)
    setThreads(refreshedThreads)
    setComposerValue('')
    navigate({ kind: 'thread', threadId: event.thread.thread_id }, true)
  }

  async function handleSubmitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (composerDisabledReason) {
      setComposerError(composerDisabledReason)
      return
    }

    if (!composerValue.trim()) {
      setComposerError('Enter a task to continue.')
      return
    }

    const validationError = getComposerValidation(composerValue)
    if (validationError) {
      setComposerError(validationError)
      return
    }

    setSystemBanner(null)
    setComposerError('')
    setIsSubmitting(true)

    try {
      const taskText = composerValue.trim()
      let thread = selectedThread
      if (!thread) {
        if (isThreadLimitReached) {
          setComposerError(threadLimitMessage())
          return
        }
        const createdThread = await createThread()
        thread = createdThread
        setSelectedThread(createdThread)
        setTotalThreadCount((current) => current + 1)
        setThreads((current) => [
          buildThreadSummary(createdThread),
          ...current.filter((item) => item.thread_id !== createdThread.thread_id),
        ])
        navigate({ kind: 'thread', threadId: createdThread.thread_id })
      }

      setPendingTurn({
        execution_steps: [],
        task_text: taskText,
        timestamp: new Date().toISOString(),
        tools_used: [],
        trace_id: '',
      })

      try {
        const completedEvent = await createTurnStream(
          thread.thread_id,
          { task_text: taskText },
          {
            onRetryScheduled: handleStreamStep,
            onRunStarted: handleStreamStarted,
            onTraceStep: handleStreamStep,
          },
        )
        await persistCompletedStream(completedEvent)
      } catch (error) {
        if (error instanceof StreamUnavailableError) {
          setPendingTurn(null)
          await createTurn(thread.thread_id, { task_text: taskText })
          const refreshedThread = await fetchThread(thread.thread_id)
          const refreshedThreads = await fetchThreads(deferredSearch)
          setSelectedThread(refreshedThread)
          setThreads(refreshedThreads)
          setComposerValue('')
          navigate({ kind: 'thread', threadId: thread.thread_id }, true)
        } else {
          throw error
        }
      }
    } catch (error) {
      setPendingTurn(null)
      if (error instanceof ApiError && isInputError(error)) {
        setComposerError(error.message)
      } else {
        handleSystemError(error, 'Unable to run this task.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const username = createUserForm.username.trim()
    const passwordError = getPasswordValidation(createUserForm.password)
    const roleCount = users.filter((user) => user.role === createUserForm.role).length
    const roleLimit = createUserForm.role === 'admin' ? ROLE_LIMITS.admin : ROLE_LIMITS.user
    const nextErrors: CreateUserErrors = {}

    if (username.length < 3) {
      nextErrors.username = 'Use at least 3 characters.'
    }
    if (passwordError) {
      nextErrors.password = passwordError
    }
    if (roleCount >= roleLimit) {
      nextErrors.form = roleLimitMessage(createUserForm.role)
    }

    if (nextErrors.username || nextErrors.password || nextErrors.form) {
      setCreateUserErrors(nextErrors)
      return
    }

    setCreateUserErrors({})
    setAdminNotice('')
    setSystemBanner(null)
    setIsCreatingUser(true)

    try {
      const createdUser = await createUser({ ...createUserForm, username })
      setSessionPasswords((current) => ({ ...current, [createdUser.user_id]: createUserForm.password }))
      setPasswordVisibility((current) => ({ ...current, [createdUser.user_id]: false }))
      setCreateUserForm({ username: '', password: '', role: 'user' })
      setAdminNotice(`User ${username} created.`)
      await loadUsers()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        resetSession()
      } else if (error instanceof ApiError) {
        setCreateUserErrors({ form: error.message })
      } else {
        handleSystemError(error, 'Unable to create the user.')
      }
    } finally {
      setIsCreatingUser(false)
    }
  }

  async function handleDeleteUser(user: UserSummary) {
    if (!window.confirm(`Delete local user "${user.username}"?`)) {
      return
    }

    setSystemBanner(null)
    setDeletingUserId(user.user_id)
    try {
      await deleteUser(user.user_id)
      setUsers((current) => current.filter((item) => item.user_id !== user.user_id))
      setSessionPasswords((current) => {
        const next = { ...current }
        delete next[user.user_id]
        return next
      })
      setPasswordVisibility((current) => {
        const next = { ...current }
        delete next[user.user_id]
        return next
      })
    } catch (error) {
      if (error instanceof ApiError) {
        setCreateUserErrors({ form: error.message })
      } else {
        handleSystemError(error, 'Unable to delete the user.')
      }
    } finally {
      setDeletingUserId(null)
    }
  }

  function handleTogglePasswordVisibility(userId: string) {
    setPasswordVisibility((current) => ({ ...current, [userId]: !current[userId] }))
  }

  if (sessionStatus === 'loading') {
    return (
      <div className="screen screen--splash">
        <BrandMark size="lg" />
        <p>Loading TaskBuddy...</p>
      </div>
    )
  }

  if (sessionStatus === 'unauthenticated') {
    return (
      <>
        {systemBanner ? <PageBanner banner={systemBanner} onDismiss={() => setSystemBanner(null)} /> : null}
        <LoginView
          errors={loginErrors}
          isAuthenticating={isAuthenticating}
          loginPassword={loginPassword}
          loginUsername={loginUsername}
          onPasswordChange={setLoginPassword}
          onSubmit={handleLogin}
          onUsernameChange={setLoginUsername}
        />
      </>
    )
  }

  return (
    <div className={`app-layout ${isSidebarCollapsed ? 'app-layout--collapsed' : ''}`}>
      <Sidebar
        currentUser={currentUser}
        groupedThreads={groupedThreads}
        isCollapsed={isSidebarCollapsed}
        isLoadingThreads={isLoadingThreads}
        isThreadLimitReached={isThreadLimitReached}
        route={route}
        searchValue={searchValue}
        threadCount={totalThreadCount}
        onDeleteThread={handleDeleteThread}
        onLogout={() => void handleLogout()}
        onNavigate={navigate}
        onNewChat={() => void handleNewChat()}
        onSearchChange={setSearchValue}
        onSelectThread={(threadId) => void handleSelectThread(threadId)}
        onToggleCollapse={() => setIsSidebarCollapsed((current) => !current)}
      />

      <main className="app-main">
        {systemBanner ? <PageBanner banner={systemBanner} onDismiss={() => setSystemBanner(null)} /> : null}

        {route.kind === 'admin' && currentUser?.role === 'admin' ? (
          <AdminView
            currentUser={currentUser}
            form={createUserForm}
            formErrors={createUserErrors}
            isCreatingUser={isCreatingUser}
            isDeletingUser={deletingUserId}
            isLoadingUsers={isLoadingUsers}
            notice={adminNotice}
            onBack={() => navigate({ kind: 'home' })}
            onCreateUser={handleCreateUser}
            onDeleteUser={(user) => void handleDeleteUser(user)}
            onFormChange={setCreateUserForm}
            onTogglePasswordVisibility={handleTogglePasswordVisibility}
            passwordVisibility={passwordVisibility}
            sessionPasswords={sessionPasswords}
            users={users}
          />
        ) : (
          <WorkspaceView
            composerError={composerError}
            composerDisabledReason={composerDisabledReason}
            composerValue={composerValue}
            isSubmitting={isSubmitting}
            onComposerChange={handleComposerChange}
            onExampleSelect={setComposerValue}
            onSubmit={handleSubmitTask}
            pendingTurn={pendingTurn}
            selectedThread={selectedThread}
          />
        )}
      </main>
    </div>
  )
}

export default App
