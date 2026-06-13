import client from './client'
import type { MCPService } from '@/types/models'

export const mcpAPI = {
  list(params: { project_id?: string; site_id?: string; scope_type?: string } = {}) {
    return client.get<any, { ok: boolean; services: MCPService[] }>('/mcp/services', { params })
  },

  update(serviceId: string, payload: Partial<MCPService> & { config?: Record<string, string> }) {
    return client.put<any, { ok: boolean; service: MCPService }>(`/mcp/services/${serviceId}`, payload)
  },

  test(serviceId: string, payload: { project_id?: string; site_id?: string; scope_type?: string } = {}) {
    return client.post<any, { ok: boolean; message: string; service: MCPService }>(`/mcp/services/${serviceId}/test`, payload)
  },
}
