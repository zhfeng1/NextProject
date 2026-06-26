<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { tasksAPI, type TaskLog } from '@/api/tasks'
import { projectsAPI } from '@/api/projects'
import type { Project, Task } from '@/types/models'
import { RotateCcw, Search, XCircle, RefreshCw, GitBranch, ClipboardList } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const BOARD_COLUMNS = [
  { key: 'todo', label: '待办', tone: 'muted' },
  { key: 'queued', label: '排队', tone: 'muted' },
  { key: 'running', label: '运行中', tone: 'warning' },
  { key: 'review', label: '待验收', tone: 'primary' },
  { key: 'done', label: '完成', tone: 'success' },
  { key: 'failed', label: '失败', tone: 'danger' },
  { key: 'canceled', label: '取消', tone: 'muted' },
]

const STAGE_LABELS: Record<string, string> = {
  research: '研究',
  ideate: '构思',
  plan: '计划',
  execute: '执行',
  optimize: '优化',
  review: '评审',
}

const filters = ref({ project_id: '', repo_id: '', provider: '', board_status: '', priority: '', keyword: '' })
const projects = ref<Project[]>([])
const tasks = ref<Task[]>([])
const selectedTask = ref<Task | null>(null)
const taskLogs = ref<TaskLog[]>([])
const logsRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const mutating = ref(false)
let ws: WebSocket | null = null

const availableRepos = computed(() => {
  const selectedProject = projects.value.find(project => project.id === filters.value.project_id)
  return selectedProject?.repos || projects.value.flatMap(project => project.repos || [])
})

const groupedTasks = computed(() => {
  const groups: Record<string, Task[]> = Object.fromEntries(BOARD_COLUMNS.map(column => [column.key, []]))
  for (const task of tasks.value) {
    const key = task.board_status || 'queued'
    if (!groups[key]) groups[key] = []
    groups[key].push(task)
  }
  return groups
})

function shortSha(sha: string) {
  return sha ? sha.slice(0, 8) : '-'
}

function displayDate(value?: string | null) {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

function promptOf(task: Task | null) {
  if (!task) return ''
  const payload = task.payload || {}
  return String(payload.prompt || payload.instruction || task.description || task.title || '')
}

function priorityTone(priority?: string): 'danger' | 'warning' | 'muted' {
  return ({ urgent: 'danger', high: 'warning', medium: 'muted', low: 'muted' } as const)[priority as 'urgent'] ?? 'muted'
}

async function loadData() {
  loading.value = true
  try {
    const [taskRes, projectRes] = await Promise.all([
      tasksAPI.list({ ...filters.value, limit: 300 }),
      projectsAPI.list(),
    ])
    tasks.value = taskRes.tasks || []
    projects.value = projectRes.projects || []
    if (selectedTask.value) {
      const fresh = tasks.value.find(task => task.id === selectedTask.value?.id)
      if (fresh) selectedTask.value = fresh
    }
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '加载任务看板失败')
  } finally {
    loading.value = false
  }
}

async function selectTask(task: Task) {
  try {
    const detail = await tasksAPI.get(task.id)
    selectedTask.value = detail.task
  } catch {
    selectedTask.value = task
  }
  taskLogs.value = []
  try {
    const res = await tasksAPI.getLogs(task.id, 0)
    taskLogs.value = res.logs || []
    scrollLogs()
  } catch {}
  if (ws) { ws.close(); ws = null }
  if (['queued', 'running'].includes(task.status)) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${task.id}/logs`)
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'log' && msg.data) {
          taskLogs.value.push({
            id: msg.data.id || Date.now() + Math.random(),
            ts: msg.data.ts || new Date().toISOString(),
            level: msg.data.level || 'INFO',
            line: msg.data.line || '',
          })
          scrollLogs()
        }
        if (msg.type === 'status') {
          loadData()
        }
      } catch {}
    }
  }
}

function scrollLogs() {
  setTimeout(() => {
    if (logsRef.value) logsRef.value.scrollTop = logsRef.value.scrollHeight
  }, 40)
}

async function moveTask(status: string) {
  if (!selectedTask.value || mutating.value) return
  mutating.value = true
  try {
    const res = await tasksAPI.updateBoardStatus(selectedTask.value.id, status)
    selectedTask.value = res.task
    await loadData()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '状态更新失败')
  } finally {
    mutating.value = false
  }
}

async function rollbackTask() {
  if (!selectedTask.value || mutating.value) return
  if (!window.confirm('确认回滚该任务涉及的所有仓库到任务开始前检查点吗？')) return
  mutating.value = true
  try {
    const res = await tasksAPI.rollback(selectedTask.value.id)
    selectedTask.value = res.task
    toast.success('任务已回滚到检查点')
    await loadData()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '回滚失败')
  } finally {
    mutating.value = false
  }
}

async function cancelTask() {
  if (!selectedTask.value || mutating.value) return
  mutating.value = true
  try {
    await tasksAPI.cancel(selectedTask.value.id)
    await loadData()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '取消失败')
  } finally {
    mutating.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">任务看板</h1>
        <p class="mt-1 text-sm text-muted-foreground">按项目、仓库、工具和状态维护多仓任务</p>
      </div>
      <Button variant="outline" :disabled="loading" @click="loadData">
        <RefreshCw class="size-4" :class="loading ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>

    <!-- Filters -->
    <div class="grid gap-3 rounded-xl border bg-card p-3 md:grid-cols-3 xl:grid-cols-6">
      <div class="relative md:col-span-2 xl:col-span-2">
        <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input v-model="filters.keyword" class="pl-8" placeholder="搜索标题、描述、任务类型" @keyup.enter="loadData" />
      </div>
      <select v-model="filters.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring" @change="filters.repo_id = ''; loadData()">
        <option value="">全部项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
      </select>
      <select v-model="filters.repo_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring" @change="loadData">
        <option value="">全部仓库</option>
        <option v-for="repo in availableRepos" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
      </select>
      <select v-model="filters.provider" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring" @change="loadData">
        <option value="">全部工具</option>
        <option value="codex">Codex</option>
        <option value="claude_code">Claude Code</option>
        <option value="gemini_cli">Gemini CLI</option>
      </select>
      <select v-model="filters.priority" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring" @change="loadData">
        <option value="">全部优先级</option>
        <option value="urgent">紧急</option>
        <option value="high">高</option>
        <option value="medium">中</option>
        <option value="low">低</option>
      </select>
    </div>

    <!-- Board + detail -->
    <div class="flex gap-4 overflow-x-auto pb-3">
      <section
        v-for="column in BOARD_COLUMNS"
        :key="column.key"
        class="flex w-72 shrink-0 flex-col rounded-xl border bg-muted/30"
      >
        <div class="flex items-center justify-between border-b px-3 py-2.5">
          <h2 class="flex items-center gap-1.5 text-sm font-semibold">
            <span class="status-dot" :data-tone="column.tone" />
            {{ column.label }}
          </h2>
          <span class="stat-num text-xs text-muted-foreground">{{ groupedTasks[column.key]?.length || 0 }}</span>
        </div>
        <div class="flex-1 space-y-2 overflow-y-auto p-2">
          <button
            v-for="task in groupedTasks[column.key]"
            :key="task.id"
            class="w-full rounded-lg border bg-card p-3 text-left text-sm shadow-none transition hover:border-primary/50"
            :class="selectedTask?.id === task.id ? 'border-primary ring-1 ring-primary/20' : 'border-border'"
            @click="selectTask(task)"
          >
            <div class="mb-2 flex items-start justify-between gap-2">
              <span class="line-clamp-2 font-medium leading-snug">{{ task.title || promptOf(task) }}</span>
              <span
                v-if="task.priority"
                class="flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium"
                :class="{
                  'border-destructive/30 bg-destructive/10 text-destructive': priorityTone(task.priority) === 'danger',
                  'border-warning/30 bg-warning/10 text-warning': priorityTone(task.priority) === 'warning',
                  'border-border bg-muted text-muted-foreground': priorityTone(task.priority) === 'muted',
                }"
              >{{ task.priority }}</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <Badge variant="secondary">{{ task.provider || 'system' }}</Badge>
              <Badge v-if="task.project_name" variant="outline">{{ task.project_name }}</Badge>
              <Badge v-for="stage in task.workflow_stages" :key="stage" variant="outline">{{ STAGE_LABELS[stage] || stage }}</Badge>
            </div>
            <div class="mt-2 truncate font-mono-data text-xs text-muted-foreground">
              {{ (task.repositories || []).map(repo => repo.name || repo.site_id).join(' / ') || task.site_id }}
            </div>
            <div class="mt-1 font-mono-data text-xs text-muted-foreground">{{ displayDate(task.created_at) }}</div>
          </button>
          <div v-if="!groupedTasks[column.key]?.length" class="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
            暂无任务
          </div>
        </div>
      </section>

      <!-- Detail panel -->
      <aside class="sticky right-0 flex w-[420px] shrink-0 flex-col rounded-xl border bg-card shadow-none">
        <div v-if="!selectedTask" class="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
          <div>
            <ClipboardList class="mx-auto mb-2 size-8 opacity-30" />
            选择一张任务卡查看详情
          </div>
        </div>
        <div v-else class="flex h-full flex-col">
          <div class="border-b p-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h2 class="text-base font-semibold leading-tight">{{ selectedTask.title }}</h2>
                <p class="mt-1 truncate font-mono-data text-xs text-muted-foreground">{{ selectedTask.id }}</p>
              </div>
              <Button variant="ghost" size="icon-sm" class="text-muted-foreground" @click="selectedTask = null">
                <XCircle class="size-4" />
              </Button>
            </div>
            <div class="mt-3 flex flex-wrap gap-2">
              <Badge>{{ selectedTask.board_status }}</Badge>
              <Badge variant="outline">{{ selectedTask.status }}</Badge>
              <Badge variant="secondary">{{ selectedTask.provider }}</Badge>
            </div>
          </div>

          <div class="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
            <div>
              <div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Prompt</div>
              <div class="whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-xs leading-relaxed">{{ promptOf(selectedTask) }}</div>
            </div>

            <div>
              <div class="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">参与仓库与 Git 检查点</div>
              <div class="space-y-2">
                <div v-for="repo in selectedTask.repositories || []" :key="repo.site_id" class="rounded-md border p-3 text-xs">
                  <div class="mb-1.5 flex items-center justify-between gap-2">
                    <span class="flex items-center gap-1.5 font-medium">
                      <GitBranch class="size-3 text-muted-foreground" />
                      {{ repo.name || repo.site_id }}
                    </span>
                    <span class="flex items-center gap-1.5">
                      <span class="status-dot" :data-tone="repo.changed ? 'success' : 'muted'" />
                      {{ repo.changed ? '有提交' : '无变更' }}
                    </span>
                  </div>
                  <div class="font-mono-data text-muted-foreground">before {{ shortSha(repo.before_sha) }} · after {{ shortSha(repo.after_sha) }}</div>
                  <div v-if="repo.rollback_status" class="mt-1 font-mono-data text-muted-foreground">回滚：{{ repo.rollback_status }}</div>
                </div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <Button variant="outline" :disabled="mutating" @click="moveTask('todo')">移到待办</Button>
              <Button variant="outline" :disabled="mutating" @click="moveTask('review')">移到验收</Button>
              <Button v-if="['queued', 'running'].includes(selectedTask.status)" variant="destructive" :disabled="mutating" @click="cancelTask">取消任务</Button>
              <Button variant="outline" :disabled="mutating" @click="rollbackTask">
                <RotateCcw class="size-4" />
                回滚检查点
              </Button>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <div class="text-xs font-medium uppercase tracking-wide text-muted-foreground">日志</div>
              </div>
              <div ref="logsRef" class="terminal h-72 overflow-y-auto px-3 py-2 text-[11px] leading-relaxed">
                <div v-for="log in taskLogs" :key="log.id" class="mb-1 flex gap-2">
                  <span class="terminal-time shrink-0">{{ String(log.ts || '').slice(11, 19) }}</span>
                  <span class="shrink-0 font-bold"
                    :class="{'terminal-info': log.level==='INFO','terminal-warn':log.level==='WARN','terminal-error':log.level==='ERROR'}"
                  >[{{ log.level }}]</span>
                  <span class="whitespace-pre-wrap break-all">{{ log.line }}</span>
                </div>
                <div v-if="!taskLogs.length" class="pt-16 text-center text-xs text-zinc-600">暂无日志</div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
