export interface User {
  id: string
  email: string
  name?: string
  avatar_url?: string
  is_superuser?: boolean
  default_org_id?: string
}

export interface UserConfig {
  llm_mode: string
  llm_base_url: string
  llm_api_key: string
  llm_model: string
  codex_client_id: string
  codex_client_secret: string
  codex_redirect_uri: string
  codex_access_token: string
  codex_mcp_url: string
  claude_api_key: string
  gemini_api_key: string
}

export interface Site {
  site_id: string
  name: string
  status: 'running' | 'stopped' | 'failed' | 'building'
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
  task_id: string
  site_id: string
  status: 'pending' | 'running' | 'success' | 'failed'
  command: string
  created_at: string
}

export interface MCPService {
  service_id: string
  name: string
  description: string
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
  scope: 'global' | 'site'
  content: string
  triggers: string[]
  enabled: boolean
  source_type: string
  source_url: string
  bound_site_ids: string[]
  created_at: string | null
  updated_at: string | null
}

export interface WorkflowRun {
  id: string
  site_id: string
  site_name: string
  name: string
  status: string
  current_stage: 'research' | 'ideate' | 'plan' | 'execute' | 'optimize' | 'review'
  current_stage_label: string
  stage_status: Record<string, string>
  stage_artifacts: Record<string, string>
  enabled_mcp_services: string[]
  enabled_skill_ids: string[]
  summary: string
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
}
