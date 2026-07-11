// @ts-nocheck
import { defineStore } from 'pinia'
import { authAPI } from '@/api/auth'
import type { User } from '@/types/models'

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: User | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem('access_token'),
    refreshToken: localStorage.getItem('refresh_token'),
    user: null,
  }),

  getters: {
    isAuthenticated: (state) => !!state.token,
  },

  actions: {
    normalizeUser(payload: any) {
      return payload?.user || payload || null
    },

    // 登录
    async login(email: string, password: string) {
      const response = await authAPI.login({ email, password })

      this.token = response.access_token
      this.refreshToken = response.refresh_token
      this.user = this.normalizeUser(response)

      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('refresh_token', response.refresh_token)

      // 获取用户信息
      await this.fetchUser()
    },

    // 注册
    async register(email: string, password: string, name?: string) {
      await authAPI.register({ email, password, name })
      // 注册成功后自动登录
      await this.login(email, password)
    },

    // 获取用户信息
    async fetchUser() {
      const response = await authAPI.getCurrentUser()
      this.user = this.normalizeUser(response)
    },

    clearSession() {
      this.token = null
      this.refreshToken = null
      this.user = null

      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    },

    // 登出
    async logout() {
      const refreshToken = this.refreshToken
      this.clearSession()
      if (refreshToken) {
        try {
          await authAPI.logout(refreshToken)
        } catch {
          // Local credentials are already cleared; server session will expire by TTL.
        }
      }
    },

    // 刷新 Token
    async refresh() {
      if (!this.refreshToken) {
        this.clearSession()
        return null
      }

      try {
        const response = await authAPI.refreshToken(this.refreshToken)
        this.token = response.access_token
        localStorage.setItem('access_token', response.access_token)
        return response.access_token as string
      } catch {
        this.clearSession()
        return null
      }
    },
  },
})
