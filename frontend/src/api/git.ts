import client from './client'

export type GitRefType = 'head' | 'branch' | 'local_branch' | 'remote' | 'remote_branch' | 'tag' | string

export interface GitGraphLabel {
  name: string
  full_name: string
  type: GitRefType
  current: boolean
}

export interface GitGraphBranchRef extends GitGraphLabel {
  sha: string
}

export interface GitGraphParentLane {
  sha: string
  lane: number
}

export interface GitGraphCommit {
  sha: string
  short_sha: string
  subject: string
  message: string
  author_name: string
  author_email: string
  authored_at: string | null
  committed_at: string | null
  parents: string[]
  lane: number
  parent_lanes: GitGraphParentLane[]
  labels: GitGraphLabel[]
  current: boolean
}

export interface GitGraph {
  site_id: string
  name: string
  branch: string
  default_branch: string
  scope: 'project' | 'conversation' | string
  head_sha: string
  total: number
  truncated: boolean
  commits: GitGraphCommit[]
  lanes: number
  branches: GitGraphBranchRef[]
}

export interface GitRollbackOperation {
  id: string
  scope: 'project' | 'conversation' | string
  site_id: string
  conversation_id: string | null
  branch: string
  target_sha: string
  before_sha: string
  after_sha: string
  status: string
  error: string
  created_at: string | null
}

type GitGraphResponse = { ok: boolean; graph: GitGraph }
type GitRollbackResponse = { ok: boolean; operation: GitRollbackOperation; graph: GitGraph }

export const gitAPI = {
  getProjectGraph(projectId: string, repoId: string, limit = 200, skip = 0, branch = '') {
    return client.get<any, GitGraphResponse>(
      `/projects/${projectId}/repos/${repoId}/git/graph`,
      { params: { limit, skip, ...(branch ? { branch } : {}) } },
    )
  },

  rollbackProject(projectId: string, repoId: string, commitSha: string) {
    return client.post<any, GitRollbackResponse>(
      `/projects/${projectId}/repos/${repoId}/git/rollback`,
      { commit_sha: commitSha },
    )
  },

  getConversationGraph(conversationId: string, repoId: string, limit = 200, skip = 0) {
    return client.get<any, GitGraphResponse>(
      `/conversations/${conversationId}/repos/${repoId}/git/graph`,
      { params: { limit, skip } },
    )
  },

  rollbackConversation(conversationId: string, repoId: string, commitSha: string) {
    return client.post<any, GitRollbackResponse>(
      `/conversations/${conversationId}/repos/${repoId}/git/rollback`,
      { commit_sha: commitSha },
    )
  },
}
