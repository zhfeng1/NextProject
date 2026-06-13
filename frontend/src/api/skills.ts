import client from './client'
import type { Skill } from '@/types/models'

export const skillsAPI = {
  list(params: { project_id?: string; site_id?: string; scope_type?: string } = {}) {
    return client.get<any, { ok: boolean; skills: Skill[] }>('/skills', { params })
  },

  create(payload: Partial<Skill> & { content: string }) {
    return client.post<any, { ok: boolean; skill: Skill }>('/skills', payload)
  },

  update(skillId: string, payload: Partial<Skill>) {
    return client.put<any, { ok: boolean; skill: Skill }>(`/skills/${skillId}`, payload)
  },

  remove(skillId: string) {
    return client.delete<any, { ok: boolean; skill_id: string }>(`/skills/${skillId}`)
  },

  importMarkdown(payload: { name?: string; description?: string; markdown: string; triggers?: string[]; enabled?: boolean }) {
    return client.post<any, { ok: boolean; skill: Skill }>('/skills/import', { ...payload, type: 'markdown' })
  },

  importSkillsSh(url: string, enabled = true) {
    return client.post<any, { ok: boolean; skill: Skill }>('/skills/import', { type: 'skills_sh', url, enabled })
  },

  listBySite(siteId: string) {
    return client.get<any, { ok: boolean; skills: Skill[] }>(`/skills/site/${siteId}`)
  },
}
