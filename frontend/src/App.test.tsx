import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { AuthUser, ThreadDetail, ThreadSummary, TurnResponse, UserSummary } from './types'

const adminUser: AuthUser = { user_id: 'user-admin', username: 'admin', role: 'admin' }
const analystUser: AuthUser = { user_id: 'user-analyst1', username: 'analyst1', role: 'user' }

let sessionUser: AuthUser | null
let users: UserSummary[]
let threads: ThreadSummary[]
let threadDetails: Record<string, ThreadDetail>
let streamMode: 'normal' | 'slow' | 'unavailable'
let threadCounter: number
let scrollIntoViewMock: ReturnType<typeof vi.fn>

function buildCompletedTurn(taskText: string): TurnResponse {
  return {
    turn_id: `turn-${Math.random().toString(16).slice(2)}`,
    task_text: taskText,
    status: 'completed',
    final_output: taskText.includes('weather') ? 'Toronto: Cloudy, 8C, humidity 71%.' : 'TASK BUDDY',
    output_data: taskText.includes('weather')
      ? { city: 'Toronto', condition: 'Cloudy', temperature_c: 8 }
      : { operation: 'uppercase', result: 'TASK BUDDY' },
    tools_used: [taskText.includes('weather') ? 'WeatherMockTool' : 'TextProcessorTool'],
    execution_steps: [
      { step_number: 1, phase: 'validation', status: 'completed', message: 'Checked request length and normalized the input.' },
      { step_number: 2, phase: 'planning', status: 'completed', message: 'Planned a single tool step: Text.' },
      { step_number: 3, phase: 'tool_execution', status: 'completed', message: 'Applied uppercase to the text input.', tool_name: 'TextProcessorTool' },
      { step_number: 4, phase: 'response_assembly', status: 'completed', message: 'Assembled final output, trace details, and structured data.' },
    ],
    timestamp: '2026-03-14T18:00:00Z',
    trace_id: 'trace-1',
  }
}

function buildUnsupportedTurn(taskText: string): TurnResponse {
  return {
    turn_id: 'turn-unsupported',
    task_text: taskText,
    status: 'unsupported',
    final_output: 'TaskBuddy could not match this request to a supported tool.',
    output_data: {
      issue: {
        error_code: 'UNSUPPORTED_TASK',
        message: 'TaskBuddy could not match this request to a supported tool.',
        suggestions: ['Convert "task buddy" to uppercase'],
      },
      supported_tasks: ['Convert "task buddy" to uppercase'],
    },
    tools_used: [],
    execution_steps: [
      { step_number: 1, phase: 'validation', status: 'completed', message: 'Checked request length and normalized the input.' },
      { step_number: 2, phase: 'planning', status: 'failed', message: 'TaskBuddy could not match this request to a supported tool.' },
      { step_number: 3, phase: 'response_assembly', status: 'completed', message: 'Returned a handled response with trace context and suggestions.' },
    ],
    timestamp: '2026-03-14T18:05:00Z',
    trace_id: 'trace-unsupported',
  }
}

function refreshSummary(detail: ThreadDetail): ThreadSummary {
  return {
    thread_id: detail.thread_id,
    title: detail.title,
    last_message_preview: detail.turns.at(-1)?.task_text ?? '',
    updated_at: detail.updated_at,
  }
}

function buildStreamResponse(turn: TurnResponse, detail: ThreadDetail, mode: 'normal' | 'slow') {
  const encoder = new TextEncoder()
  const stepDelay = mode === 'slow' ? 35 : 0
  const completedDelay = mode === 'slow' ? 35 : 0
  const events = [
    {
      event: 'run_started',
      data: {
        type: 'run_started',
        turn_id: turn.turn_id,
        task_text: turn.task_text,
        timestamp: turn.timestamp,
        trace_id: turn.trace_id,
      },
      delay: 0,
    },
    ...turn.execution_steps.map((step) => ({
      event: 'trace_step',
      data: {
        type: 'trace_step',
        step,
        trace_id: turn.trace_id,
      },
      delay: stepDelay,
    })),
    {
      event: 'completed',
      data: {
        type: 'completed',
        trace_id: turn.trace_id,
        timestamp: turn.timestamp,
        turn,
        thread: detail,
      },
      delay: completedDelay,
    },
  ]

  return new Response(
    new ReadableStream({
      start(controller) {
        let totalDelay = 0
        for (const item of events) {
          totalDelay += item.delay
          setTimeout(() => {
            controller.enqueue(
              encoder.encode(`event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`),
            )
          }, totalDelay)
        }
        setTimeout(() => controller.close(), totalDelay + 5)
      },
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    },
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  window.history.pushState({}, '', '/')
  scrollIntoViewMock = vi.fn()
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoViewMock,
  })
  sessionUser = null
  users = [
    { user_id: 'user-admin', username: 'admin', role: 'admin', created_at: '2026-03-14T18:00:00Z' },
  ]
  threads = [
    {
      thread_id: 'thread-1',
      title: 'Convert "task buddy" to uppercase',
      last_message_preview: 'Convert "task buddy" to uppercase',
      updated_at: '2026-03-14T18:00:00Z',
    },
  ]
  threadDetails = {
    'thread-1': {
      thread_id: 'thread-1',
      title: 'Convert "task buddy" to uppercase',
      created_at: '2026-03-14T18:00:00Z',
      updated_at: '2026-03-14T18:00:00Z',
      turns: [buildCompletedTurn('Convert "task buddy" to uppercase')],
    },
  }
  streamMode = 'normal'
  threadCounter = 1

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : null

      if (url.endsWith('/api/v1/auth/me')) {
        if (!sessionUser) {
          return new Response(JSON.stringify({ error_code: 'AUTH_REQUIRED', message: 'Authentication is required.' }), { status: 401 })
        }
        return new Response(JSON.stringify(sessionUser), { status: 200 })
      }

      if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
        if (body.username === 'admin' && body.password === 'admin123') {
          sessionUser = adminUser
          return new Response(JSON.stringify(adminUser), { status: 200 })
        }
        if (body.username === 'analyst1' && body.password === 'Analyst1') {
          sessionUser = analystUser
          return new Response(JSON.stringify(analystUser), { status: 200 })
        }
        return new Response(JSON.stringify({ error_code: 'AUTH_INVALID_CREDENTIALS', message: 'Invalid username or password.' }), { status: 401 })
      }

      if (url.endsWith('/api/v1/auth/logout') && method === 'POST') {
        sessionUser = null
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
      }

      if (url.includes('/api/v1/threads') && !sessionUser) {
        return new Response(JSON.stringify({ error_code: 'AUTH_REQUIRED', message: 'Authentication is required.' }), { status: 401 })
      }

      if (url.includes('/api/v1/admin/users') && (!sessionUser || sessionUser.role !== 'admin')) {
        return new Response(JSON.stringify({ error_code: 'FORBIDDEN', message: 'Administrator access is required.' }), { status: 403 })
      }

      if (url.includes('/api/v1/threads?search=')) {
        const search = decodeURIComponent(url.split('?search=')[1] ?? '').toLowerCase()
        const results = threads.filter((thread) => thread.title.toLowerCase().includes(search) || thread.last_message_preview.toLowerCase().includes(search))
        return new Response(JSON.stringify(results), { status: 200 })
      }

      if (url.endsWith('/api/v1/threads') && method === 'GET') {
        return new Response(JSON.stringify(threads), { status: 200 })
      }

      if (url.endsWith('/api/v1/threads') && method === 'POST') {
        threadCounter += 1
        const detail: ThreadDetail = {
          thread_id: `thread-${threadCounter}`,
          title: 'New chat',
          created_at: '2026-03-14T18:00:00Z',
          updated_at: '2026-03-14T18:00:00Z',
          turns: [],
        }
        threadDetails[detail.thread_id] = detail
        threads = [refreshSummary(detail), ...threads]
        return new Response(JSON.stringify(detail), { status: 200 })
      }

      if (/\/api\/v1\/threads\/[^/]+$/.test(url) && method === 'GET') {
        const threadId = url.split('/').at(-1) as string
        if (!threadDetails[threadId]) {
          return new Response(JSON.stringify({ error_code: 'THREAD_NOT_FOUND', message: 'Thread not found.' }), { status: 404 })
        }
        return new Response(JSON.stringify(threadDetails[threadId]), { status: 200 })
      }

      if (/\/api\/v1\/threads\/[^/]+$/.test(url) && method === 'DELETE') {
        const threadId = url.split('/').at(-1) as string
        delete threadDetails[threadId]
        threads = threads.filter((thread) => thread.thread_id !== threadId)
        return new Response(null, { status: 204 })
      }

      if (/\/api\/v1\/threads\/[^/]+\/tasks$/.test(url) && method === 'POST') {
        const threadId = url.split('/')[url.split('/').length - 2]
        const nextTurn = body.task_text.includes('unsupported')
          ? buildUnsupportedTurn(body.task_text)
          : buildCompletedTurn(body.task_text)
        const detail = threadDetails[threadId]
        detail.turns = [...detail.turns, nextTurn]
        detail.title = detail.title === 'New chat' ? body.task_text.slice(0, 48) : detail.title
        detail.updated_at = nextTurn.timestamp
        threadDetails[threadId] = detail
        threads = [refreshSummary(detail), ...threads.filter((thread) => thread.thread_id !== threadId)]
        return new Response(JSON.stringify(nextTurn), { status: 200 })
      }

      if (/\/api\/v1\/threads\/[^/]+\/tasks\/stream$/.test(url) && method === 'POST') {
        if (streamMode === 'unavailable') {
          return new Response(JSON.stringify({ status: 'unavailable' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }

        const threadId = url.split('/')[url.split('/').length - 3]
        const nextTurn = body.task_text.includes('unsupported')
          ? buildUnsupportedTurn(body.task_text)
          : buildCompletedTurn(body.task_text)
        const detail = threadDetails[threadId]
        detail.turns = [...detail.turns, nextTurn]
        detail.title = detail.title === 'New chat' ? body.task_text.slice(0, 48) : detail.title
        detail.updated_at = nextTurn.timestamp
        threadDetails[threadId] = detail
        threads = [refreshSummary(detail), ...threads.filter((thread) => thread.thread_id !== threadId)]
        return buildStreamResponse(nextTurn, detail, streamMode)
      }

      if (url.endsWith('/api/v1/admin/users') && method === 'GET') {
        return new Response(JSON.stringify(users), { status: 200 })
      }

      if (url.endsWith('/api/v1/admin/users') && method === 'POST') {
        const roleLimit = body.role === 'admin' ? 1 : 2
        const currentCount = users.filter((user) => user.role === body.role).length

        if (currentCount >= roleLimit) {
          return new Response(
            JSON.stringify({
              error_code: 'ROLE_LIMIT_REACHED',
              message: body.role === 'admin' ? 'TaskBuddy supports only 1 admin account.' : 'TaskBuddy supports up to 2 standard user accounts.',
            }),
            { status: 422 },
          )
        }

        const newUser: UserSummary = {
          user_id: `user-${body.username}`,
          username: body.username,
          role: body.role,
          created_at: '2026-03-14T18:00:00Z',
        }
        users = [...users, newUser]
        return new Response(JSON.stringify(newUser), { status: 200 })
      }

      if (/\/api\/v1\/admin\/users\/[^/]+$/.test(url) && method === 'DELETE') {
        const userId = url.split('/').at(-1) as string
        users = users.filter((user) => user.user_id !== userId)
        return new Response(null, { status: 204 })
      }

      return new Response(JSON.stringify({ error_code: 'NOT_FOUND', message: 'Not found' }), { status: 404 })
    }),
  )
})

describe('App', () => {
  it('renders the login page and signs in to the workspace', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'TaskBuddy' })).toBeInTheDocument()
    expect(screen.queryByText('Local demo access')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'admin123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByPlaceholderText('Search chat threads')).toBeInTheDocument()
    expect(screen.queryByText('Submit a task to execute predefined tools')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start new chat' })).toBeInTheDocument()
  })

  it('creates a new chat and renders the response card hierarchy', async () => {
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.click(screen.getByRole('button', { name: 'Start new chat' }))
    await waitFor(() => {
      expect(screen.getByText('New chat')).toBeInTheDocument()
      expect(window.location.pathname).toBe('/threads/thread-2')
    })
    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert "task buddy" to uppercase' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run task' }))

    await waitFor(() => {
      expect(screen.getAllByText('Execution trace').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('Final output').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Tools used').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TASK BUDDY').length).toBeGreaterThan(0)
  })

  it('creates a chat from the home workspace on first submission and activates the thread route', async () => {
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert "task buddy" to uppercase' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run task' }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/threads/thread-2')
    })
    expect(await screen.findByText('TASK BUDDY')).toBeInTheDocument()
  })

  it('renders streamed execution trace steps before completion', async () => {
    streamMode = 'slow'
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.click(screen.getByRole('button', { name: 'Start new chat' }))
    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert "slow stream" to uppercase' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run task' }))

    expect(await screen.findByText('Executing tools and assembling trace details.')).toBeInTheDocument()

    expect(await screen.findByText('Checked request length and normalized the input.')).toBeInTheDocument()

    expect((await screen.findAllByText('TASK BUDDY')).length).toBeGreaterThan(0)
  }, 10000)

  it('falls back to synchronous submission when streaming is unavailable', async () => {
    streamMode = 'unavailable'
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.click(screen.getByRole('button', { name: 'Start new chat' }))
    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert "task buddy" to uppercase' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run task' }))

    expect(await screen.findByText('TASK BUDDY')).toBeInTheDocument()
  })

  it('collapses and expands the history panel from the rail', async () => {
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.click(screen.getByRole('button', { name: 'Collapse history panel' }))

    expect(screen.queryByPlaceholderText('Search chat threads')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand history panel' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Expand history panel' }))

    expect(await screen.findByPlaceholderText('Search chat threads')).toBeInTheDocument()
  })

  it('shows inline composer validation for too many subtasks', async () => {
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert task buddy to uppercase and calculate 25 * 3 and weather in Toronto' },
    })

    expect(screen.getByText('Use up to 2 subtasks in a single request.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run task' })).toBeDisabled()
  })

  it('loads direct thread routes and redirects missing threads home', async () => {
    sessionUser = adminUser
    window.history.pushState({}, '', '/threads/missing-thread')
    render(<App />)

    expect(await screen.findByText('The requested chat could not be found.')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
  })

  it('blocks creating a sixth thread from the sidebar', async () => {
    sessionUser = adminUser
    threads = Array.from({ length: 5 }, (_, index) => ({
      thread_id: `thread-${index + 1}`,
      title: `Chat ${index + 1}`,
      last_message_preview: `Preview ${index + 1}`,
      updated_at: '2026-03-14T18:00:00Z',
    }))
    threadDetails = Object.fromEntries(
      threads.map((thread) => [
        thread.thread_id,
        {
          thread_id: thread.thread_id,
          title: thread.title,
          created_at: '2026-03-14T18:00:00Z',
          updated_at: '2026-03-14T18:00:00Z',
          turns: [buildCompletedTurn(thread.title)],
        },
      ]),
    )

    render(<App />)

    expect(await screen.findByText('TaskBuddy supports up to 5 chat threads per user. Delete an existing chat to create another one.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start new chat' })).toBeDisabled()
  })

  it('blocks submissions when a chat already has three task flows', async () => {
    sessionUser = adminUser
    window.history.pushState({}, '', '/threads/thread-1')
    threadDetails['thread-1'] = {
      ...threadDetails['thread-1'],
      turns: [
        buildCompletedTurn('Convert "task buddy" to uppercase'),
        buildCompletedTurn('Calculate 3 + 2'),
        buildCompletedTurn('What is the weather in Toronto?'),
      ],
    }

    render(<App />)

    expect(await screen.findByText('Each chat supports up to 3 task flows. Start a new chat or delete an old one to continue.')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Run task' })).toBeDisabled()
  })

  it('auto-scrolls the active thread when a later response is appended', async () => {
    sessionUser = adminUser
    window.history.pushState({}, '', '/threads/thread-1')
    threadDetails['thread-1'] = {
      ...threadDetails['thread-1'],
      turns: [
        buildCompletedTurn('Convert "task buddy" to uppercase'),
        buildCompletedTurn('What is the weather in Toronto?'),
      ],
    }

    render(<App />)

    expect(await screen.findAllByText('Execution trace')).toHaveLength(2)
    expect(scrollIntoViewMock).not.toHaveBeenCalled()

    fireEvent.change(screen.getByPlaceholderText('Ask TaskBuddy to run up to 2 supported subtasks.'), {
      target: { value: 'Convert "later turn" to uppercase' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run task' }))

    await waitFor(() => {
      expect(scrollIntoViewMock).toHaveBeenCalled()
    })
  })

  it('navigates to the admin page and reveals passwords only for session-created users', async () => {
    sessionUser = adminUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    fireEvent.click(screen.getByRole('button', { name: 'Admin' }))

    expect(await screen.findByText('Admin - User Management')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/admin')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    fireEvent.change(screen.getByLabelText(/^Username/), { target: { value: 'reviewer' } })
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: 'Reviewer1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    expect(await screen.findByText('reviewer')).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
    expect(screen.getByText('*********')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show password for reviewer' }))
    expect(screen.getByText('Reviewer1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide password for reviewer' }))
    expect(screen.getByText('*********')).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('button', { name: 'Delete reviewer' }))

    await waitFor(() => {
      expect(screen.queryByText('reviewer')).not.toBeInTheDocument()
    })
    confirmSpy.mockRestore()
  })

  it('keeps admin navigation hidden for standard users', async () => {
    sessionUser = analystUser
    render(<App />)

    await screen.findByPlaceholderText('Search chat threads')
    expect(screen.queryByRole('button', { name: 'Admin' })).not.toBeInTheDocument()
  })
})
