<script setup lang="ts">
// @ts-nocheck
import { ref, onMounted, computed } from 'vue'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { sitesAPI } from '@/api/sites'
import { tasksAPI } from '@/api/tasks'
import type { Task, TaskLog } from '@/api/tasks'

const sites = ref<any[]>([])
const allTasks = ref<Task[]>([])
const selectedTask = ref<Task | null>(null)
const taskLogs = ref<TaskLog[]>([])
const logsRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const deletingTaskId = ref('')
let ws: WebSocket | null = null

const STATUS_BADGE: Record<string, string> = {
  queued: 'secondary', running: 'default', success: 'outline',
  failed: 'destructive', canceled: 'secondary',
}
const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', success: '成功', failed: '失败', canceled: '已取消',
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await sitesAPI.list()
    sites.value = res.sites || []
    const all: Task[] = []
    for (const s of sites.value) {
      try {
        const tr = await tasksAPI.listBySite(s.site_id, 20)
        if (tr.tasks) all.push(...tr.tasks)
      } catch {}
    }
    all.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
    allTasks.value = all
  } catch {}
  loading.value = false
}

onMounted(async () => {
  await loadTasks()
})

async function selectTask(task: Task) {
  selectedTask.value = task
  taskLogs.value = []
  // 加载已有日志
  try {
    const res = await tasksAPI.getLogs(task.id, 0)
    taskLogs.value = res.logs || []
    scrollLogs()
  } catch {}
  // 如果任务还在运行，连接 WebSocket
  if (ws) { ws.close(); ws = null }
  if (task.status === 'running' || task.status === 'queued') {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${task.id}/logs`)
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'log' && msg.data) {
          taskLogs.value.push({
            id: Date.now() + Math.random(),
            ts: msg.data.ts || new Date().toISOString(),
            level: msg.data.level || 'INFO',
            line: msg.data.line || '',
          })
          scrollLogs()
        } else if (msg.type === 'status') {
          if (selectedTask.value) {
            selectedTask.value = { ...selectedTask.value, status: msg.status }
          }
        }
      } catch {}
    }
  }
}

async function removeTask(task: Task) {
  if (deletingTaskId.value || task.status === 'running' || task.status === 'queued') return
  const ok = window.confirm('确认删除这条任务记录吗？')
  if (!ok) return
  deletingTaskId.value = task.id
  try {
    await tasksAPI.remove(task.id)
    allTasks.value = allTasks.value.filter((item) => item.id !== task.id)
    if (selectedTask.value?.id === task.id) {
      selectedTask.value = null
      taskLogs.value = []
      if (ws) { ws.close(); ws = null }
    }
  } catch (error: any) {
    window.alert(error?.response?.data?.detail || '删除任务失败')
  } finally {
    deletingTaskId.value = ''
  }
}

function scrollLogs() {
  setTimeout(() => {
    if (logsRef.value) logsRef.value.scrollTop = logsRef.value.scrollHeight
  }, 30)
}

function getSiteName(siteId: string) {
  const found = sites.value.find(s => s.id === siteId)
  return found?.name || found?.site_id || siteId.slice(0, 8)
}

function formatPrompt(task: Task) {
  const p = (task as any).payload
  return p?.prompt || p?.instruction || task.task_type
}

const canceling = ref(false)

async function cancelTask() {
  if (!selectedTask.value || canceling.value) return
  canceling.value = true
  try {
    await tasksAPI.cancel(selectedTask.value.id)
    selectedTask.value = { ...selectedTask.value, status: 'canceled' }
    // 同步更新左侧列表
    const idx = allTasks.value.findIndex(t => t.id === selectedTask.value!.id)
    if (idx !== -1) allTasks.value[idx] = { ...allTasks.value[idx], status: 'canceled' }
    if (ws) { ws.close(); ws = null }
  } catch {}
  canceling.value = false
}
</script>

<template>
  <div class="flex gap-4 h-[calc(100vh-5rem)]">

    <!-- 左侧：任务列表 -->
    <div class="w-96 shrink-0 flex flex-col overflow-hidden">
      <h1 class="text-2xl font-bold tracking-tight mb-3">任务列表</h1>
      <div v-if="loading" class="text-muted-foreground text-sm">加载中...</div>
      <div v-else-if="!allTasks.length" class="text-muted-foreground text-sm">暂无任务</div>
      <div v-else class="flex-1 overflow-y-auto space-y-1.5 pr-1">
        <div
          v-for="task in allTasks" :key="task.id"
          @click="selectTask(task)"
          class="p-2.5 rounded-lg border cursor-pointer transition-colors text-sm"
          :class="selectedTask?.id === task.id
            ? 'border-primary bg-primary/5'
            : 'hover:bg-muted/50 border-border'"
        >
          <div class="flex items-center gap-2 mb-1">
            <Badge :variant="STATUS_BADGE[task.status] || 'secondary'" class="text-[10px] h-4 px-1.5">
              {{ STATUS_LABEL[task.status] || task.status }}
            </Badge>
            <span class="text-xs text-muted-foreground">{{ task.provider || task.task_type }}</span>
            <div class="ml-auto flex items-center gap-2">
              <span class="text-xs text-muted-foreground">{{ getSiteName(task.site_id) }}</span>
              <Button
                v-if="task.status !== 'running' && task.status !== 'queued'"
                size="sm"
                variant="ghost"
                class="h-6 px-2 text-[10px] text-muted-foreground hover:text-red-600"
                :disabled="deletingTaskId === task.id"
                @click.stop="removeTask(task)"
              >
                {{ deletingTaskId === task.id ? '删除中...' : '删除' }}
              </Button>
            </div>
          </div>
          <div class="text-xs text-foreground line-clamp-2">{{ formatPrompt(task) }}</div>
          <div class="text-[11px] text-muted-foreground mt-1">
            {{ String(task.created_at || '').slice(0, 19).replace('T', ' ') }}
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：任务详情 & 日志 -->
    <div class="flex-1 min-w-0 flex flex-col overflow-hidden">
      <div v-if="!selectedTask" class="flex items-center justify-center h-full text-muted-foreground text-sm">
        点击左侧任务查看详情和日志
      </div>
      <template v-else>
        <!-- 任务信息 -->
        <Card class="shrink-0 mb-3">
          <CardHeader class="py-2 px-3">
            <div class="flex items-center gap-2">
              <CardTitle class="text-sm">任务详情</CardTitle>
              <Badge :variant="STATUS_BADGE[selectedTask.status] || 'secondary'" class="text-[10px] h-4 px-1.5">
                {{ STATUS_LABEL[selectedTask.status] || selectedTask.status }}
              </Badge>
              <span class="text-xs text-muted-foreground">{{ selectedTask.provider }}</span>
              <Button
                v-if="selectedTask.status === 'running' || selectedTask.status === 'queued'"
                size="sm" variant="destructive" class="ml-auto h-6 px-2 text-[11px]"
                :disabled="canceling"
                @click="cancelTask"
              >{{ canceling ? '停止中...' : '停止任务' }}</Button>
              <Button
                v-else
                size="sm"
                variant="outline"
                class="ml-auto h-6 px-2 text-[11px]"
                :disabled="deletingTaskId === selectedTask.id"
                @click="removeTask(selectedTask)"
              >{{ deletingTaskId === selectedTask.id ? '删除中...' : '删除任务' }}</Button>
            </div>
          </CardHeader>
          <CardContent class="px-3 pb-3 space-y-1 text-xs">
            <div><span class="text-muted-foreground">需求：</span>{{ formatPrompt(selectedTask) }}</div>
            <div v-if="selectedTask.error" class="text-red-600">
              <span class="text-muted-foreground">错误：</span>{{ selectedTask.error }}
            </div>
            <div class="text-muted-foreground">
              创建：{{ String(selectedTask.created_at || '').slice(0, 19).replace('T', ' ') }}
              <span v-if="selectedTask.started_at"> · 开始：{{ String(selectedTask.started_at || '').slice(11, 19) }}</span>
              <span v-if="selectedTask.finished_at"> · 结束：{{ String(selectedTask.finished_at || '').slice(11, 19) }}</span>
            </div>
          </CardContent>
        </Card>

        <!-- 日志 -->
        <Card class="flex-1 flex flex-col overflow-hidden">
          <CardHeader class="py-2 px-3 shrink-0">
            <CardTitle class="text-sm">任务日志</CardTitle>
          </CardHeader>
          <CardContent class="px-0 pb-0 flex-1 overflow-hidden">
            <div
              ref="logsRef"
              class="h-full overflow-y-auto bg-zinc-950 px-3 py-2 font-mono text-[11px] leading-relaxed"
            >
              <div v-for="log in taskLogs" :key="log.id" class="flex gap-1.5 mb-0.5">
                <span class="shrink-0 text-zinc-500">{{ String(log.ts || '').slice(11, 19) }}</span>
                <span class="shrink-0 font-bold"
                  :class="{'text-sky-400': log.level==='INFO', 'text-orange-400': log.level==='WARN', 'text-red-400': log.level==='ERROR'}"
                >[{{ log.level }}]</span>
                <span class="text-zinc-300 whitespace-pre-wrap break-all">{{ log.line }}</span>
              </div>
              <div v-if="!taskLogs.length" class="text-zinc-600 text-center pt-16 text-xs">
                {{ selectedTask.status === 'queued' ? '任务排队中，等待执行...' : '暂无日志' }}
              </div>
            </div>
          </CardContent>
        </Card>
      </template>
    </div>
  </div>
</template>
