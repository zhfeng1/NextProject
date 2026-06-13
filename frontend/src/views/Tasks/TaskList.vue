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
import { RotateCcw, Search, XCircle } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const BOARD_COLUMNS = [
  { key: 'todo', label: '待办' },
  { key: 'queued', label: '排队' },
  { key: 'running', label: '运行中' },
  { key: 'review', label: '待验收' },
  { key: 'done', label: '完成' },
  { key: 'failed', label: '失败' },
  { key: 'canceled', label: '取消' },
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
        <h1 class="text-2xl font-bold tracking-tight">任务看板</h1>
        <p class="text-sm text-muted-foreground">按项目、仓库、工具和状态维护多仓任务。</p>
      </div>
      <Button variant="outline" :disabled="loading" @click="loadData">刷新</Button>
    </div>

    <div class="grid gap-3 rounded-lg border bg-background p-3 md:grid-cols-3 xl:grid-cols-6">
      <div class="relative md:col-span-2 xl:col-span-2">
        <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input v-model="filters.keyword" class="pl-8" placeholder="搜索标题、描述、任务类型" @keyup.enter="loadData" />
      </div>
      <select v-model="filters.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="filters.repo_id = ''; loadData()">
        <option value="">全部项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
      </select>
      <select v-model="filters.repo_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadData">
        <option value="">全部仓库</option>
        <option v-for="repo in availableRepos" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
      </select>
      <select v-model="filters.provider" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadData">
        <option value="">全部工具</option>
        <option value="codex">Codex</option>
        <option value="claude_code">Claude Code</option>
        <option value="gemini_cli">Gemini CLI</option>
      </select>
      <select v-model="filters.priority" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadData">
        <option value="">全部优先级</option>
        <option value="urgent">紧急</option>
        <option value="high">高</option>
        <option value="medium">中</option>
        <option value="low">低</option>
      </select>
    </div>

    <div class="flex gap-4 overflow-x-auto pb-3">
      <section
        v-for="column in BOARD_COLUMNS"
        :key="column.key"
        class="flex min-h-[58vh] w-72 shrink-0 flex-col rounded-lg border bg-muted/30"
      >
        <div class="flex items-center justify-between border-b px-3 py-2">
          <h2 class="text-sm font-semibold">{{ column.label }}</h2>
          <Badge variant="secondary">{{ groupedTasks[column.key]?.length || 0 }}</Badge>
        </div>
        <div class="flex-1 space-y-2 overflow-y-auto p-2">
          <button
            v-for="task in groupedTasks[column.key]"
            :key="task.id"
            class="w-full rounded-md border bg-background p-3 text-left text-sm shadow-sm transition hover:border-primary/60"
            :class="selectedTask?.id === task.id ? 'border-primary' : 'border-border'"
            @click="selectTask(task)"
          >
            <div class="mb-2 flex items-start justify-between gap-2">
              <span class="line-clamp-2 font-medium leading-snug">{{ task.title || promptOf(task) }}</span>
              <Badge variant="outline" class="shrink-0">{{ task.priority || 'medium' }}</Badge>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <Badge variant="secondary">{{ task.provider || 'system' }}</Badge>
              <Badge v-if="task.project_name" variant="outline">{{ task.project_name }}</Badge>
              <Badge v-for="stage in task.workflow_stages" :key="stage" variant="outline">{{ STAGE_LABELS[stage] || stage }}</Badge>
            </div>
            <div class="mt-2 text-xs text-muted-foreground">
              {{ (task.repositories || []).map(repo => repo.name || repo.site_id).join(' / ') || task.site_id }}
            </div>
            <div class="mt-1 text-xs text-muted-foreground">{{ displayDate(task.created_at) }}</div>
          </button>
          <div v-if="!groupedTasks[column.key]?.length" class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
            暂无任务
          </div>
        </div>
      </section>

      <aside class="sticky right-0 min-h-[58vh] w-[420px] shrink-0 rounded-lg border bg-background shadow-sm">
        <div v-if="!selectedTask" class="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
          选择一张任务卡查看详情
        </div>
        <div v-else class="flex h-full flex-col">
          <div class="border-b p-4">
            <div class="flex items-start justify-between gap-3">
              <div>
                <h2 class="text-lg font-semibold leading-tight">{{ selectedTask.title }}</h2>
                <p class="mt-1 text-xs text-muted-foreground">{{ selectedTask.id }}</p>
              </div>
              <Button variant="ghost" size="sm" @click="selectedTask = null">
                <XCircle class="h-4 w-4" />
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
              <div class="mb-1 text-xs font-medium text-muted-foreground">Prompt</div>
              <div class="whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs leading-relaxed">{{ promptOf(selectedTask) }}</div>
            </div>

            <div>
              <div class="mb-2 text-xs font-medium text-muted-foreground">参与仓库与 Git 检查点</div>
              <div class="space-y-2">
                <div v-for="repo in selectedTask.repositories || []" :key="repo.site_id" class="rounded-md border p-3 text-xs">
                  <div class="mb-1 flex items-center justify-between gap-2">
                    <span class="font-medium">{{ repo.name || repo.site_id }}</span>
                    <Badge :variant="repo.changed ? 'default' : 'secondary'">{{ repo.changed ? '有提交' : '无变更' }}</Badge>
                  </div>
                  <div class="text-muted-foreground">before {{ shortSha(repo.before_sha) }} · after {{ shortSha(repo.after_sha) }}</div>
                  <div v-if="repo.rollback_status" class="mt-1 text-muted-foreground">回滚: {{ repo.rollback_status }}</div>
                </div>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <Button variant="outline" :disabled="mutating" @click="moveTask('todo')">移到待办</Button>
              <Button variant="outline" :disabled="mutating" @click="moveTask('review')">移到验收</Button>
              <Button v-if="['queued', 'running'].includes(selectedTask.status)" variant="destructive" :disabled="mutating" @click="cancelTask">取消任务</Button>
              <Button variant="outline" :disabled="mutating" @click="rollbackTask">
                <RotateCcw class="mr-2 h-4 w-4" />
                回滚检查点
              </Button>
            </div>

            <Card>
              <CardHeader class="px-3 py-2">
                <CardTitle class="text-sm">日志</CardTitle>
              </CardHeader>
              <CardContent class="px-0 pb-0">
                <div ref="logsRef" class="h-72 overflow-y-auto bg-zinc-950 px-3 py-2 font-mono text-[11px] leading-relaxed">
                  <div v-for="log in taskLogs" :key="log.id" class="mb-1 flex gap-2">
                    <span class="shrink-0 text-zinc-500">{{ String(log.ts || '').slice(11, 19) }}</span>
                    <span class="shrink-0 text-sky-300">[{{ log.level }}]</span>
                    <span class="whitespace-pre-wrap break-all text-zinc-200">{{ log.line }}</span>
                  </div>
                  <div v-if="!taskLogs.length" class="pt-16 text-center text-xs text-zinc-500">暂无日志</div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
