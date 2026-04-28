import client from './client'
import type { WorkflowRun } from '@/types/models'

export interface WorkflowArtifactsResponse {
  ok: boolean
  run: WorkflowRun
  artifacts: Record<string, { label: string; path: string; content: string }>
}

export const workflowsAPI = {
  list(limit = 20) {
    return client.get<any, { ok: boolean; runs: WorkflowRun[] }>(`/workflows/runs?limit=${limit}`)
  },

  getCurrent(siteId: string) {
    return client.get<any, { ok: boolean; run: WorkflowRun | null }>(`/workflows/sites/${siteId}/current`)
  },

  create(siteId: string, payload: { name?: string; enabled_mcp_services?: string[]; enabled_skill_ids?: string[] }) {
    return client.post<any, { ok: boolean; run: WorkflowRun }>(`/workflows/sites/${siteId}/runs`, payload)
  },

  get(runId: string) {
    return client.get<any, { ok: boolean; run: WorkflowRun }>(`/workflows/runs/${runId}`)
  },

  generateStage(runId: string, payload: { stage?: string; content?: string; notes?: string }) {
    return client.post<any, { ok: boolean; run: WorkflowRun; stage: string; content: string; artifact_path: string }>(
      `/workflows/runs/${runId}/generate-stage`,
      payload,
    )
  },

  confirmStage(runId: string) {
    return client.post<any, { ok: boolean; run: WorkflowRun }>(`/workflows/runs/${runId}/confirm-stage`)
  },

  getArtifacts(runId: string) {
    return client.get<any, WorkflowArtifactsResponse>(`/workflows/runs/${runId}/artifacts`)
  },
}
