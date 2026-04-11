import client from './client'
import type { Project, ProjectCreateRequest, RepoAddRequest, Site } from '@/types/models'

export const projectsAPI = {
  list() {
    return client.get<any, { ok: boolean; projects: Project[] }>('/projects')
  },

  create(data: ProjectCreateRequest) {
    return client.post<any, { ok: boolean; project: Project }>('/projects', data)
  },

  get(projectId: string) {
    return client.get<any, { ok: boolean; project: Project }>(`/projects/${projectId}`)
  },

  update(projectId: string, data: Partial<ProjectCreateRequest>) {
    return client.put<any, { ok: boolean; project: Project }>(`/projects/${projectId}`, data)
  },

  delete(projectId: string) {
    return client.delete<any, { ok: boolean }>(`/projects/${projectId}`)
  },

  addRepo(projectId: string, data: RepoAddRequest) {
    return client.post<any, { ok: boolean; repo: Site }>(`/projects/${projectId}/repos`, data)
  },

  listRepoFiles(projectId: string, repoId: string, path = '') {
    return client.get<any, {
      ok: boolean
      current_path: string
      parent_path: string
      entries: Array<{ name: string; path: string; type: 'directory' | 'file'; size?: number | null }>
    }>(`/projects/${projectId}/repos/${repoId}/files`, { params: { path } })
  },

  getRepoFile(projectId: string, repoId: string, path: string) {
    return client.get<any, {
      ok: boolean
      path: string
      name: string
      size: number
      truncated: boolean
      binary: boolean
      content: string
    }>(`/projects/${projectId}/repos/${repoId}/file`, { params: { path } })
  },
}
