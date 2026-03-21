import client from './client'

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

export interface TaskLog {
  id: number
  ts: string
  level: string
  line: string
}

export interface Task {
  id: string
  site_id: string
  task_type: string
  provider: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'canceled'
  error: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export const tasksAPI = {
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

  listBySite(siteId: string, limit = 10) {
    return client.get<any, { ok: boolean; tasks: Task[] }>(
      `/tasks/site/${siteId}?limit=${limit}`,
    )
  },

  cancel(taskId: string) {
    return client.post(`/tasks/${taskId}/cancel`)
  },

  remove(taskId: string) {
    return client.delete(`/tasks/${taskId}`)
  },
}
