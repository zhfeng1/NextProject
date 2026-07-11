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

  logout(refreshToken: string) {
    return client.post('/auth/logout', { refresh_token: refreshToken })
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
    return client.get<any, { ok: boolean; config: Record<string, unknown> }>('/auth/me/config')
  },

  updateUserConfig(data: Record<string, unknown>) {
    return client.put<any, { ok: boolean; config: Record<string, unknown> }>('/auth/me/config', data)
  },
}
