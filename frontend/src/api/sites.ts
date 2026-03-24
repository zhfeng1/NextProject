import client from './client'
import type { Site, SiteCreateRequest, SiteUpdateRequest } from '@/types/models'

export const sitesAPI = {
  // 获取站点列表
  list() {
    return client.get<any, { ok: boolean; sites: Site[] }>('/sites')
  },

  // 创建站点
  create(data: SiteCreateRequest) {
    return client.post<any, { ok: boolean; site: Site }>('/sites', data)
  },

  // 获取站点详情
  get(siteId: string) {
    return client.get<any, { ok: boolean; site: Site }>(`/sites/${siteId}`)
  },

  // 更新站点
  update(siteId: string, data: SiteUpdateRequest) {
    return client.patch<any, { ok: boolean; site: Site }>(`/sites/${siteId}`, data)
  },

  // 删除站点
  delete(siteId: string) {
    return client.delete(`/sites/${siteId}`)
  },

  // 启动站点
  start(siteId: string) {
    return client.post(`/sites/${siteId}/start`)
  },

  // 停止站点
  stop(siteId: string) {
    return client.post(`/sites/${siteId}/stop`)
  },

  // 获取需求文档
  getRequirements(siteId: string) {
    return client.get<any, { ok: boolean; content: string }>(`/sites/${siteId}/requirements`)
  },

  // 获取目录列表
  listFiles(siteId: string, path = '') {
    return client.get<any, {
      ok: boolean
      current_path: string
      parent_path: string
      entries: Array<{ name: string; path: string; type: 'directory' | 'file'; size?: number | null }>
    }>(`/sites/${siteId}/files`, { params: { path } })
  },

  // 获取文件内容
  getFileContent(siteId: string, path: string) {
    return client.get<any, {
      ok: boolean
      path: string
      name: string
      size: number
      truncated: boolean
      binary: boolean
      content: string
    }>(`/sites/${siteId}/file`, { params: { path } })
  },

  // 追加需求条目
  addRequirement(siteId: string, content: string) {
    return client.post<any, { ok: boolean; content: string }>(`/sites/${siteId}/requirements`, { content })
  },
}
