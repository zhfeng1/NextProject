import { ref, onUnmounted } from 'vue'
import { io, Socket } from 'socket.io-client'
import { useAuthStore } from '@/stores/auth'

export function useWebSocket(namespace: string = '/') {
  const socket = ref<Socket | null>(null)
  const connected = ref(false)
  const authStore = useAuthStore()

  const connect = () => {
    socket.value = io(`ws://localhost:18080${namespace}`, {
      auth: {
        token: authStore.token,
      },
      transports: ['websocket'],
    })

    socket.value.on('connect', () => {
      connected.value = true
      console.log('WebSocket 已连接')
    })

    socket.value.on('disconnect', () => {
      connected.value = false
      console.log('WebSocket 已断开')
    })

    socket.value.on('error', (error) => {
      console.error('WebSocket 错误:', error)
    })
  }

  const disconnect = () => {
    if (socket.value) {
      socket.value.disconnect()
      socket.value = null
    }
  }

  const emit = (event: string, data: any) => {
    if (socket.value && connected.value) {
      socket.value.emit(event, data)
    }
  }

  const on = (event: string, callback: (...args: any[]) => void) => {
    if (socket.value) {
      socket.value.on(event, callback)
    }
  }

  const off = (event: string, callback?: (...args: any[]) => void) => {
    if (socket.value) {
      socket.value.off(event, callback)
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    socket,
    connected,
    connect,
    disconnect,
    emit,
    on,
    off,
  }
}
