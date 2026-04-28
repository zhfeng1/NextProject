import client from './client'
import type { Template } from '@/types/models'

export const templatesAPI = {
  list(params?: { category?: string }) {
    return client.get<any, { ok: boolean; templates: Template[] }>('/templates', { params })
  },

  async createSiteFromTemplate(data: { template_id: string; site_name: string }) {
    const response = await client.post<any, { ok: boolean; site_id: string }>('/templates/sites/from-template', data)
    return {
      ok: response.ok,
      site: {
        site_id: response.site_id,
      },
    }
  }
}
