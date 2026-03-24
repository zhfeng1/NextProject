<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from '@/composables/useWebSocket'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface LogEntry {
  ts: string
  level: string
  line: string
}

const props = defineProps<{
  taskId: string
}>()

const logs = ref<LogEntry[]>([])
const autoScroll = ref(true)
const logContainerRef = ref<HTMLElement | null>(null)

const { connect, disconnect, on, off } = useWebSocket('/ws')

onMounted(() => {
  connect()
  on(`task:${props.taskId}:log`, (log: LogEntry) => {
    logs.value.push(log)
    if (autoScroll.value) {
      scrollToBottom()
    }
  })
})

onUnmounted(() => {
  off(`task:${props.taskId}:log`)
  disconnect()
})

const scrollToBottom = async () => {
  await nextTick()
  if (logContainerRef.value) {
    logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight
  }
}

const clearLogs = () => {
  logs.value = []
}

watch(() => props.taskId, () => {
  logs.value = []
})
</script>

<template>
  <Card class="flex flex-col h-full overflow-hidden">
    <CardHeader class="flex flex-row items-center justify-between border-b px-4 py-3 bg-muted/50">
      <CardTitle class="text-sm font-medium">任务日志</CardTitle>
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
          v-for="(log, index) in logs"
          :key="index"
          class="mb-1 flex gap-2"
        >
          <span class="text-zinc-500 whitespace-nowrap">{{ log.ts }}</span>
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
        <div v-if="logs.length === 0" class="h-full flex items-center justify-center text-zinc-600">
          暂无日志
        </div>
      </div>
    </CardContent>
  </Card>
</template>
