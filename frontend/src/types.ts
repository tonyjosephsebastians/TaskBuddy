export interface LoginPayload {
  username: string
  password: string
}

export interface TaskCreatePayload {
  task_text: string
  client_request_id?: string
}

export interface CreateUserPayload {
  username: string
  password: string
  role: 'admin' | 'user'
}

export interface ExecutionStep {
  step_number: number
  phase: string
  status: string
  message: string
  tool_name?: string | null
  payload?: Record<string, unknown> | null
}

export interface TurnResponse {
  turn_id: string
  task_text: string
  status: string
  final_output: string
  output_data: Record<string, unknown>
  tools_used: string[]
  execution_steps: ExecutionStep[]
  timestamp: string
  trace_id: string
}

export interface ThreadSummary {
  thread_id: string
  title: string
  last_message_preview: string
  updated_at: string
}

export interface ThreadDetail {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
  turns: TurnResponse[]
}

export interface StreamRunStartedEvent {
  type: 'run_started'
  turn_id: string
  task_text: string
  timestamp: string
  trace_id: string
}

export interface StreamTraceStepEvent {
  type: 'trace_step'
  step: ExecutionStep
  trace_id: string
}

export interface StreamRetryScheduledEvent {
  type: 'retry_scheduled'
  step: ExecutionStep
  trace_id: string
  delay_ms: number
}

export interface StreamCompletedEvent {
  type: 'completed'
  trace_id: string
  timestamp: string
  turn: TurnResponse
  thread: ThreadDetail
}

export interface AuthUser {
  user_id: string
  username: string
  role: 'admin' | 'user'
}

export interface UserSummary {
  user_id: string
  username: string
  role: 'admin' | 'user'
  created_at: string
}
