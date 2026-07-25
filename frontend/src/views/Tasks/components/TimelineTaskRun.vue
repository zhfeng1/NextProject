<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  tasksAPI,
  type ExecutionDetailEvent,
  type TaskProviderOutput,
} from '@/api/tasks'
import { useTaskLogs } from '@/composables/useTaskLogs'
import type { Task } from '@/types/models'
import { programmingToolLabel } from '@/api/programmingTools'
import AiOutputStream from '@/components/AiOutputStream.vue'
import {
  Bot,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Loader2,
  Radio,
  RotateCcw,
  Square,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const props = defineProps<{
  taskId: string
  snapshot?: Partial<Task>
  provider?: string
  repoNames?: string[]
  createdAt?: string | null
}>()

const emit = defineEmits<{
  (e: 'statusChange', taskId: string, status: string, task: Task | null): void
}>()

const taskIdRef = computed(() => props.taskId)
const task = ref<Partial<Task>>({ ...(props.snapshot || {}) })
const executionExpanded = ref(false)
const loadingTask = ref(false)
const canceling = ref(false)
const retrying = ref(false)
const output = ref<TaskProviderOutput | null>(null)
const outputLoading = ref(false)
const executionEvents = ref<ExecutionDetailEvent[]>([])
const afterLogId = ref(0)
const afterTraceSeq = ref(0)
const executionHasMore = ref(false)
const executionComplete = ref(false)
const executionRedacted = ref(false)
const executionLoading = ref(false)
const executionError = ref('')
const executionContainerRef = ref<HTMLElement | null>(null)
let poller: ReturnType<typeof setInterval> | null = null
let executionPoller: ReturnType<typeof setInterval> | null = null

const {
  status: wsStatus,
  providerOutput: liveProviderOutput,
  connectionState,
  connect,
  disconnect,
} = useTaskLogs(taskIdRef)

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
  canceled: '已取消',
}

const STATUS_TONE: Record<string, string> = {
  queued: 'muted',
  running: 'warning',
  success: 'success',
  failed: 'danger',
  canceled: 'muted',
}

const terminalStatuses = ['success', 'failed', 'canceled']

const currentStatus = computed(() => wsStatus.value || task.value.status || props.snapshot?.status || 'queued')
const statusTone = computed(() => STATUS_TONE[currentStatus.value] || 'muted')
const isActive = computed(() => ['queued', 'running'].includes(currentStatus.value))
const hasProviderOutput = computed(() => Boolean(task.value.provider || props.provider))
const canRetry = computed(() => ['failed', 'canceled'].includes(String(currentStatus.value)))
const repositories = computed(() => task.value.repositories || props.snapshot?.repositories || [])
const displayRepos = computed(() => {
  const names = repositories.value.map((repo: any) => repo.name || repo.site_id).filter(Boolean)
  return names.length ? names : (props.repoNames || [])
})
const taskSummary = computed(() => {
  if (task.value.error || currentStatus.value === 'failed') return '本轮执行失败，可展开执行日志查看诊断信息。'
  if (currentStatus.value === 'running') return '编程工具正在处理任务…'
  if (currentStatus.value === 'success') return '本轮任务已经完成。'
  if (currentStatus.value === 'canceled') return '本轮任务已取消。'
  return '任务正在等待执行。'
})
const providerOutputText = computed(() => {
  if (output.value?.available && output.value.content) return output.value.content
  return ''
})
const providerOutputEmptyText = computed(() => {
  if (outputLoading.value && !output.value) return '正在同步 AI 输出…'
  if (isActive.value) return '等待编程工具输出面向用户的说明…'
  return '暂无可展示输出'
})

function displayDate(value?: string | null) {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

function providerLabel(provider?: string) {
  return programmingToolLabel(provider)
}

function shortSha(sha?: string) {
  return sha ? String(sha).slice(0, 8) : '-'
}

async function refreshTask() {
  if (!props.taskId) return
  loadingTask.value = true
  try {
    const res = await tasksAPI.get(props.taskId)
    task.value = res.task || task.value
    const terminal = terminalStatuses.includes(String(task.value.status || ''))
    if (hasProviderOutput.value && (connectionState.value !== 'connected' || terminal)) {
      await loadOutput(true, true)
    }
    emit('statusChange', props.taskId, String(task.value.status || ''), res.task || null)
    if (terminal) stopPolling()
  } catch {
    stopPolling()
  } finally {
    loadingTask.value = false
  }
}

function startPolling() {
  stopPolling()
  if (terminalStatuses.includes(String(currentStatus.value))) return
  poller = setInterval(refreshTask, 4000)
}

function stopPolling() {
  if (poller) {
    clearInterval(poller)
    poller = null
  }
}

function resetExecutionDetails() {
  executionEvents.value = []
  afterLogId.value = 0
  afterTraceSeq.value = 0
  executionHasMore.value = false
  executionComplete.value = false
  executionRedacted.value = false
  executionError.value = ''
}

async function loadExecutionDetails() {
  if (!executionExpanded.value || executionLoading.value || executionComplete.value) return
  executionLoading.value = true
  executionError.value = ''
  try {
    const response = await tasksAPI.getExecutionDetails(
      props.taskId,
      afterLogId.value,
      afterTraceSeq.value,
    )
    const seen = new Set(executionEvents.value.map(event => `${event.source}:${event.seq}`))
    const additions = response.events.filter(event => !seen.has(`${event.source}:${event.seq}`))
    if (additions.length) executionEvents.value.push(...additions)
    afterLogId.value = Math.max(afterLogId.value, Number(response.next_after_log_id || 0))
    afterTraceSeq.value = Math.max(afterTraceSeq.value, Number(response.next_after_trace_seq || 0))
    executionHasMore.value = Boolean(response.has_more)
    executionComplete.value = Boolean(response.complete)
    executionRedacted.value = executionRedacted.value || Boolean(response.redacted)

    await nextTick()
    if (executionContainerRef.value) {
      executionContainerRef.value.scrollTop = executionContainerRef.value.scrollHeight
    }
    if (executionComplete.value) stopExecutionPolling()
  } catch (error: any) {
    executionError.value = error?.response?.data?.detail || '执行详情暂时无法加载，将自动重试。'
  } finally {
    executionLoading.value = false
  }
}

function startExecutionPolling() {
  stopExecutionPolling()
  if (!executionExpanded.value || executionComplete.value) return
  void loadExecutionDetails()
  executionPoller = setInterval(() => {
    void loadExecutionDetails()
  }, 1000)
}

function stopExecutionPolling() {
  if (executionPoller) {
    clearInterval(executionPoller)
    executionPoller = null
  }
}

async function cancelTask() {
  if (!props.taskId || canceling.value) return
  canceling.value = true
  try {
    const res: any = await tasksAPI.cancel(props.taskId)
    if (res?.task) task.value = res.task
    toast.success('已发送停止请求')
    await refreshTask()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '停止任务失败')
  } finally {
    canceling.value = false
  }
}

async function retryTask() {
  if (!props.taskId || retrying.value) return
  retrying.value = true
  try {
    const res = await tasksAPI.retry(props.taskId)
    if (res?.task) {
      task.value = res.task
      wsStatus.value = String(res.task.status || 'queued')
      emit('statusChange', props.taskId, String(res.task.status || 'queued'), res.task)
    }
    output.value = null
    resetExecutionDetails()
    toast.success('已重新排队')
    await refreshTask()
    void connect()
    startPolling()
    if (executionExpanded.value) startExecutionPolling()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '重试任务失败')
  } finally {
    retrying.value = false
  }
}

async function loadOutput(force = false, silent = false) {
  if (!hasProviderOutput.value || (!force && output.value) || outputLoading.value) return
  outputLoading.value = true
  try {
    output.value = await tasksAPI.getProviderOutput(props.taskId)
  } catch (error: any) {
    if (!silent) toast.error(error?.response?.data?.detail || '加载 AI 输出失败')
  } finally {
    outputLoading.value = false
  }
}

watch(executionExpanded, (open) => {
  if (open) {
    startExecutionPolling()
  } else {
    stopExecutionPolling()
  }
})

watch(liveProviderOutput, (value) => {
  if (!value) return
  output.value = {
    task_id: props.taskId,
    provider: String(task.value.provider || props.provider || ''),
    available: value.available,
    content: value.content,
    truncated: value.truncated,
  }
})

watch(wsStatus, (value) => {
  if (value) {
    task.value = { ...task.value, status: value }
    emit('statusChange', props.taskId, value, task.value as Task)
  }
})

onMounted(async () => {
  void connect()
  await refreshTask()
  await loadOutput()
  if (isActive.value) startPolling()
})

onUnmounted(() => {
  stopPolling()
  stopExecutionPolling()
  disconnect()
})
</script>

<template>
  <div class="max-w-[min(48rem,92%)]">
    <div class="rounded-lg border bg-card shadow-none">
      <div class="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div class="min-w-0 space-y-1">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <span class="status-dot" :data-tone="statusTone" :data-pulse="currentStatus === 'running'" />
            <span class="text-sm font-semibold">{{ STATUS_LABEL[currentStatus] || currentStatus }}</span>
            <Badge variant="secondary">{{ providerLabel(task.provider || provider) }}</Badge>
            <span class="font-mono-data text-xs text-muted-foreground">{{ taskId.slice(0, 8) }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{{ displayDate(task.created_at || createdAt) }}</span>
            <span v-if="loadingTask" class="inline-flex items-center gap-1">
              <Loader2 class="size-3 animate-spin" />
              同步中
            </span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <Button
            v-if="canRetry"
            size="sm"
            variant="outline"
            :disabled="retrying"
            @click="retryTask"
          >
            <RotateCcw class="size-3.5" :class="retrying ? 'animate-spin' : ''" />
            重试
          </Button>
          <Button
            v-if="isActive"
            size="sm"
            variant="outline"
            class="text-destructive hover:text-destructive"
            :disabled="canceling"
            @click="cancelTask"
          >
            <Square class="size-3.5" />
            停止本轮
          </Button>
          <Button
            size="sm"
            variant="ghost"
            :aria-expanded="executionExpanded"
            aria-controls="task-execution-details"
            @click="executionExpanded = !executionExpanded"
          >
            <ChevronDown v-if="executionExpanded" class="size-4" />
            <ChevronRight v-else class="size-4" />
            {{ executionExpanded ? '收起执行日志' : '执行日志' }}
          </Button>
        </div>
      </div>

      <div class="space-y-3 px-4 py-3 text-sm">
        <div class="flex min-w-0 flex-wrap gap-1.5">
          <Badge v-for="name in displayRepos" :key="name" variant="outline" class="max-w-full truncate">
            {{ name }}
          </Badge>
          <Badge v-if="!displayRepos.length" variant="outline">未记录仓库</Badge>
        </div>
        <div
          class="rounded-md bg-muted/40 px-3 py-2 text-xs leading-relaxed text-muted-foreground"
          :class="task.error ? 'text-destructive' : ''"
        >
          {{ taskSummary }}
        </div>
      </div>

      <section v-if="hasProviderOutput" class="space-y-2 border-t px-4 py-4">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-sm font-medium">
            <Bot class="size-4 text-muted-foreground" />
            AI 输出
          </div>
          <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span class="status-dot" :data-tone="connectionState === 'connected' ? 'success' : 'muted'" :data-pulse="isActive" />
            {{ connectionState === 'connected' ? '实时同步' : '轮询同步' }}
          </span>
        </div>
        <div class="max-h-80 overflow-auto rounded-lg border bg-muted/20 p-3">
          <AiOutputStream
            :content="providerOutputText"
            :empty-text="providerOutputEmptyText"
            :active="isActive"
            compact
          />
        </div>
        <div v-if="output?.truncated" class="text-xs text-warning">内容较长，当前仅展示最近一部分。</div>
      </section>

      <div
        v-if="executionExpanded"
        id="task-execution-details"
        class="border-t px-4 py-4"
      >
        <section class="space-y-2">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-sm font-medium">
              <Radio class="size-4 text-muted-foreground" />
              执行日志
            </div>
            <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span class="status-dot" :data-tone="connectionState === 'connected' ? 'success' : connectionState === 'disconnected' ? 'muted' : 'warning'" />
              {{ connectionState === 'connected' ? '已连接' : connectionState === 'disconnected' ? '未连接' : '连接中' }}
            </span>
          </div>
          <div
            v-if="executionRedacted"
            class="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-muted-foreground"
          >
            部分敏感信息已隐藏。
          </div>
          <div ref="executionContainerRef" class="terminal h-64 overflow-y-auto rounded-md px-3 py-2 text-[11px] leading-relaxed">
            <div v-for="event in executionEvents" :key="`${event.source}:${event.seq}`" class="mb-1 flex gap-2">
              <span class="terminal-time shrink-0">{{ String(event.ts || '').slice(11, 19) }}</span>
              <span
                class="shrink-0 font-bold"
                :class="{
                  'terminal-info': event.level === 'INFO',
                  'terminal-warn': event.level === 'WARN',
                  'terminal-error': event.level === 'ERROR',
                }"
              >[{{ event.level }}]</span>
              <span class="whitespace-pre-wrap break-words">{{ event.content }}</span>
            </div>
            <div v-if="executionError" class="pt-24 text-center text-xs text-red-400">{{ executionError }}</div>
            <div v-else-if="!executionEvents.length && executionLoading" class="pt-24 text-center text-xs text-zinc-600">加载执行日志...</div>
            <div v-else-if="!executionEvents.length && executionComplete" class="pt-24 text-center text-xs text-zinc-600">暂无执行日志</div>
            <div v-else-if="!executionEvents.length" class="pt-24 text-center text-xs text-zinc-600">等待执行日志...</div>
          </div>
          <div v-if="executionHasMore && !executionComplete" class="text-xs text-muted-foreground">正在继续加载后续日志…</div>
        </section>
      </div>

      <section class="space-y-2 border-t px-4 py-4">
        <div class="flex items-center gap-2 text-sm font-medium">
          <GitBranch class="size-4 text-muted-foreground" />
          仓库变更
        </div>
        <div class="divide-y rounded-md border">
          <div v-for="repo in repositories" :key="repo.site_id" class="grid gap-1 px-3 py-2 text-xs sm:grid-cols-[1fr_auto]">
            <div class="min-w-0">
              <div class="truncate font-medium">{{ repo.name || repo.site_id }}</div>
              <div class="font-mono-data text-muted-foreground">
                before {{ shortSha(repo.before_sha) }} · after {{ shortSha(repo.after_sha) }}
              </div>
            </div>
            <span class="inline-flex items-center gap-1 text-muted-foreground">
              <span class="status-dot" :data-tone="repo.changed ? 'success' : 'muted'" />
              {{ repo.changed ? '有变更' : '无变更' }}
            </span>
          </div>
          <div v-if="!repositories.length" class="px-3 py-6 text-center text-xs text-muted-foreground">
            暂无仓库变更记录
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
