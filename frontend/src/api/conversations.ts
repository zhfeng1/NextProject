import client from './client'

export interface Conversation {
  id: string
  site_id: string
  scope_type: 'site' | 'project' | string
  project_id: string
  repo_ids: string[]
  provider: string
  branch_name: string
  worktree_root: string
  completion_status: 'active' | 'merging' | 'completed' | 'failed' | string
  completion_task_id: string
  completion_error: string
  cleanup_status?: string
  cleanup_error?: string
  completed_at: string | null
  title: string
  status: 'active' | 'archived'
  summary_text: string
  message_count: number
  last_message_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ConversationGitFile {
  status: string
  path: string
  old_path?: string
  score?: string
}

export interface ConversationGitRepository {
  site_id: string
  name: string
  main_branch: string
  branch_name: string
  ahead: number
  behind: number
  changed_files: number
  insertions: number
  deletions: number
  files: ConversationGitFile[]
  diff: string
  diff_truncated: boolean
  snapshot?: boolean
}

export interface ConversationGitFileDiff {
  site_id: string
  name: string
  path: string
  old_path: string
  status: string
  before: string
  after: string
  before_exists: boolean
  after_exists: boolean
  binary: boolean
  truncated: boolean
  before_revision: string
  after_revision: string
}

export interface ConversationGitState {
  available: boolean
  provider: string
  branch_name: string
  worktree_root: string
  completion_status: string
  repositories: ConversationGitRepository[]
}

export interface ConversationMessage {
  id: number
  conversation_id: string
  seq: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  message_type: 'text' | 'task_ref'
  provider: string
  task_id: string
  token_count: number
  metadata: Record<string, unknown>
  created_at: string | null
}

export const conversationsAPI = {
  create(siteId: string, title?: string) {
    return client.post<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/site/${siteId}`,
      title ? { title } : {},
    )
  },

  createProject(projectId: string, data: { title?: string; repo_ids?: string[]; provider?: string } = {}) {
    return client.post<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/project/${projectId}`,
      {
        title: data.title || '新会话',
        repo_ids: data.repo_ids || [],
        provider: data.provider || 'codex',
      },
    )
  },

  list(siteId: string, limit = 50) {
    return client.get<any, { ok: boolean; site_id: string; conversations: Conversation[] }>(
      `/conversations/site/${siteId}?limit=${limit}`,
    )
  },

  listProject(projectId: string, limit = 50, status: 'active' | 'archived' = 'active') {
    return client.get<any, { ok: boolean; project_id: string; conversations: Conversation[] }>(
      `/conversations/project/${projectId}?limit=${limit}&status=${status}`,
    )
  },

  get(convId: string) {
    return client.get<any, { ok: boolean; conversation: Conversation & { messages: ConversationMessage[] } }>(
      `/conversations/${convId}`,
    )
  },

  getGit(convId: string) {
    return client.get<any, { ok: boolean; git: ConversationGitState }>(
      `/conversations/${convId}/git`,
    )
  },

  getGitFileDiff(convId: string, repoId: string, path: string) {
    return client.get<any, { ok: boolean; file: ConversationGitFileDiff }>(
      `/conversations/${convId}/repos/${repoId}/git/diff`,
      { params: { path } },
    )
  },

  complete(convId: string) {
    return client.post<any, {
      ok: boolean
      conversation: Conversation
      assistant_message: ConversationMessage
      task_id: string
      task: Record<string, unknown>
    }>(`/conversations/${convId}/complete`)
  },

  sendMessage(
    convId: string,
    content: string,
    opts: { provider?: string; repo_ids?: string[]; current_url?: string; selected_xpath?: string; console_errors?: string } = {},
  ) {
    return client.post<any, { ok: boolean; user_message: ConversationMessage; assistant_message?: ConversationMessage; task_id?: string; task?: Record<string, unknown> }>(
      `/conversations/${convId}/messages`,
      {
        content,
        provider: opts.provider ?? 'codex',
        repo_ids: opts.repo_ids ?? [],
        current_url: opts.current_url ?? '',
        selected_xpath: opts.selected_xpath ?? '',
        console_errors: opts.console_errors ?? '',
      },
    )
  },

  listMessages(convId: string, limit = 100, afterSeq = 0) {
    return client.get<any, { ok: boolean; conv_id: string; messages: ConversationMessage[] }>(
      `/conversations/${convId}/messages?limit=${limit}&after_seq=${afterSeq}`,
    )
  },

  archive(convId: string) {
    return client.delete<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/${convId}`,
    )
  },

  cleanup(convId: string) {
    return client.post<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/${convId}/cleanup`,
    )
  },

  restore(convId: string) {
    return client.post<any, { ok: boolean; conversation: Conversation }>(
      `/conversations/${convId}/restore`,
    )
  },
}
