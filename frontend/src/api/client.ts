// @ts-nocheck
import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { useAuthStore } from '@/stores/auth'
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

    if (response) {
      switch (response.status) {
        case 401:
          useAuthStore().logout()
          router.replace('/')
          break
        case 403:
          // ElMessage.error('无权限访问')
          alert('没有权限执行此操作')
          break
        case 404:
          // ElMessage.error('请求的资源不存在')
          alert('请求的资源不存在')
          break
        case 500:
          // ElMessage.error('服务器错误，请稍后重试')
          alert('服务器内部错误')
          break
        default:
          const message = response.data.detail || response.data.message || '请求失败';
          // ElMessage.error(response.data.detail || response.data.message || '请求失败')
          alert(`请求失败: ${message}`)
      }
    } else {
      console.warn('Network request failed without response', error)
    }

    return Promise.reject(error)
  }
)

export default client
