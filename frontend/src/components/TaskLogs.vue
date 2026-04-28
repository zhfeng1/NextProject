<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, toRef } from 'vue'
import { useTaskLogs } from '@/composables/useTaskLogs'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  taskId: string
}>()

const emit = defineEmits<{
  (e: 'statusChange', status: string): void
}>()

const taskIdRef = toRef(props, 'taskId')
const autoScroll = ref(true)
const logContainerRef = ref<HTMLElement | null>(null)

const {
  logs,
  status,
  connectionState,
  historyLoaded,
  connect,
  clear,
} = useTaskLogs(taskIdRef)

// Connection status indicator
const connectionLabel = computed(() => {
  switch (connectionState.value) {
    case 'connected': return '已连接'
    case 'connecting': return '连接中...'
    case 'reconnecting': return '重连中...'
    case 'disconnected': return '已断开'
    default: return ''
  }
})

const connectionColor = computed(() => {
  switch (connectionState.value) {
    case 'connected': return 'bg-emerald-500'
    case 'connecting':
    case 'reconnecting': return 'bg-amber-500 animate-pulse'
    case 'disconnected': return 'bg-zinc-500'
    default: return 'bg-zinc-500'
  }
})

// Auto-scroll when new logs arrive
watch(() => logs.value.length, () => {
  if (autoScroll.value) {
    scrollToBottom()
  }
})

// Emit status changes to parent
watch(status, (newStatus) => {
  if (newStatus) {
    emit('statusChange', newStatus)
  }
})

// Connect on mount
onMounted(() => {
  connect()
})

const scrollToBottom = async () => {
  await nextTick()
  if (logContainerRef.value) {
    logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight
  }
}

const clearLogs = () => {
  clear()
}

const formatTime = (ts: string) => {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}
</script>

<template>
  <Card class="flex flex-col h-full overflow-hidden">
    <CardHeader class="flex flex-row items-center justify-between border-b px-4 py-3 bg-muted/50">
      <div class="flex items-center gap-2">
        <CardTitle class="text-sm font-medium">任务日志</CardTitle>
        <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span class="inline-block w-2 h-2 rounded-full" :class="connectionColor" />
          {{ connectionLabel }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="clearLogs">清空</Button>
        <Button
          size="sm"
          :variant="autoScroll ? 'default' : 'secondary'"
          @click="autoScroll = !autoScroll"
        >
          自动滚动
        </Button>
      </div>
    </CardHeader>
    <CardContent class="p-0 flex-1 overflow-hidden relative">
      <div
        class="absolute inset-0 overflow-y-auto bg-zinc-950 text-zinc-300 p-4 font-mono text-xs leading-relaxed"
        ref="logContainerRef"
      >
        <div
          v-for="log in logs"
          :key="log.id"
          class="mb-1 flex gap-2"
        >
          <span class="text-zinc-500 whitespace-nowrap">{{ formatTime(log.ts) }}</span>
          <span
            class="font-bold whitespace-nowrap"
            :class="{
              'text-sky-400': log.level === 'INFO',
              'text-orange-400': log.level === 'WARN',
              'text-red-400': log.level === 'ERROR'
            }"
          >
            [{{ log.level }}]
          </span>
          <span class="whitespace-pre-wrap">{{ log.line }}</span>
        </div>
        <div v-if="logs.length === 0 && historyLoaded" class="h-full flex items-center justify-center text-zinc-600">
          暂无日志
        </div>
        <div v-else-if="logs.length === 0 && !historyLoaded" class="h-full flex items-center justify-center text-zinc-600">
          <span v-if="connectionState === 'connecting' || connectionState === 'reconnecting'">
            正在连接...
          </span>
          <span v-else>
            等待日志...
          </span>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
