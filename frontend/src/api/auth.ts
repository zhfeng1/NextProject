import client from './client'

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface RegisterRequest {
  email: string
  password: string
  name?: string
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

export const authAPI = {
  login(data: LoginRequest) {
    return client.post<any, LoginResponse>('/auth/login', data)
  },

  register(data: RegisterRequest) {
    return client.post<any, { ok: boolean; user_id: string }>('/auth/register', data)
  },

  getCurrentUser() {
    return client.get('/auth/me')
  },

  refreshToken(refreshToken: string) {
    return client.post('/auth/refresh', { refresh_token: refreshToken })
  },

  updateProfile(data: { name?: string; avatar_url?: string }) {
    return client.put('/auth/me', data)
  },

  updateEmail(data: { new_email: string; current_password: string }) {
    return client.put('/auth/me/email', data)
  },

  updatePassword(data: { current_password: string; new_password: string }) {
    return client.put('/auth/me/password', data)
  },

  getUserConfig() {
    return client.get<any, { ok: boolean; config: UserConfig }>('/auth/me/config')
  },

  updateUserConfig(data: Partial<UserConfig>) {
    return client.put<any, { ok: boolean; config: UserConfig }>('/auth/me/config', data)
  },
}
