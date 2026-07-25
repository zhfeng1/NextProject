import client from './client'
import type { Task } from '@/types/models'
export type { Task } from '@/types/models'

export interface TaskPayload {
  site_id: string
  task_type: 'develop_code' | 'deploy_local' | 'test_local_playwright'
  provider?: string
  prompt?: string
  current_url?: string
  selected_xpath?: string
  console_errors?: string
  [key: string]: unknown
}

export interface ProjectTaskPayload {
  repo_ids: string[]
  provider: string
  title: string
  prompt: string
  priority?: string
  assignee?: string
  workflow_stages?: string[]
  mcp_service_ids?: string[]
  skill_ids?: string[]
  enabled_mcp_services?: string[]
  enabled_skill_ids?: string[]
}

export interface TaskLog {
  id: number
  ts: string
  level: string
  line: string
}

export interface TaskProviderOutput {
  task_id: string
  provider: string
  available: boolean
  content: string
  truncated: boolean
}

export interface TaskWsTicket {
  ticket: string
}

export interface ExecutionDetailEvent {
  source: string
  seq: number
  ts: string
  level: string
  kind: string
  content: string
}

export interface ExecutionDetailsResponse {
  events: ExecutionDetailEvent[]
  next_after_log_id: number
  next_after_trace_seq: number
  has_more: boolean
  complete: boolean
  redacted: boolean
}

export const tasksAPI = {
  list(params: {
    project_id?: string
    repo_id?: string
    provider?: string
    board_status?: string
    priority?: string
    keyword?: string
    limit?: number
  } = {}) {
    return client.get<any, { ok: boolean; tasks: Task[] }>('/tasks', { params })
  },

  create(payload: TaskPayload) {
    return client.post<any, { ok: boolean; task: Task }>('/tasks', payload)
  },

  get(taskId: string) {
    return client.get<any, { ok: boolean; task: Task }>(
      `/tasks/${taskId}?_ts=${Date.now()}`,
      {
        headers: {
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache',
        },
      },
    )
  },

  getLogs(taskId: string, afterId = 0) {
    return client.get<any, { ok: boolean; logs: TaskLog[] }>(
      `/tasks/${taskId}/logs?after_id=${afterId}&limit=500&_ts=${Date.now()}`,
      {
        headers: {
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache',
        },
      },
    )
  },

  getProviderOutput(taskId: string) {
    return client.get<any, { ok: boolean } & TaskProviderOutput>(
      `/tasks/${taskId}/provider-output?_ts=${Date.now()}`,
      {
        headers: {
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache',
        },
      },
    )
  },

  createWsTicket(taskId: string) {
    return client.post<any, TaskWsTicket>(`/tasks/${taskId}/ws-ticket`)
  },

  getExecutionDetails(taskId: string, afterLogId = 0, afterTraceSeq = 0, limit = 200) {
    return client.get<any, ExecutionDetailsResponse>(`/tasks/${taskId}/execution-details`, {
      params: {
        after_log_id: afterLogId,
        after_trace_seq: afterTraceSeq,
        limit,
      },
      headers: {
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache',
      },
    })
  },

  listBySite(siteId: string, opts: { task_type?: string; limit?: number } = {}) {
    const params = new URLSearchParams()
    if (opts.task_type) params.set('task_type', opts.task_type)
    params.set('limit', String(opts.limit ?? 10))
    return client.get<any, { ok: boolean; tasks: Task[] }>(
      `/tasks/site/${siteId}?${params.toString()}`,
    )
  },

  cancel(taskId: string) {
    return client.post(`/tasks/${taskId}/cancel`)
  },

  retry(taskId: string) {
    return client.post<any, { ok: boolean; task: Task }>(`/tasks/${taskId}/retry`)
  },

  updateBoardStatus(taskId: string, boardStatus: string) {
    return client.patch<any, { ok: boolean; task: Task }>(`/tasks/${taskId}/board-status`, { board_status: boardStatus })
  },

  rollback(taskId: string) {
    return client.post<any, { ok: boolean; task: Task }>(`/tasks/${taskId}/rollback`)
  },

  remove(taskId: string) {
    return client.delete(`/tasks/${taskId}`)
  },
}
