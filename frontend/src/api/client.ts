// @ts-nocheck
import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import router from '@/router'

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
    return response.data
  },
  (error) => {
    const { response } = error

    const requestUrl = error.config?.url || ''
    const isAuthEndpoint = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register')

    if (response) {
      switch (response.status) {
        case 401:
          if (!isAuthEndpoint) {
            useAuthStore().logout()
            toast.error('登录已过期，请重新登录')
            router.replace('/login')
          }
          break
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
