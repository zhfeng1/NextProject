<script setup lang="ts">
// @ts-nocheck
import { ref, watch, nextTick, onMounted } from 'vue'
import { conversationsAPI } from '@/api/conversations'
import type { Conversation, ConversationMessage } from '@/api/conversations'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const props = defineProps<{
  siteId: string
  currentUrl?: string
  selectedXpath?: string
  consoleErrors?: string
  provider?: string
}>()

const emit = defineEmits<{
  (e: 'taskCreated', taskId: string): void
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

const PROVIDERS = [
  { value: 'codex', label: 'Codex' },
  { value: 'claude_code', label: 'Claude' },
  { value: 'gemini_cli', label: 'Gemini' },
]
const selectedProvider = ref(props.provider || 'codex')

watch(() => props.provider, (v) => { if (v) selectedProvider.value = v })

// ── Task status helpers ───────────────────────────────────────────────────────
const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', success: '成功', failed: '失败', canceled: '已取消',
}
const STATUS_CLASS: Record<string, string> = {
  queued: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  running: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  success: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  canceled: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
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
        const status = res.task?.status || ''
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
  try {
    await conversationsAPI.archive(conv.id)
    conversations.value = conversations.value.filter(c => c.id !== conv.id)
    if (activeConv.value?.id === conv.id) {
      activeConv.value = null
      messages.value = []
    }
  } catch {}
}

// ── Send ──────────────────────────────────────────────────────────────────────
async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
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
        class="flex items-center gap-1.5 text-sm font-medium hover:text-foreground transition-colors"
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
      class="shrink-0 border-b bg-background shadow-sm max-h-48 overflow-y-auto"
    >
      <div v-if="!conversations.length" class="px-3 py-4 text-xs text-muted-foreground text-center">
        暂无会话，点击「新建」开始
      </div>
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors"
        :class="activeConv?.id === conv.id ? 'bg-muted/60' : ''"
        @click="selectConversation(conv)"
      >
        <span class="flex-1 truncate text-xs">{{ conv.title || '新会话' }}</span>
        <span class="shrink-0 text-[10px] text-muted-foreground">{{ conv.message_count }}条</span>
        <button
          class="shrink-0 text-muted-foreground hover:text-red-500 transition-colors text-[11px]"
          title="归档"
          @click.stop="archiveConversation(conv)"
        >✕</button>
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

      <div v-if="loading" class="flex items-center justify-center h-full">
        <span class="text-xs text-muted-foreground">加载中...</span>
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
                class="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                :class="STATUS_CLASS[taskStatuses[msg.task_id]] || STATUS_CLASS.queued"
              >
                {{ STATUS_LABEL[taskStatuses[msg.task_id]] || taskStatuses[msg.task_id] }}
              </span>
              <span
                v-else-if="msg.task_id"
                class="rounded-full px-1.5 py-0.5 text-[10px] font-medium animate-pulse"
                :class="STATUS_CLASS.queued"
              >
                排队中
              </span>
              <span
                v-if="msg.provider"
                class="text-[10px] text-muted-foreground"
              >via {{ msg.provider }}</span>
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
        <div v-if="sending" class="flex justify-start">
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
    <div v-if="error" class="px-3 py-1.5 text-xs text-red-600 bg-red-50 dark:bg-red-950/30 border-t shrink-0">
      {{ error }}
      <button class="ml-2 underline" @click="error = ''">关闭</button>
    </div>

    <!-- Provider selector -->
    <div class="px-3 pt-2 flex gap-1 shrink-0">
      <button
        v-for="p in PROVIDERS" :key="p.value"
        class="flex-1 py-0.5 text-[10px] rounded border transition-colors"
        :class="selectedProvider === p.value
          ? 'bg-primary text-primary-foreground border-primary'
          : 'bg-background hover:bg-muted border-border text-foreground'"
        @click="selectedProvider = p.value"
      >{{ p.label }}</button>
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
          @keydown="handleKey"
        />
        <Button
          size="sm"
          class="h-8 px-3 shrink-0"
          :disabled="sending || !input.trim()"
          @click="send"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
          </svg>
        </Button>
      </div>
    </div>
  </div>
</template>
