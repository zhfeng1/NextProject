import { ref, watch, onUnmounted, type Ref } from 'vue'
import { tasksAPI, type TaskLog } from '@/api/tasks'

export type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'

export function useTaskLogs(taskId: Ref<string>) {
  const logs = ref<TaskLog[]>([])
  const status = ref<string>('')
  const providerOutput = ref<{ available: boolean; content: string; truncated: boolean } | null>(null)
  const connectionState = ref<ConnectionState>('disconnected')
  const historyLoaded = ref(false)

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECT_DELAY = 30000
  let disposed = false
  let connectionGeneration = 0

  function getLastLogId(): number {
    if (logs.value.length === 0) return 0
    return Math.max(...logs.value.map(l => l.id || 0))
  }

  function buildWsUrl(afterId: number, ticket: string): string {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({
      ticket,
      after_id: String(afterId),
    })
    return `${protocol}//${location.host}/ws/tasks/${encodeURIComponent(taskId.value)}/logs?${params.toString()}`
  }

  async function connect() {
    if (!taskId.value) return
    disposed = false
    const generation = ++connectionGeneration
    const connectingTaskId = taskId.value
    cleanup()

    const afterId = getLastLogId()
    connectionState.value = reconnectAttempts > 0 ? 'reconnecting' : 'connecting'

    let ticket: string
    try {
      const response = await tasksAPI.createWsTicket(connectingTaskId)
      ticket = response.ticket
    } catch (err) {
      if (generation !== connectionGeneration || disposed) return
      console.warn('[useTaskLogs] Failed to acquire WebSocket ticket:', err)
      scheduleReconnect()
      return
    }

    if (
      generation !== connectionGeneration
      || disposed
      || taskId.value !== connectingTaskId
    ) return

    let socket: WebSocket
    try {
      socket = new WebSocket(buildWsUrl(afterId, ticket))
      ws = socket
    } catch {
      scheduleReconnect()
      return
    }

    socket.onopen = () => {
      if (socket !== ws) return
      connectionState.value = 'connected'
      reconnectAttempts = 0
    }

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'log':
            if (msg.data) {
              const entry: TaskLog = {
                id: msg.data.id,
                ts: msg.data.ts || '',
                level: msg.data.level || 'INFO',
                line: msg.data.line || '',
              }
              // Deduplicate by id
              if (!entry.id || !logs.value.some(l => l.id === entry.id)) {
                logs.value.push(entry)
              }
            }
            break
          case 'status':
            status.value = msg.status || ''
            break
          case 'provider_output':
            if (msg.data) {
              providerOutput.value = {
                available: Boolean(msg.data.available),
                content: String(msg.data.content || ''),
                truncated: Boolean(msg.data.truncated),
              }
            }
            break
          case 'history_end':
            historyLoaded.value = true
            break
          case 'ping':
            socket.send(JSON.stringify({ type: 'pong' }))
            break
          case 'error':
            console.warn('[useTaskLogs] Server error:', msg.message)
            break
        }
      } catch (err) {
        console.warn('[useTaskLogs] Failed to parse message:', err)
      }
    }

    socket.onclose = () => {
      if (socket !== ws) return
      ws = null
      connectionState.value = 'disconnected'
      if (!disposed) {
        scheduleReconnect()
      }
    }

    socket.onerror = () => {
      // onclose will fire after this, which handles reconnection
    }
  }

  function scheduleReconnect() {
    if (disposed) return
    // Don't reconnect if task is in terminal state
    if (['success', 'failed', 'canceled'].includes(status.value)) return

    reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), MAX_RECONNECT_DELAY)
    connectionState.value = 'reconnecting'
    reconnectTimer = setTimeout(() => {
      void connect()
    }, delay)
  }

  function cleanup() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
      ws = null
    }
  }

  function disconnect() {
    disposed = true
    connectionGeneration++
    cleanup()
    connectionState.value = 'disconnected'
  }

  function clear() {
    logs.value = []
    providerOutput.value = null
    historyLoaded.value = false
  }

  /** Fallback: fetch logs via REST API */
  async function fetchLogsREST(afterId = 0) {
    try {
      const res = await tasksAPI.getLogs(taskId.value, afterId)
      if (res.ok && res.logs) {
        for (const log of res.logs) {
          if (!logs.value.some(l => l.id === log.id)) {
            logs.value.push(log)
          }
        }
      }
    } catch (err) {
      console.warn('[useTaskLogs] REST fallback failed:', err)
    }
  }

  // Watch for taskId changes - reset and reconnect
  watch(taskId, (newId, oldId) => {
    if (newId !== oldId) {
      clear()
      status.value = ''
      reconnectAttempts = 0
      disposed = false
      void connect()
    }
  })

  onUnmounted(() => {
    disconnect()
  })

  return {
    logs,
    status,
    providerOutput,
    connectionState,
    historyLoaded,
    connect,
    disconnect,
    clear,
    fetchLogsREST,
  }
}
