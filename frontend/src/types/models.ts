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
