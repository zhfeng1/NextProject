<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { conversationsAPI } from '@/api/conversations'
import type { Conversation, ConversationMessage } from '@/api/conversations'
import { Button } from '@/components/ui/button'
import ProgrammingToolPicker from '@/components/ProgrammingToolPicker.vue'
import {
  programmingToolLabel,
  programmingToolReason,
  visibleProgrammingTools,
  type ProgrammingTool,
} from '@/api/programmingTools'
import { Loader2, Send, X } from 'lucide-vue-next'

const props = defineProps<{
  siteId: string
  currentUrl?: string
  selectedXpath?: string
  consoleErrors?: string
  provider?: string
  programmingTools?: ProgrammingTool[]
  programmingToolsLoading?: boolean
  programmingToolsError?: string
  providerSettingsTo?: string
}>()

const emit = defineEmits<{
  (e: 'taskCreated', taskId: string): void
  (e: 'retryProgrammingTools'): void
}>()

// ── State ────────────────────────────────────────────────────────────────────
const conversations = ref<Conversation[]>([])
const activeConv = ref<Conversation | null>(null)
const messages = ref<ConversationMessage[]>([])
const input = ref('')
const sending = ref(false)
const loading = ref(false)
const error = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const showConvList = ref(false)
const archivingConversationId = ref('')
const cleanupRetryConversation = ref<Conversation | null>(null)
const retryingCleanup = ref(false)

const selectedProvider = ref(props.provider || '')
const availableTools = computed(() => visibleProgrammingTools(props.programmingTools || []))
const selectedTool = computed(() => availableTools.value.find(tool => tool.id === selectedProvider.value) || null)
const canUseSelectedProvider = computed(() => selectedTool.value?.available === true)
const selectedToolReason = computed(() => programmingToolReason(selectedTool.value))

function selectDefaultTool(preferred?: string) {
  const tools = availableTools.value
  const preferredTool = tools.find(tool => tool.id === preferred && tool.available)
  const currentTool = tools.find(tool => tool.id === selectedProvider.value && tool.available)
  selectedProvider.value = preferredTool?.id || currentTool?.id || tools.find(tool => tool.available)?.id || tools[0]?.id || ''
}

watch(
  [() => props.provider, () => props.programmingTools],
  ([preferred]) => selectDefaultTool(preferred),
  { immediate: true, deep: true },
)

function providerLabel(provider?: string) {
  return programmingToolLabel(provider, availableTools.value)
}

// ── Task status helpers ───────────────────────────────────────────────────────
const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', success: '成功', failed: '失败', canceled: '已取消',
}
const STATUS_TONE: Record<string, 'muted' | 'warning' | 'success' | 'danger'> = {
  queued: 'muted', running: 'warning', success: 'success', failed: 'danger', canceled: 'muted',
}

// inline task status polling (per message)
const taskStatuses = ref<Record<string, string>>({})
let taskPollers: Record<string, ReturnType<typeof setInterval>> = {}

function startTaskPoller(taskId: string) {
  if (taskPollers[taskId]) return
  import('@/api/tasks').then(({ tasksAPI }) => {
    taskPollers[taskId] = setInterval(async () => {
      try {
        const res = await tasksAPI.get(taskId)
        const status = String(res.task?.status || '')
        taskStatuses.value = { ...taskStatuses.value, [taskId]: status }
        if (['success', 'failed', 'canceled'].includes(status)) {
          clearInterval(taskPollers[taskId])
          delete taskPollers[taskId]
        }
      } catch {}
    }, 4000)
  })
}

function stopAllPollers() {
  Object.values(taskPollers).forEach(clearInterval)
  taskPollers = {}
}

// ── Conversations ─────────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    const res = await conversationsAPI.list(props.siteId)
    conversations.value = res.conversations || []
  } catch {}
}

async function selectConversation(conv: Conversation) {
  activeConv.value = conv
  showConvList.value = false
  loading.value = true
  try {
    const res = await conversationsAPI.get(conv.id)
    messages.value = res.conversation.messages || []
    // start pollers for any running task_ref messages
    messages.value.forEach((m) => {
      if (m.message_type === 'task_ref' && m.task_id) {
        const s = taskStatuses.value[m.task_id]
        if (!s || !['success', 'failed', 'canceled'].includes(s)) {
          startTaskPoller(m.task_id)
        }
      }
    })
    scrollToBottom()
  } catch (e: any) {
    error.value = '加载消息失败'
  } finally {
    loading.value = false
  }
}

async function createConversation() {
  try {
    const res = await conversationsAPI.create(props.siteId)
    conversations.value.unshift(res.conversation)
    await selectConversation(res.conversation)
  } catch {
    error.value = '创建会话失败'
  }
}

async function archiveConversation(conv: Conversation) {
  if (conv.completion_status === 'merging') {
    error.value = '会话正在合并，暂时不能归档'
    return
  }
  const confirmed = window.confirm(
    conv.scope_type === 'project'
      ? `确认永久归档「${conv.title || '新会话'}」？\n\n归档后无法恢复，系统将清理该会话的 worktree 和任务分支。请先确认需要保留的修改已经合并或备份。`
      : `确认归档「${conv.title || '新会话'}」？`,
  )
  if (!confirmed) return
  archivingConversationId.value = conv.id
  try {
    const res = await conversationsAPI.archive(conv.id)
    conversations.value = conversations.value.filter(c => c.id !== conv.id)
    if (activeConv.value?.id === conv.id) {
      activeConv.value = null
      messages.value = []
    }
    if (['warning', 'failed'].includes(res.conversation.cleanup_status || '')) {
      cleanupRetryConversation.value = res.conversation
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '归档会话失败'
  } finally {
    archivingConversationId.value = ''
  }
}

async function retryConversationCleanup() {
  const conv = cleanupRetryConversation.value
  if (!conv || retryingCleanup.value) return
  retryingCleanup.value = true
  try {
    const res = await conversationsAPI.cleanup(conv.id)
    cleanupRetryConversation.value = ['warning', 'failed'].includes(res.conversation.cleanup_status || '')
      ? res.conversation
      : null
  } catch (e: any) {
    cleanupRetryConversation.value = {
      ...conv,
      cleanup_status: 'failed',
      cleanup_error: e?.response?.data?.detail || '重试清理失败',
    }
  } finally {
    retryingCleanup.value = false
  }
}

// ── Send ──────────────────────────────────────────────────────────────────────
async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  if (!canUseSelectedProvider.value) {
    error.value = selectedToolReason.value
    return
  }
  if (!activeConv.value) {
    await createConversation()
  }
  if (!activeConv.value) return
  sending.value = true
  error.value = ''
  // Optimistic user bubble
  const optimisticId = -(Date.now())
  messages.value.push({
    id: optimisticId,
    conversation_id: activeConv.value.id,
    seq: (messages.value[messages.value.length - 1]?.seq ?? 0) + 1,
    role: 'user',
    content: text,
    message_type: 'text',
    provider: '',
    task_id: '',
    token_count: 0,
    metadata: {},
    created_at: new Date().toISOString(),
  })
  input.value = ''
  scrollToBottom()

  try {
    const res = await conversationsAPI.sendMessage(activeConv.value.id, text, {
      provider: selectedProvider.value,
      current_url: props.currentUrl,
      selected_xpath: props.selectedXpath,
      console_errors: props.consoleErrors,
    })
    // Replace optimistic with real user message
    const idx = messages.value.findIndex(m => m.id === optimisticId)
    if (idx !== -1 && res.user_message) {
      messages.value[idx] = res.user_message
    }
    // Add assistant placeholder
    if (res.assistant_message) {
      messages.value.push(res.assistant_message)
    }
    // Start task poller if task created
    if (res.task_id) {
      taskStatuses.value = { ...taskStatuses.value, [res.task_id]: res.task?.status as string || 'queued' }
      startTaskPoller(res.task_id)
      emit('taskCreated', res.task_id)
    }
    // Refresh conversation list counts
    await loadConversations()
    scrollToBottom()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '发送失败，请重试'
    // Remove optimistic bubble on failure
    messages.value = messages.value.filter(m => m.id !== optimisticId)
  } finally {
    sending.value = false
  }
}

function handleKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadConversations()
  // Auto-open latest active conversation
  if (conversations.value.length) {
    await selectConversation(conversations.value[0])
  }
})

onBeforeUnmount(stopAllPollers)

watch(() => props.siteId, async () => {
  stopAllPollers()
  activeConv.value = null
  messages.value = []
  await loadConversations()
  if (conversations.value.length) {
    await selectConversation(conversations.value[0])
  }
})
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <!-- Header -->
    <div class="flex items-center justify-between px-3 py-2 border-b bg-muted/30 shrink-0">
      <button
        type="button"
        class="flex min-h-9 items-center gap-1.5 rounded-sm text-sm font-medium transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-expanded="showConvList"
        aria-controls="site-conversation-list"
        @click="showConvList = !showConvList"
      >
        <svg class="w-3.5 h-3.5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
        </svg>
        <span class="truncate max-w-[9rem]">{{ activeConv?.title || '多轮对话' }}</span>
        <svg class="w-3 h-3 text-muted-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
      <Button size="sm" variant="ghost" class="h-6 px-2 text-xs gap-1" @click="createConversation">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        新建
      </Button>
    </div>

    <!-- Conversation list dropdown -->
    <div
      v-if="showConvList"
      id="site-conversation-list"
      class="shrink-0 border-b bg-background shadow-sm max-h-48 overflow-y-auto"
    >
      <div v-if="!conversations.length" class="px-3 py-4 text-xs text-muted-foreground text-center">
        暂无会话，点击「新建」开始
      </div>
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="flex items-center gap-1 px-1.5 py-1"
        :class="activeConv?.id === conv.id ? 'bg-muted/60' : ''"
      >
        <button
          type="button"
          class="flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded px-1.5 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="selectConversation(conv)"
        >
          <span class="flex-1 truncate text-xs">{{ conv.title || '新会话' }}</span>
          <span class="shrink-0 text-[10px] text-muted-foreground">{{ conv.message_count }}条</span>
        </button>
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :disabled="conv.completion_status === 'merging' || archivingConversationId === conv.id"
          :aria-label="`归档会话：${conv.title || '新会话'}`"
          :title="conv.completion_status === 'merging' ? '会话正在合并，暂时不能归档' : '永久归档'"
          @click="archiveConversation(conv)"
        ><X class="size-3.5" aria-hidden="true" /></button>
      </div>
    </div>

    <!-- Messages area -->
    <div ref="messagesRef" class="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
      <!-- Empty state -->
      <div v-if="!activeConv && !loading" class="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground">
        <svg class="w-8 h-8 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
        </svg>
        <p class="text-xs">输入需求，开始多轮对话</p>
      </div>

      <div v-if="loading" role="status" aria-live="polite" class="flex items-center justify-center h-full gap-2">
        <Loader2 class="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
        <span class="text-xs text-muted-foreground">正在加载会话…</span>
      </div>

      <!-- Message bubbles -->
      <template v-if="!loading">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <!-- User bubble -->
          <div
            v-if="msg.role === 'user'"
            class="max-w-[85%] rounded-2xl rounded-tr-sm px-3 py-2 bg-primary text-primary-foreground text-xs leading-relaxed whitespace-pre-wrap break-words"
          >
            {{ msg.content }}
          </div>

          <!-- Assistant task_ref bubble -->
          <div
            v-else-if="msg.role === 'assistant' && msg.message_type === 'task_ref'"
            class="max-w-[85%] rounded-2xl rounded-tl-sm px-3 py-2 bg-muted text-foreground text-xs border"
          >
            <div class="flex items-center gap-1.5 flex-wrap">
              <svg class="w-3.5 h-3.5 text-muted-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"/>
              </svg>
              <span class="text-muted-foreground">AI 编码任务</span>
              <span
                v-if="msg.task_id && taskStatuses[msg.task_id]"
                class="flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                :class="{
                  'border-border bg-muted text-muted-foreground': STATUS_TONE[taskStatuses[msg.task_id]] === 'muted',
                  'border-warning/30 bg-warning/10 text-warning': STATUS_TONE[taskStatuses[msg.task_id]] === 'warning',
                  'border-success/30 bg-success/10 text-success': STATUS_TONE[taskStatuses[msg.task_id]] === 'success',
                  'border-destructive/30 bg-destructive/10 text-destructive': STATUS_TONE[taskStatuses[msg.task_id]] === 'danger',
                }"
              >
                <span
                  class="status-dot"
                  :data-tone="STATUS_TONE[taskStatuses[msg.task_id]]"
                  :data-pulse="taskStatuses[msg.task_id] === 'running'"
                />
                {{ STATUS_LABEL[taskStatuses[msg.task_id]] || taskStatuses[msg.task_id] }}
              </span>
              <span
                v-else-if="msg.task_id"
                class="flex items-center gap-1 rounded-full border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
              >
                <span class="status-dot" data-tone="muted" data-pulse="true" />
                排队中
              </span>
              <span
                v-if="msg.provider"
                class="text-[10px] text-muted-foreground"
              >via {{ providerLabel(msg.provider) }}</span>
            </div>
          </div>

          <!-- Assistant text bubble -->
          <div
            v-else-if="msg.role === 'assistant'"
            class="max-w-[85%] rounded-2xl rounded-tl-sm px-3 py-2 bg-muted text-foreground text-xs leading-relaxed whitespace-pre-wrap break-words border"
          >
            {{ msg.content || '...' }}
          </div>
        </div>

        <!-- Sending indicator -->
        <div v-if="sending" role="status" aria-live="polite" aria-label="正在提交任务" class="flex justify-start">
          <div class="rounded-2xl rounded-tl-sm px-3 py-2 bg-muted text-muted-foreground text-xs border flex items-center gap-1">
            <span class="inline-flex gap-0.5">
              <span class="w-1 h-1 rounded-full bg-muted-foreground animate-bounce" style="animation-delay:0ms"/>
              <span class="w-1 h-1 rounded-full bg-muted-foreground animate-bounce" style="animation-delay:150ms"/>
              <span class="w-1 h-1 rounded-full bg-muted-foreground animate-bounce" style="animation-delay:300ms"/>
            </span>
          </div>
        </div>
      </template>
    </div>

    <!-- Error -->
    <div v-if="error" role="alert" class="shrink-0 border-t border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
      {{ error }}
      <button class="ml-2 underline" @click="error = ''">关闭</button>
    </div>

    <div
      v-if="cleanupRetryConversation"
      role="alert"
      class="shrink-0 border-t border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div class="font-medium">会话已归档，但工作区清理未完成</div>
      <div class="mt-0.5 break-words">
        {{ cleanupRetryConversation.cleanup_error || 'worktree 或任务分支清理失败，请重试。' }}
      </div>
      <button
        type="button"
        class="mt-1.5 font-medium underline underline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="retryingCleanup"
        @click="retryConversationCleanup"
      >{{ retryingCleanup ? '清理中…' : '重试清理' }}</button>
    </div>

    <!-- Programming tool selector -->
    <div class="shrink-0 px-3 pt-2">
      <ProgrammingToolPicker
        v-model="selectedProvider"
        :tools="availableTools"
        :loading="programmingToolsLoading"
      />
    </div>

    <div
      v-if="!programmingToolsLoading && programmingToolsError"
      role="alert"
      class="mx-3 mt-2 shrink-0 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs text-destructive"
    >
      {{ programmingToolsError }}
      <button type="button" class="ml-1 font-medium underline underline-offset-2" @click="emit('retryProgrammingTools')">重新加载</button>
    </div>

    <div
      v-else-if="!programmingToolsLoading && !canUseSelectedProvider"
      role="alert"
      class="mx-3 mt-2 shrink-0 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-2 text-xs text-warning"
    >
      {{ selectedToolReason }}。
      <RouterLink :to="providerSettingsTo || '/projects'" class="ml-1 font-medium underline underline-offset-2">前往配置</RouterLink>
    </div>

    <!-- Input area -->
    <div class="px-3 pb-3 pt-1.5 shrink-0">
      <div class="flex gap-1.5 items-end">
        <textarea
          v-model="input"
          rows="3"
          placeholder="描述需求，按 Enter 发送（Shift+Enter 换行）..."
          class="flex-1 resize-none rounded-lg border bg-muted/30 px-2.5 py-2 text-xs outline-none focus:ring-1 focus:ring-ring font-sans leading-relaxed"
          :disabled="sending"
          aria-label="对话需求"
          @keydown="handleKey"
        />
        <Button
          size="sm"
          class="h-8 px-3 shrink-0"
          :disabled="sending || !input.trim() || programmingToolsLoading || !canUseSelectedProvider"
          aria-label="发送消息"
          title="发送消息"
          @click="send"
        >
          <Send class="size-3.5" aria-hidden="true" />
        </Button>
      </div>
    </div>
  </div>
</template>
