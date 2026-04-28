<script setup lang="ts">
// @ts-nocheck
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Card, CardHeader, CardTitle, CardContent,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { sitesAPI } from '@/api/sites'
import { tasksAPI } from '@/api/tasks'
import type { Task, TaskLog } from '@/api/tasks'
import { useIframeBridge } from '@/composables/useIframeBridge'
import SiteFileBrowserDialog from '@/components/SiteFileBrowserDialog.vue'
import SiteWorkflowPanel from '@/components/SiteWorkflowPanel.vue'
import ConversationPanel from '@/components/ConversationPanel.vue'

// ── 路由 ────────────────────────────────────────────────────────────────────
const route = useRoute()
const router = useRouter()
const siteId = computed(() => String(route.params.id))
const previewNonce = ref(Date.now())

// ── 站点信息 ─────────────────────────────────────────────────────────────────
const site = ref<any>(null)
const previewUrl = computed(() => siteId.value ? `/preview/${siteId.value}/?_ts=${previewNonce.value}` : '')
const agentContextUrl = computed(() => buildAgentContextUrl() || currentUrl.value || previewUrl.value)

// ── iframe bridge ────────────────────────────────────────────────────────────
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeKey = ref(0)

const {
  currentUrl, consoleErrors, pickedElement, pickerMode,
  onIframeLoad, togglePicker, clearErrors, clearPicked, reloadIframe,
} = useIframeBridge(iframeRef)

function hardReload() {
  previewNonce.value = Date.now()
  iframeKey.value++
  clearErrors()
}

function buildAgentContextUrl() {
  const raw = (currentUrl.value || '').trim()
  if (!raw) return ''
  const internalBase = String(site.value?.internal_url || '').trim()
  if (!internalBase) return raw

  try {
    const url = new URL(raw, window.location.origin)
    const previewPrefix = `/preview/${siteId.value}`
    if (!url.pathname.startsWith(previewPrefix)) {
      return raw
    }

    const forwardedPath = url.pathname.slice(previewPrefix.length) || '/'
    const normalizedPath = forwardedPath.startsWith('/') ? forwardedPath : `/${forwardedPath}`
    url.searchParams.delete('_ts')
    return `${internalBase}${normalizedPath}${url.search}${url.hash}`
  } catch {
    return raw
  }
}

// ── 需求文档 ─────────────────────────────────────────────────────────────────
const requirementsDoc = ref('')
const showRequirements = ref(false)

async function loadRequirements() {
  try {
    const res = await sitesAPI.getRequirements(siteId.value)
    requirementsDoc.value = res.content || ''
  } catch {}
}

// ── 文件浏览 ─────────────────────────────────────────────────────────────────
const fileBrowserOpen = ref(false)
const fileBrowserRefreshKey = ref(0)

// ── 需求输入 ─────────────────────────────────────────────────────────────────
const userInput = ref('')
const provider = ref('codex')
const PROVIDERS = [
  { value: 'codex', label: 'Codex' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'gemini_cli', label: 'Gemini' },
]
const submitting = ref(false)

async function launchTask(payload: Record<string, unknown>, requirementText = '') {
  resetTaskLogs()
  currentTask.value = null
  taskStatus.value = ''
  try {
    if (requirementText) {
      const reqRes = await sitesAPI.addRequirement(siteId.value, requirementText)
      requirementsDoc.value = reqRes.content || requirementsDoc.value
    }

    const res = await tasksAPI.create(payload)
    currentTask.value = res.task
    connectTaskWS(res.task.id, res.task.status || 'queued')
    refreshTaskHistory()
  } catch (e: any) {
    taskLogs.value.push({
      id: -1, ts: new Date().toISOString(), level: 'ERROR',
      line: e?.response?.data?.detail || '提交失败，请检查网络或配置',
    })
  } finally {}
}

async function submitRequirement() {
  const text = userInput.value.trim()
  if (!text || submitting.value) return
  submitting.value = true
  try {
    const errors = consoleErrors.value.map(e => `[${e.type}] ${e.message}`).join('\n')
    await launchTask({
      site_id: siteId.value,
      task_type: 'develop_code',
      provider: provider.value,
      prompt: text,
      current_url: buildAgentContextUrl(),
      selected_xpath: pickedElement.value?.xpath || '',
      console_errors: errors,
    }, text)
    userInput.value = ''
    clearPicked()
  } finally {
    submitting.value = false
  }
}

function fixErrors() {
  const errText = consoleErrors.value.map(e => `[${e.type}] ${e.message}`).join('\n')
  userInput.value = `请修复以下错误：\n${errText}`
}

// ── 任务日志 & WebSocket + 轮询兜底 ─────────────────────────────────────────
const currentTask = ref<Task | null>(null)
const taskLogs = ref<TaskLog[]>([])
const taskStatus = ref<string>('')
const latestLogId = ref(0)
const logsRef = ref<HTMLElement | null>(null)
const expandedLogsRef = ref<HTMLElement | null>(null)
const providerOutputRef = ref<HTMLElement | null>(null)
const providerOutputOpen = ref(false)
const providerOutput = ref('')
const providerOutputTruncated = ref(false)
let ws: WebSocket | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function stopTaskStream() {
  stopPolling()
  if (ws) { ws.close(); ws = null }
}

function isTerminal(status: string) {
  return ['success', 'failed', 'canceled'].includes(status)
}

function resetTaskLogs() {
  taskLogs.value = []
  latestLogId.value = 0
}

const currentTaskSupportsProviderOutput = computed(() => currentTask.value?.provider === 'codex')

function syncTaskStatus(taskId: string, status: string) {
  taskStatus.value = status
  if (currentTask.value?.id === taskId) {
    currentTask.value = { ...currentTask.value, status }
  }
  const idx = taskHistory.value.findIndex(task => task.id === taskId)
  if (idx !== -1) {
    taskHistory.value[idx] = { ...taskHistory.value[idx], status }
  }
}

function appendLogs(logs: TaskLog[] = [], replace = false) {
  if (replace) {
    taskLogs.value = logs
  } else if (logs.length) {
    const existingIds = new Set(taskLogs.value.map(log => Number(log.id)))
    const freshLogs = logs.filter(log => !existingIds.has(Number(log.id)))
    if (freshLogs.length) taskLogs.value = [...taskLogs.value, ...freshLogs]
  }
  if (logs.length) {
    latestLogId.value = Math.max(latestLogId.value, ...logs.map(log => Number(log.id) || 0))
    scrollLogs()
  }
}

async function fetchTaskLogs(taskId: string, replace = false) {
  try {
    const res = await tasksAPI.getLogs(taskId, replace ? 0 : latestLogId.value)
    appendLogs(res.logs || [], replace)
  } catch {}
}

async function fetchProviderOutput(taskId: string) {
  try {
    const res = await tasksAPI.getProviderOutput(taskId)
    providerOutput.value = res.content || ''
    providerOutputTruncated.value = !!res.truncated
    scrollProviderOutput()
  } catch {}
}

function onTaskFinished(status: string) {
  if (currentTask.value) {
    syncTaskStatus(currentTask.value.id, status)
  } else {
    taskStatus.value = status
  }
  stopTaskStream()
  void refreshTaskHistory()
  if (currentTask.value?.provider === 'codex') {
    void fetchProviderOutput(currentTask.value.id)
  }
  if (status === 'success') {
    setTimeout(() => {
      hardReload()
      fileBrowserRefreshKey.value += 1
    }, 1200)
  }
}

async function pollTaskStatus(taskId: string) {
  try {
    await fetchTaskLogs(taskId)
    const res = await tasksAPI.get(taskId)
    const task = res.task
    if (!task) return
    currentTask.value = task
    syncTaskStatus(task.id, task.status)
    if (providerOutputOpen.value && task.provider === 'codex') {
      await fetchProviderOutput(taskId)
    }
    // 任务已结束
    if (isTerminal(task.status)) {
      await fetchTaskLogs(taskId, true)
      if (task.provider === 'codex') {
        await fetchProviderOutput(taskId)
      }
      onTaskFinished(task.status)
    }
  } catch {}
}

function connectTaskWS(taskId: string, initialStatus = 'queued') {
  stopTaskStream()
  taskStatus.value = initialStatus

  // WebSocket 实时日志（带历史回放 + 心跳）
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const afterId = latestLogId.value
  ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${taskId}/logs?after_id=${afterId}`)
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'log' && msg.data) {
        // 直接使用 WS 数据，不再走 REST
        const entry: TaskLog = {
          id: msg.data.id,
          ts: msg.data.ts || '',
          level: msg.data.level || 'INFO',
          line: msg.data.line || '',
        }
        appendLogs([entry])
      } else if (msg.type === 'status') {
        syncTaskStatus(taskId, msg.status)
        if (isTerminal(msg.status)) {
          onTaskFinished(msg.status)
        }
      } else if (msg.type === 'ping') {
        ws?.send(JSON.stringify({ type: 'pong' }))
      } else if (msg.type === 'history_end') {
        // 历史回放完成，降低轮询频率
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        pollTimer = setInterval(() => pollTaskStatus(taskId), 15000)
      }
    } catch {}
  }
  ws.onclose = () => {
    // WS 断开后恢复快速轮询作为兜底
    if (!isTerminal(taskStatus.value)) {
      stopPolling()
      pollTimer = setInterval(() => pollTaskStatus(taskId), 3000)
    }
  }
  ws.onerror = () => {}

  // 初始轮询兜底（WS 连接建立前保障），WS history_end 后降频
  pollTimer = setInterval(() => pollTaskStatus(taskId), 5000)
  // 立即查一次（应对任务在 WS 连接前就结束的情况）
  setTimeout(() => pollTaskStatus(taskId), 1500)
}

function scrollLogs() {
  setTimeout(() => {
    if (logsRef.value) logsRef.value.scrollTop = logsRef.value.scrollHeight
    if (expandedLogsRef.value) expandedLogsRef.value.scrollTop = expandedLogsRef.value.scrollHeight
  }, 30)
}

function scrollProviderOutput() {
  setTimeout(() => {
    if (providerOutputRef.value) providerOutputRef.value.scrollTop = providerOutputRef.value.scrollHeight
  }, 30)
}

// ── 重启站点 ─────────────────────────────────────────────────────────────────
const restarting = ref(false)

async function restartSite() {
  restarting.value = true
  resetTaskLogs()
  taskStatus.value = ''
  currentTask.value = null
  try {
    const res = await tasksAPI.create({
      site_id: siteId.value,
      task_type: 'deploy_local',
      provider: '',
    })
    currentTask.value = res.task
    connectTaskWS(res.task.id, res.task.status || 'queued')
    refreshTaskHistory()
  } catch {
    taskLogs.value.push({ id: -1, ts: new Date().toISOString(), level: 'ERROR', line: '重启失败' })
  } finally {
    restarting.value = false
  }
}

async function submitWorkflowTask(payload: Record<string, unknown>) {
  await launchTask({
    ...payload,
    current_url: buildAgentContextUrl(),
    selected_xpath: pickedElement.value?.xpath || '',
    console_errors: consoleErrors.value.map(e => `[${e.type}] ${e.message}`).join('\n'),
  })
}

// ── 历史任务 ─────────────────────────────────────────────────────────────────
const taskHistory = ref<Task[]>([])

async function inspectTask(task: Task) {
  const switchedTask = currentTask.value?.id !== task.id
  currentTask.value = task
  taskStatus.value = task.status || ''
  stopTaskStream()
  if (switchedTask) resetTaskLogs()
  providerOutput.value = ''
  providerOutputTruncated.value = false
  await fetchTaskLogs(task.id, true)
  if (task.provider === 'codex') {
    await fetchProviderOutput(task.id)
  }
  if (!isTerminal(task.status)) {
    connectTaskWS(task.id, task.status || 'queued')
  }
}

async function refreshTaskHistory() {
  try {
    const res = await tasksAPI.listBySite(siteId.value, 5)
    taskHistory.value = res.tasks || []
    const activeTask = taskHistory.value.find(task => !isTerminal(task.status))
    if (activeTask && (!currentTask.value || currentTask.value.id === activeTask.id || isTerminal(taskStatus.value))) {
      await inspectTask(activeTask)
    }
  } catch {}
}

const STATUS_BADGE: Record<string, string> = {
  queued: 'secondary', running: 'default', success: 'outline',
  failed: 'destructive', canceled: 'secondary',
}
const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', success: '成功', failed: '失败', canceled: '已取消',
}
const STATUS_BADGE_CLASS: Record<string, string> = {
  queued: 'border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
  running: 'border-sky-400/60 bg-sky-100 text-sky-700 dark:border-sky-500/40 dark:bg-sky-500/15 dark:text-sky-200',
  success: 'border-emerald-500 bg-emerald-100 text-emerald-700 shadow-sm shadow-emerald-500/20 dark:border-emerald-400/50 dark:bg-emerald-500/20 dark:text-emerald-100 dark:shadow-emerald-500/10',
  failed: 'border-red-500/60 bg-red-100 text-red-700 dark:border-red-500/40 dark:bg-red-500/15 dark:text-red-200',
  canceled: 'border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800/80 dark:text-zinc-300',
}

// ── 右侧面板 tab ──────────────────────────────────────────────────────────────
const rightTab = ref<'chat' | 'classic'>('chat')

function onConvTaskCreated(taskId: string) {
  // Switch to classic tab to show task logs, then connect WS
  rightTab.value = 'classic'
  resetTaskLogs()
  currentTask.value = null
  taskStatus.value = ''
  connectTaskWS(taskId, 'queued')
  refreshTaskHistory()
}

// ── 日志放大 ──────────────────────────────────────────────────────────────────
const logsExpanded = ref(false)

// ── 控制台错误面板展开 ────────────────────────────────────────────────────────
const showErrors = ref(false)
watch(consoleErrors, (v) => { if (v.length) showErrors.value = true }, { deep: true })
watch(logsExpanded, (expanded) => {
  if (expanded) scrollLogs()
})
watch(providerOutputOpen, (open) => {
  if (open && currentTask.value?.provider === 'codex') {
    void fetchProviderOutput(currentTask.value.id)
  }
})

// ── 加载状态 & 错误处理 ─────────────────────────────────────────────────────────
const siteLoading = ref(true)
const siteError = ref('')

const hasValidSiteId = computed(() => !!siteId.value && siteId.value.length > 0)

const canOperateOnSite = computed(() => hasValidSiteId.value && !!site.value && !siteError.value)

const siteFailureTitle = computed(() => {
  if (!hasValidSiteId.value) return '站点 ID 无效'
  if (siteError.value) return '加载站点失败'
  return '站点不可用'
})

const siteFailureMessage = computed(() => {
  if (!hasValidSiteId.value) return '当前路径中未包含有效的站点 ID，请从站点列表进入。'
  if (siteError.value) return siteError.value
  return '站点数据加载失败，请稍后重试。'
})

async function loadSite() {
  siteLoading.value = true
  siteError.value = ''
  try {
    const res = await sitesAPI.get(siteId.value)
    site.value = res.site
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    siteError.value = detail || '无法获取站点信息'
  } finally {
    siteLoading.value = false
  }
}

function goBackToSites() {
  router.push({ name: 'SiteList' })
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadSite()
  if (canOperateOnSite.value) {
    await Promise.all([loadRequirements(), refreshTaskHistory()])
  }
})

onUnmounted(() => { stopTaskStream() })
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b bg-background px-4 py-3 shrink-0">
      <div class="min-w-0">
        <div class="text-lg font-semibold text-foreground">
          {{ site?.name || '站点编辑' }}
        </div>
        <div class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span class="font-mono">站点 ID: {{ site?.site_id || siteId || '—' }}</span>
        </div>
      </div>
      <Badge
        :variant="STATUS_BADGE[site?.status] || 'secondary'"
        :class="['text-[11px] h-6 px-2.5 font-medium shrink-0', STATUS_BADGE_CLASS[site?.status] || STATUS_BADGE_CLASS.queued]"
      >
        {{ siteLoading ? '加载中' : (site?.status ? (STATUS_LABEL[site.status] || site.status) : '不可用') }}
      </Badge>
    </div>

    <div v-if="siteLoading" class="flex flex-1 items-center justify-center px-6 text-sm text-muted-foreground">
      正在加载站点信息...
    </div>

    <div v-else-if="!canOperateOnSite" class="flex flex-1 items-center justify-center p-6">
      <Card class="w-full max-w-2xl border-red-200 bg-red-50/60 dark:border-red-900/60 dark:bg-red-950/20">
        <CardHeader class="space-y-2">
          <CardTitle class="text-base text-red-700 dark:text-red-300">{{ siteFailureTitle }}</CardTitle>
        </CardHeader>
        <CardContent class="space-y-4 text-sm">
          <p class="leading-6 text-red-700/90 dark:text-red-200">{{ siteFailureMessage }}</p>
          <div class="rounded-md border border-red-200/80 bg-background/80 px-3 py-2 text-xs text-muted-foreground dark:border-red-900/50">
            <div>当前路径：<span class="font-mono break-all">{{ route.fullPath }}</span></div>
            <div class="mt-1">站点 ID：<span class="font-mono break-all">{{ siteId || '（空）' }}</span></div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button size="sm" @click="loadSite" :disabled="!hasValidSiteId">重试加载</Button>
            <Button size="sm" variant="outline" @click="goBackToSites">返回站点列表</Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <div v-else class="flex overflow-hidden" style="height: calc(100vh - 7rem)">

      <!-- ── 左侧：iframe 预览 ─────────────────────────────────── -->
      <div class="flex flex-col flex-1 min-w-0 border-r">

      <!-- Toolbar -->
      <div class="flex items-center gap-2 h-10 px-2 border-b bg-muted/40 shrink-0">
        <div class="flex-1 min-w-0 flex items-center gap-1 bg-background border rounded px-2 h-7 text-xs text-muted-foreground">
          <span class="opacity-50 shrink-0">🌐</span>
          <span class="truncate">{{ currentUrl || previewUrl }}</span>
        </div>
        <Button size="icon" variant="ghost" class="h-7 w-7 shrink-0" title="刷新" @click="hardReload">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
        </Button>
        <Button
          size="sm" variant="ghost" class="h-7 px-2 text-xs shrink-0 gap-1"
          :class="pickerMode ? 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300' : ''"
          title="选区模式" @click="togglePicker"
        >
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5"/>
          </svg>
          {{ pickerMode ? '取消' : '选区' }}
        </Button>
        <button
          v-if="consoleErrors.length"
          class="flex items-center gap-1 px-2 h-7 rounded text-xs bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 shrink-0"
          @click="showErrors = !showErrors"
        >⚠ {{ consoleErrors.length }}</button>
        <span class="text-xs text-muted-foreground truncate max-w-24 shrink-0">{{ site?.name || siteId }}</span>
      </div>

      <!-- iframe -->
      <div class="flex-1 overflow-hidden relative">
        <iframe
          v-if="previewUrl"
          :key="iframeKey"
          ref="iframeRef"
          :src="previewUrl"
          class="w-full h-full border-0 bg-white"
          :class="pickerMode ? 'cursor-crosshair' : ''"
          @load="onIframeLoad"
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
        />
        <div v-else class="flex items-center justify-center h-full text-muted-foreground text-sm">
          加载站点中...
        </div>
      </div>
      </div>

      <!-- ── 右侧：操作面板 ────────────────────────────────────── -->
      <div class="w-[22rem] shrink-0 flex flex-col overflow-hidden">

        <!-- Tab bar -->
        <div class="flex border-b shrink-0 bg-muted/20">
          <button
            class="flex-1 py-2 text-xs font-medium transition-colors"
            :class="rightTab === 'chat' ? 'border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="rightTab = 'chat'"
          >💬 对话</button>
          <button
            class="flex-1 py-2 text-xs font-medium transition-colors"
            :class="rightTab === 'classic' ? 'border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="rightTab = 'classic'"
          >⚡ 快速</button>
        </div>

        <!-- Chat tab -->
        <div v-if="rightTab === 'chat'" class="flex-1 overflow-hidden">
          <ConversationPanel
            v-if="canOperateOnSite"
            :site-id="siteId"
            :current-url="buildAgentContextUrl()"
            :selected-xpath="pickedElement?.xpath || ''"
            :console-errors="consoleErrors.map(e => `[${e.type}] ${e.message}`).join('\n')"
            :provider="provider"
            @task-created="onConvTaskCreated"
          />
          <div v-else class="flex h-full items-center justify-center px-6 text-sm text-muted-foreground">
            站点未加载成功，暂不可发起对话任务。
          </div>
        </div>

        <!-- Classic tab -->
        <div v-if="rightTab === 'classic'" class="flex-1 overflow-y-auto p-3 space-y-3">

        <!-- ① 需求输入 -->
        <Card>
          <CardHeader class="py-2 px-3 pb-1">
            <CardTitle class="text-sm">需求输入</CardTitle>
          </CardHeader>
          <CardContent class="px-3 pb-3 space-y-2">
            <textarea
              v-model="userInput" rows="4"
              placeholder="描述你想修改的内容，AI 会结合当前页面和历史需求一起处理..."
              class="w-full resize-none rounded border bg-muted/30 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring font-sans"
            />
            <div class="flex gap-1">
              <button
                v-for="p in PROVIDERS" :key="p.value" @click="provider = p.value"
                class="flex-1 py-1 text-xs rounded border transition-colors"
                :class="provider === p.value
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-background hover:bg-muted border-border text-foreground'"
              >{{ p.label }}</button>
            </div>
            <Button class="w-full" size="sm" :disabled="submitting || !userInput.trim() || !canOperateOnSite" @click="submitRequirement">
              {{ submitting ? '提交中...' : '提交给 AI 编码' }}
            </Button>
          </CardContent>
        </Card>

        <SiteWorkflowPanel
          v-if="canOperateOnSite"
          :site-id="siteId"
          :current-url="buildAgentContextUrl()"
          :selected-xpath="pickedElement?.xpath || ''"
          :console-errors="consoleErrors.map(e => `[${e.type}] ${e.message}`).join('\n')"
          @submit-task="submitWorkflowTask"
        />

        <!-- ② 当前上下文 -->
        <Card>
          <CardHeader class="py-2 px-3 pb-1">
            <CardTitle class="text-sm">上下文信息</CardTitle>
          </CardHeader>
          <CardContent class="px-3 pb-3 space-y-2 text-xs">
            <div class="space-y-0.5">
              <span class="text-muted-foreground">当前 URL</span>
              <div class="truncate font-mono bg-muted/40 rounded px-1.5 py-0.5 text-[11px]">
                {{ agentContextUrl || '（等待 iframe 加载）' }}
              </div>
            </div>
            <div v-if="pickedElement">
              <div class="flex items-center justify-between mb-1">
                <span class="text-muted-foreground">选中元素 XPath</span>
                <button class="text-muted-foreground hover:text-foreground text-[11px]" @click="clearPicked">✕ 清除</button>
              </div>
              <div class="font-mono bg-muted/40 rounded px-1.5 py-0.5 text-[11px] break-all mb-1.5">{{ pickedElement.xpath }}</div>
              <img
                v-if="pickedElement.screenshotDataUrl"
                :src="pickedElement.screenshotDataUrl"
                class="rounded border max-h-28 w-auto object-contain"
                alt="元素截图"
              />
              <details v-else>
                <summary class="cursor-pointer text-muted-foreground text-[11px]">查看 outerHTML</summary>
                <pre class="mt-1 bg-muted/40 rounded p-1 overflow-auto max-h-20 text-[10px] whitespace-pre-wrap">{{ pickedElement.outerHTML }}</pre>
              </details>
            </div>
            <div v-else class="text-muted-foreground italic text-[11px]">
              点击工具栏「选区」后在左侧页面点选元素
            </div>
          </CardContent>
        </Card>

        <!-- ③ 控制台错误 -->
        <Card v-if="showErrors || consoleErrors.length">
          <CardHeader class="py-2 px-3 pb-1">
            <div class="flex items-center justify-between">
              <CardTitle class="text-sm flex items-center gap-1.5">
                <span class="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                控制台错误
                <Badge variant="destructive" class="text-[10px] h-4 px-1">{{ consoleErrors.length }}</Badge>
              </CardTitle>
              <div class="flex gap-1">
                <Button size="sm" variant="outline" class="h-6 px-2 text-[11px]" @click="fixErrors">立即修复</Button>
                <Button size="sm" variant="ghost" class="h-6 px-2 text-[11px]" @click="clearErrors">清空</Button>
              </div>
            </div>
          </CardHeader>
          <CardContent class="px-3 pb-3">
            <div class="space-y-1 max-h-36 overflow-y-auto">
              <div
                v-for="(err, i) in consoleErrors" :key="i"
                class="flex gap-1.5 text-[11px] bg-red-50 dark:bg-red-950/30 rounded px-2 py-1"
              >
                <span class="shrink-0 font-bold" :class="err.type === 'network' ? 'text-orange-500' : 'text-red-500'">
                  {{ err.type === 'network' ? 'NET' : 'JS' }}
                </span>
                <span class="text-red-700 dark:text-red-300 break-all flex-1">{{ err.message }}</span>
                <span class="shrink-0 text-muted-foreground">{{ err.time.slice(11, 19) }}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- ④ 任务日志 -->
        <Card v-if="currentTask || taskLogs.length">
          <CardHeader class="py-2 px-3 pb-1">
            <div class="flex items-center justify-between">
              <CardTitle class="text-sm flex items-center gap-1.5">
                任务日志
                <Badge
                  :variant="STATUS_BADGE[taskStatus] || 'secondary'"
                  :class="['text-[11px] h-5 px-2 font-medium', STATUS_BADGE_CLASS[taskStatus]]"
                >
                  {{ STATUS_LABEL[taskStatus] || taskStatus || '—' }}
                </Badge>
              </CardTitle>
              <div class="flex gap-1">
                <Button size="sm" variant="ghost" class="h-6 w-6 p-0" title="放大" @click="logsExpanded = true">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5"/>
                  </svg>
                </Button>
                <Button size="sm" variant="ghost" class="h-6 px-2 text-[11px]" @click="taskLogs = []">清空</Button>
              </div>
            </div>
          </CardHeader>
          <CardContent class="px-0 pb-0">
            <div
              ref="logsRef"
              class="h-52 overflow-y-auto bg-zinc-950 px-3 py-2 font-mono text-[11px] leading-relaxed"
            >
              <div v-for="log in taskLogs" :key="log.id" class="flex gap-1.5 mb-0.5">
                <span class="shrink-0 text-zinc-500">{{ String(log.ts || '').slice(11, 19) }}</span>
                <span class="shrink-0 font-bold"
                  :class="{'text-sky-400': log.level==='INFO','text-orange-400':log.level==='WARN','text-red-400':log.level==='ERROR'}"
                >[{{ log.level }}]</span>
                <span class="text-zinc-300 whitespace-pre-wrap break-all">{{ log.line }}</span>
              </div>
              <div v-if="!taskLogs.length" class="text-zinc-600 text-center pt-10 text-xs">等待任务输出...</div>
            </div>
          </CardContent>
        </Card>

        <!-- ⑤ 历史需求文档 -->
        <Card v-if="requirementsDoc">
          <CardHeader class="py-2 px-3 pb-1 cursor-pointer select-none" @click="showRequirements = !showRequirements">
            <div class="flex items-center justify-between">
              <CardTitle class="text-sm">历史需求文档</CardTitle>
              <span class="text-muted-foreground text-xs">{{ showRequirements ? '▲' : '▼' }}</span>
            </div>
          </CardHeader>
          <CardContent v-if="showRequirements" class="px-3 pb-3">
            <pre class="text-[11px] whitespace-pre-wrap text-muted-foreground bg-muted/30 rounded p-2 max-h-44 overflow-y-auto leading-relaxed">{{ requirementsDoc }}</pre>
          </CardContent>
        </Card>

        <!-- ⑥ 快捷操作 + 最近任务 -->
        <Card>
          <CardHeader class="py-2 px-3 pb-1">
            <CardTitle class="text-sm">快捷操作</CardTitle>
          </CardHeader>
          <CardContent class="px-3 pb-3 space-y-2">
            <Button variant="outline" size="sm" class="w-full text-xs" :disabled="restarting || !canOperateOnSite" @click="restartSite">
              {{ restarting ? '重启中...' : '🔄 重启站点进程' }}
            </Button>
            <Button variant="outline" size="sm" class="w-full text-xs" :disabled="!canOperateOnSite" @click="fileBrowserOpen = true">
              📁 打开文件浏览
            </Button>
            <div v-if="taskHistory.length">
              <Separator class="my-2" />
              <p class="text-xs text-muted-foreground mb-1.5">最近任务</p>
              <div class="space-y-1">
                <button
                  v-for="t in taskHistory" :key="t.id"
                  type="button"
                  class="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-[11px] text-left transition-colors hover:bg-muted/50"
                  :class="currentTask?.id === t.id ? 'bg-muted/60' : ''"
                  @click="inspectTask(t)"
                >
                  <Badge
                    :variant="STATUS_BADGE[t.status] || 'secondary'"
                    :class="['text-[11px] h-5 px-2 font-medium shrink-0', STATUS_BADGE_CLASS[t.status]]"
                  >
                    {{ STATUS_LABEL[t.status] || t.status }}
                  </Badge>
                  <span class="text-muted-foreground truncate">{{ t.provider || t.task_type }}</span>
                  <span class="shrink-0 rounded border border-border/70 px-1.5 py-0.5 text-[10px] text-foreground/80">
                    查看日志
                  </span>
                  <span class="ml-auto shrink-0 text-muted-foreground">{{ String(t.created_at || '').slice(0,16).replace('T',' ') }}</span>
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        </div>
        </div><!-- end classic tab -->
      </div>

    <!-- 日志放大弹窗 -->
    <Teleport to="body">
      <div
        v-if="logsExpanded"
        class="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/70 p-4 backdrop-blur-sm"
        @click.self="logsExpanded = false"
        @keydown.escape="logsExpanded = false"
      >
        <div class="flex h-[min(88vh,60rem)] w-[min(94vw,92rem)] flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
          <div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3 shrink-0">
            <div class="flex items-center gap-2 text-sm text-zinc-300">
              <span class="font-medium">任务日志</span>
              <Badge
                :variant="STATUS_BADGE[taskStatus] || 'secondary'"
                :class="['text-[11px] h-5 px-2 font-medium', STATUS_BADGE_CLASS[taskStatus]]"
              >
                {{ STATUS_LABEL[taskStatus] || taskStatus || '—' }}
              </Badge>
            </div>
            <div class="flex items-center gap-2">
              <Button
                v-if="currentTaskSupportsProviderOutput"
                size="sm"
                variant="ghost"
                class="h-7 px-2 text-xs text-zinc-400 hover:text-zinc-200"
                @click="providerOutputOpen = true"
              >
                Codex 输出
              </Button>
              <Button size="sm" variant="ghost" class="h-7 px-2 text-xs text-zinc-400 hover:text-zinc-200" @click="logsExpanded = false">
                <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
                关闭 (Esc)
              </Button>
            </div>
          </div>
          <div ref="expandedLogsRef" class="flex-1 overflow-y-auto px-5 py-4 font-mono text-xs leading-relaxed">
            <div v-for="log in taskLogs" :key="log.id" class="flex gap-2 mb-0.5">
              <span class="shrink-0 text-zinc-500">{{ String(log.ts || '').slice(11, 19) }}</span>
              <span class="shrink-0 font-bold"
                :class="{'text-sky-400': log.level==='INFO','text-orange-400':log.level==='WARN','text-red-400':log.level==='ERROR'}"
              >[{{ log.level }}]</span>
              <span class="text-zinc-300 whitespace-pre-wrap break-all">{{ log.line }}</span>
            </div>
            <div v-if="!taskLogs.length" class="text-zinc-600 text-center pt-20">等待任务输出...</div>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="providerOutputOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/70 p-4 backdrop-blur-sm"
        @click.self="providerOutputOpen = false"
        @keydown.escape="providerOutputOpen = false"
      >
        <div class="flex h-[min(88vh,60rem)] w-[min(94vw,100rem)] flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
          <div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3 shrink-0">
            <div class="min-w-0">
              <div class="flex items-center gap-2 text-sm text-zinc-300">
                <span class="font-medium">Codex 输出</span>
                <Badge
                  :variant="STATUS_BADGE[taskStatus] || 'secondary'"
                  :class="['text-[11px] h-5 px-2 font-medium', STATUS_BADGE_CLASS[taskStatus]]"
                >
                  {{ STATUS_LABEL[taskStatus] || taskStatus || '—' }}
                </Badge>
              </div>
              <p class="mt-1 text-xs text-zinc-500">这里显示 Codex 的原始终端输出，方便判断是否需要你的进一步输入。</p>
            </div>
            <div class="flex items-center gap-2">
              <Button size="sm" variant="ghost" class="h-7 px-2 text-xs text-zinc-400 hover:text-zinc-200" @click="currentTask?.id && fetchProviderOutput(currentTask.id)">
                刷新
              </Button>
              <Button size="sm" variant="ghost" class="h-7 px-2 text-xs text-zinc-400 hover:text-zinc-200" @click="providerOutputOpen = false">
                关闭 (Esc)
              </Button>
            </div>
          </div>
          <div ref="providerOutputRef" class="flex-1 overflow-y-auto px-5 py-4 font-mono text-xs leading-relaxed text-zinc-300">
            <div v-if="providerOutputTruncated" class="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
              输出较长，当前窗口仅展示最近一部分内容。
            </div>
            <pre v-if="providerOutput" class="whitespace-pre-wrap break-all">{{ providerOutput }}</pre>
            <div v-else class="pt-20 text-center text-zinc-600">
              暂时还没有 Codex 输出，任务运行中会自动刷新这里的内容。
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <SiteFileBrowserDialog
      v-model:open="fileBrowserOpen"
      :site-id="siteId"
      :site-name="site?.name"
      :refresh-key="fileBrowserRefreshKey"
    />

  </div>
</template>
