// @ts-nocheck
import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import router from '@/router'

type RetriableRequestConfig = AxiosRequestConfig & {
  _authRetry?: boolean
}

let refreshPromise: Promise<string | null> | null = null
let sessionExpiryHandled = false

const isLoginEndpoint = (url: string) => url.includes('/auth/login')
const isRegisterEndpoint = (url: string) => url.includes('/auth/register')
const isRefreshEndpoint = (url: string) => url.includes('/auth/refresh')
const isLogoutEndpoint = (url: string) => url.includes('/auth/logout')
const isSessionMutationEndpoint = (url: string) =>
  isLoginEndpoint(url) || isRegisterEndpoint(url) || isRefreshEndpoint(url) || isLogoutEndpoint(url)

const expireLocalSession = () => {
  useAuthStore().clearSession()
  if (sessionExpiryHandled) return

  sessionExpiryHandled = true
  toast.error('登录已过期，请重新登录')
  if (router.currentRoute.value.name !== 'Login') {
    router.replace({ name: 'Login', query: { redirect: router.currentRoute.value.fullPath } })
  }
}

// 创建 Axios 实例
const client: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v2',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器（自动添加 Token）
client.interceptors.request.use(
  (config: AxiosRequestConfig) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      config.headers = config.headers || {}
      config.headers['Authorization'] = `Bearer ${authStore.token}`
    }
    return config as any
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器（统一错误处理）
client.interceptors.response.use(
  (response: AxiosResponse) => {
    const requestUrl = response.config?.url || ''
    if (isLoginEndpoint(requestUrl) || isRefreshEndpoint(requestUrl)) {
      sessionExpiryHandled = false
    }
    return response.data
  },
  async (error) => {
    const { response } = error

    const requestUrl = error.config?.url || ''
    const isAuthEndpoint = isSessionMutationEndpoint(requestUrl)

    if (response) {
      switch (response.status) {
        case 401: {
          const originalRequest = error.config as RetriableRequestConfig
          const authStore = useAuthStore()

          if (!isAuthEndpoint && !originalRequest?._authRetry && authStore.refreshToken) {
            originalRequest._authRetry = true
            if (!refreshPromise) {
              refreshPromise = authStore.refresh().finally(() => {
                refreshPromise = null
              })
            }

            const accessToken = await refreshPromise
            if (accessToken) {
              originalRequest.headers = originalRequest.headers || {}
              originalRequest.headers.Authorization = `Bearer ${accessToken}`
              return client.request(originalRequest)
            }
          }

          if (!isAuthEndpoint) {
            expireLocalSession()
          }
          break
        }
        case 403:
          toast.error('没有权限执行此操作')
          break
        case 404:
          toast.error('请求的资源不存在')
          break
        case 422:
          toast.error('请求参数有误，请检查输入')
          break
        case 500:
          toast.error('服务器内部错误，请稍后重试')
          break
        default: {
          const message = response.data?.detail || response.data?.message || '请求失败'
          toast.error(message)
        }
      }
    } else {
      toast.error('网络连接失败，请检查网络设置')
    }

    return Promise.reject(error)
  }
)

export default client
