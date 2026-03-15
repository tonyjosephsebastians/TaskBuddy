import type {
  AuthUser,
  CreateUserPayload,
  LoginPayload,
  StreamCompletedEvent,
  StreamRetryScheduledEvent,
  StreamRunStartedEvent,
  StreamTraceStepEvent,
  TaskCreatePayload,
  ThreadDetail,
  ThreadSummary,
  TurnResponse,
  UserSummary,
} from './types'

export class ApiError extends Error {
  code: string
  status: number
  details: Record<string, unknown>

  constructor(message: string, status: number, code = 'REQUEST_FAILED', details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export class StreamUnavailableError extends Error {
  constructor(message = 'Task streaming is unavailable.') {
    super(message)
    this.name = 'StreamUnavailableError'
  }
}

type StreamHandlers = {
  onCompleted?: (event: StreamCompletedEvent) => void
  onRetryScheduled?: (event: StreamRetryScheduledEvent) => void
  onRunStarted?: (event: StreamRunStartedEvent) => void
  onTraceStep?: (event: StreamTraceStepEvent) => void
}

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error_code?: string; message?: string; details?: Record<string, unknown> }
      | null
    throw new ApiError(
      payload?.message ?? 'Request failed.',
      response.status,
      payload?.error_code ?? 'REQUEST_FAILED',
      payload?.details ?? {},
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

function parseSseBlock(block: string) {
  let eventName = 'message'
  const dataLines: string[] = []

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (dataLines.length === 0) {
    return null
  }

  return {
    eventName,
    data: dataLines.join('\n'),
  }
}

export function login(payload: LoginPayload) {
  return apiRequest<AuthUser>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function logout() {
  return apiRequest<{ status: string }>('/api/v1/auth/logout', { method: 'POST' })
}

export function fetchMe() {
  return apiRequest<AuthUser>('/api/v1/auth/me')
}

export function fetchThreads(search = '') {
  const query = search ? `?search=${encodeURIComponent(search)}` : ''
  return apiRequest<ThreadSummary[]>(`/api/v1/threads${query}`)
}

export function createThread() {
  return apiRequest<ThreadDetail>('/api/v1/threads', { method: 'POST' })
}

export function fetchThread(threadId: string) {
  return apiRequest<ThreadDetail>(`/api/v1/threads/${threadId}`)
}

export function deleteThread(threadId: string) {
  return apiRequest<void>(`/api/v1/threads/${threadId}`, {
    method: 'DELETE',
  })
}

export function createTurn(threadId: string, payload: TaskCreatePayload) {
  return apiRequest<TurnResponse>(`/api/v1/threads/${threadId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function createTurnStream(threadId: string, payload: TaskCreatePayload, handlers: StreamHandlers = {}) {
  const response = await fetch(`/api/v1/threads/${threadId}/tasks/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as
      | { error_code?: string; message?: string; details?: Record<string, unknown> }
      | null
    throw new ApiError(
      errorPayload?.message ?? 'Request failed.',
      response.status,
      errorPayload?.error_code ?? 'REQUEST_FAILED',
      errorPayload?.details ?? {},
    )
  }

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('text/event-stream') || !response.body) {
    throw new StreamUnavailableError()
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let receivedEvent = false

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })

    while (true) {
      const boundaryIndex = buffer.indexOf('\n\n')
      if (boundaryIndex < 0) {
        break
      }

      const rawBlock = buffer.slice(0, boundaryIndex).trim()
      buffer = buffer.slice(boundaryIndex + 2)
      if (!rawBlock) {
        continue
      }

      const parsed = parseSseBlock(rawBlock)
      if (!parsed) {
        continue
      }

      receivedEvent = true
      const payloadData = JSON.parse(parsed.data) as Record<string, unknown>

      switch (parsed.eventName) {
        case 'run_started':
          handlers.onRunStarted?.(payloadData as unknown as StreamRunStartedEvent)
          break
        case 'trace_step':
          handlers.onTraceStep?.(payloadData as unknown as StreamTraceStepEvent)
          break
        case 'retry_scheduled':
          handlers.onRetryScheduled?.(payloadData as unknown as StreamRetryScheduledEvent)
          break
        case 'completed': {
          const completedEvent = payloadData as unknown as StreamCompletedEvent
          handlers.onCompleted?.(completedEvent)
          return completedEvent
        }
        case 'failed':
          throw new ApiError(
            String(payloadData.message ?? 'Streaming request failed.'),
            Number(payloadData.status_code ?? 500),
            String(payloadData.error_code ?? 'STREAM_FAILED'),
            (payloadData.details as Record<string, unknown> | undefined) ?? {},
          )
        default:
          break
      }
    }

    if (done) {
      break
    }
  }

  if (!receivedEvent) {
    throw new StreamUnavailableError()
  }

  throw new StreamUnavailableError('Task streaming ended before completion.')
}

export function fetchUsers() {
  return apiRequest<UserSummary[]>('/api/v1/admin/users')
}

export function createUser(payload: CreateUserPayload) {
  return apiRequest<UserSummary>('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteUser(userId: string) {
  return apiRequest<void>(`/api/v1/admin/users/${userId}`, {
    method: 'DELETE',
  })
}
