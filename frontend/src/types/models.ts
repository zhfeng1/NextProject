export interface User {
  id: string
  email: string
  name?: string
  avatar_url?: string
  is_superuser?: boolean
  default_org_id?: string
}

export interface Site {
  site_id: string
  name: string
  status: 'running' | 'stopped' | 'error' | 'building'
  port?: number
  preview_url?: string
  internal_url?: string
  config?: Record<string, unknown>
  project_id?: string
  created_at: string
}

export interface SiteCreateRequest {
  name: string
  template_id?: string
  git_url?: string
  git_branch?: string
  git_username?: string
  git_password?: string
  start_command?: string
}

export interface SiteUpdateRequest {
  name?: string
}

export interface Project {
  id: string
  name: string
  description: string
  repo_count: number
  repos?: Site[]
  created_at: string
  updated_at?: string
}

export interface ProjectCreateRequest {
  name: string
  description?: string
}

export interface RepoAddRequest {
  name: string
  git_url?: string
  git_branch?: string
  git_username?: string
  git_password?: string
}

export interface Template {
  id: string
  name: string
  description: string
  thumbnail_url: string
  rating: number
  usage_count: number
  category: string
}

export interface Task {
  id: string
  site_id: string
  project_id?: string
  title: string
  description: string
  priority: 'low' | 'medium' | 'high' | 'urgent' | string
  assignee: string
  board_status: 'todo' | 'queued' | 'running' | 'review' | 'done' | 'failed' | 'canceled' | string
  provider: string
  task_type: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'canceled' | string
  workflow_stages: string[]
  runtime_config_dir?: string
  payload?: Record<string, unknown>
  result?: Record<string, unknown>
  error?: string
  repositories?: TaskRepository[]
  project_name?: string
  created_at: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface TaskRepository {
  site_id: string
  site_db_id: string
  name: string
  repo_path: string
  before_sha: string
  after_sha: string
  changed: boolean
  commit_message: string
  rollback_status: string
}

export interface MCPService {
  id: string
  service_id: string
  name: string
  description: string
  scope_type: 'global' | 'project' | 'repo'
  project_id: string
  site_id: string
  required_fields: string[]
  supports_config: boolean
  enabled: boolean
  config: Record<string, string>
  last_test_ok: boolean | null
  last_tested_at: string | null
  last_error: string
}

export interface Skill {
  id: string
  name: string
  description: string
  scope_type: 'global' | 'project' | 'repo'
  scope?: 'global' | 'project' | 'repo'
  project_id: string
  site_id: string
  content: string
  triggers: string[]
  enabled: boolean
  source_type: string
  source_url: string
  created_at: string | null
  updated_at: string | null
}
