import client from './client'
import type { Template } from '@/types/models'

export const templatesAPI = {
  list(params?: { category?: string }) {
    return client.get<any, { ok: boolean; templates: Template[] }>('/templates', { params })
  },

  createSiteFromTemplate(data: { template_id: string; site_name: string }) {
    return client.post<any, { ok: boolean; site: any }>('/templates/use', data)
  }
}
