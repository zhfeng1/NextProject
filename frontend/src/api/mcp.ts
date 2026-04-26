import client from './client'
import type { MCPService } from '@/types/models'

export const mcpAPI = {
  list() {
    return client.get<any, { ok: boolean; services: MCPService[] }>('/mcp/services')
  },

  update(serviceId: string, payload: { enabled: boolean; config?: Record<string, string> }) {
    return client.put<any, { ok: boolean; service: MCPService }>(`/mcp/services/${serviceId}`, payload)
  },

  test(serviceId: string) {
    return client.post<any, { ok: boolean; message: string; service: MCPService }>(`/mcp/services/${serviceId}/test`)
  },
}
