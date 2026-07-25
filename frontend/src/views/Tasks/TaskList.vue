<script setup lang="ts">
// @ts-nocheck
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { conversationsAPI, type Conversation, type ConversationGitState, type ConversationMessage } from '@/api/conversations'
import { projectsAPI } from '@/api/projects'
import { gitAPI, type GitGraph, type GitGraphCommit } from '@/api/git'
import {
  programmingToolLabel,
  programmingToolReason,
  programmingToolsAPI,
  visibleProgrammingTools,
  type ProgrammingTool,
} from '@/api/programmingTools'
import type { Project, Task } from '@/types/models'
import TimelineTaskRun from './components/TimelineTaskRun.vue'
import GitCommitGraph from '@/components/GitCommitGraph.vue'
import ConversationDiffViewer from '@/components/ConversationDiffViewer.vue'
import ProgrammingToolPicker from '@/components/ProgrammingToolPicker.vue'
import {
  Archive,
  Bot,
  Check,
  ChevronDown,
  FolderGit2,
  GitBranch,
  GitCompareArrows,
  GitCommitHorizontal,
  GitMerge,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  X,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

type TimelineEvent = {
  id: string
  type: 'system_note' | 'user_request' | 'task_run'
  message?: ConversationMessage
  taskId?: string
  created_at?: string | null
  content?: string
}

const route = useRoute()
const router = useRouter()

const projects = ref<Project[]>([])
const conversations = ref<Conversation[]>([])
const activeConv = ref<Conversation | null>(null)
const messages = ref<ConversationMessage[]>([])
const selectedProjectId = ref('')
const selectedRepoIds = ref<string[]>([])
const selectedProvider = ref('')
const loadingProjects = ref(false)
const loadingConversations = ref(false)
const loadingMessages = ref(false)
const sending = ref(false)
const input = ref('')
const quoteText = ref('')
const filterMode = ref('all')
const timelineSearch = ref('')
const taskStatuses = ref<Record<string, string>>({})
const taskSnapshots = ref<Record<string, Partial<Task>>>({})
const expandedRequests = ref<Record<number, boolean>>({})
const timelineRef = ref<HTMLElement | null>(null)
const composerRef = ref<HTMLTextAreaElement | null>(null)
const isNearBottom = ref(true)
const hasNewActivity = ref(false)
const projectPickerOpen = ref(false)
const projectSearch = ref('')
const projectPickerRef = ref<HTMLElement | null>(null)
const programmingTools = ref<ProgrammingTool[]>([])
const providerAvailabilityLoading = ref(true)
const programmingToolsError = ref('')
const gitState = ref<ConversationGitState | null>(null)
const loadingGitState = ref(false)
const diffOpen = ref(false)
const showNewConversationDialog = ref(false)
const newConversationTitle = ref('')
const newConversationRepoIds = ref<string[]>([])
const newConversationProvider = ref('')
const creatingConversation = ref(false)
const showCompleteDialog = ref(false)
const completingConversation = ref(false)
const showArchiveDialog = ref(false)
const archiveTarget = ref<Conversation | null>(null)
const archivingConversation = ref(false)
const cleanupRetryConversation = ref<Conversation | null>(null)
const retryingCleanup = ref(false)
const graphOpen = ref(false)
const conversationGraphRepoId = ref('')
const conversationGraph = ref<GitGraph | null>(null)
const loadingConversationGraph = ref(false)
const conversationGraphError = ref('')
const rollingBackConversationGraph = ref(false)
let conversationGraphRequestSeq = 0

const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'requests', label: '需求' },
  { value: 'running', label: '运行中' },
  { value: 'failed', label: '失败' },
  { value: 'done', label: '已完成' },
]

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

const selectedProject = computed(() => projects.value.find(project => project.id === selectedProjectId.value) || null)
const selectedProjectName = computed(() => selectedProject.value?.name || '选择项目')
const projectRepos = computed(() => selectedProject.value?.repos || [])
const repoNameMap = computed(() => Object.fromEntries(projectRepos.value.map(repo => [repo.site_id, repo.name || repo.site_id])))
const selectedRepoNames = computed(() => selectedRepoIds.value.map(repoId => repoNameMap.value[repoId] || repoId))
const availableTools = computed(() => visibleProgrammingTools(programmingTools.value))
const selectedTool = computed(() => availableTools.value.find(tool => tool.id === selectedProvider.value) || null)
const canUseSelectedProvider = computed(() => selectedTool.value?.available === true)
const selectedToolReason = computed(() => programmingToolReason(selectedTool.value))
const newConversationTool = computed(() => availableTools.value.find(tool => tool.id === newConversationProvider.value) || null)
const newConversationBranchPrefix = computed(() => newConversationTool.value?.branch_prefix || `${newConversationProvider.value || 'tool'}/`)
const canSend = computed(() => Boolean(
  selectedProject.value
  && selectedRepoIds.value.length
  && input.value.trim()
  && !sending.value
  && !providerAvailabilityLoading.value
  && canUseSelectedProvider.value
  && !['merging', 'completed'].includes(activeConv.value?.completion_status || '')
))
const totalChangedFiles = computed(() => (
  gitState.value?.repositories.reduce((total, repo) => total + repo.changed_files, 0) || 0
))
const completionLabel = computed(() => ({
  active: '开发中',
  merging: '合并中',
  completed: '已合并',
  failed: '合并失败',
}[activeConv.value?.completion_status || 'active'] || '开发中'))
const conversationRollbackDisabledReason = computed(() => {
  if (!activeConv.value) return '请先选择开发会话'
  if (activeConv.value.status === 'archived') return '归档会话不能回滚任务分支'
  if (activeConv.value.completion_status === 'merging') return '会话正在合并，暂时不能回滚'
  if (activeConv.value.completion_status === 'completed') return '会话已经合并，任务分支为只读状态'
  const repo = gitState.value?.repositories.find(item => item.site_id === conversationGraphRepoId.value)
  if (repo?.snapshot) return '任务分支已清理，当前仅保留只读快照'
  return ''
})
const filteredProjects = computed(() => {
  const q = projectSearch.value.trim().toLowerCase()
  if (!q) return projects.value
  return projects.value.filter(project => {
    const haystack = [project.name, project.description, project.id].filter(Boolean).join(' ').toLowerCase()
    return haystack.includes(q)
  })
})

const activeTaskStatus = computed(() => {
  const taskEvent = [...timelineEvents.value].reverse().find(event => event.type === 'task_run')
  if (!taskEvent?.taskId) return ''
  return getTaskStatus(taskEvent.message)
})

const timelineEvents = computed<TimelineEvent[]>(() => {
  const events: TimelineEvent[] = []
  if (activeConv.value) {
    events.push({
      id: `conv-${activeConv.value.id}`,
      type: 'system_note',
      content: '会话已创建',
      created_at: activeConv.value.created_at,
    })
  }
  for (const msg of messages.value) {
    if (msg.role === 'user') {
      events.push({ id: `msg-${msg.id}`, type: 'user_request', message: msg, created_at: msg.created_at })
    } else if (msg.message_type === 'task_ref' && msg.task_id) {
      events.push({ id: `task-${msg.id}-${msg.task_id}`, type: 'task_run', message: msg, taskId: msg.task_id, created_at: msg.created_at })
    } else if (msg.role === 'assistant') {
      events.push({ id: `note-${msg.id}`, type: 'system_note', message: msg, content: msg.content, created_at: msg.created_at })
    }
  }
  return events
})

const filteredEvents = computed(() => {
  const q = timelineSearch.value.trim().toLowerCase()
  return timelineEvents.value.filter(event => {
    if (filterMode.value === 'requests' && event.type !== 'user_request') return false
    if (['running', 'failed', 'done'].includes(filterMode.value)) {
      if (event.type !== 'task_run') return false
      const status = getTaskStatus(event.message)
      if (filterMode.value === 'running' && !['queued', 'running'].includes(status)) return false
      if (filterMode.value === 'failed' && status !== 'failed') return false
      if (filterMode.value === 'done' && status !== 'success') return false
    }
    if (!q) return true
    const haystack = [
      event.content || '',
      event.message?.content || '',
      taskSnapshot(event.message)?.title || '',
      taskSnapshot(event.message)?.error || '',
      eventRepoNames(event.message).join(' '),
    ].join(' ').toLowerCase()
    return haystack.includes(q)
  })
})

function metadata(message?: ConversationMessage | null) {
  return (message?.metadata || {}) as Record<string, any>
}

function taskSnapshot(message?: ConversationMessage | null) {
  if (!message?.task_id) return {}
  return {
    ...(metadata(message).task_snapshot || {}),
    ...(taskSnapshots.value[message.task_id] || {}),
  }
}

function getTaskStatus(message?: ConversationMessage | null) {
  if (!message?.task_id) return ''
  return taskStatuses.value[message.task_id] || taskSnapshot(message).status || 'queued'
}

function statusTone(status: string) {
  return STATUS_TONE[status] || 'muted'
}

function displayDate(value?: string | null) {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

function eventRepoIds(message?: ConversationMessage | null) {
  const metaRepoIds = metadata(message).repo_ids
  const snapshotRepoIds = taskSnapshot(message)?.payload?.repo_ids
  const ids = Array.isArray(metaRepoIds) && metaRepoIds.length
    ? metaRepoIds
    : Array.isArray(snapshotRepoIds) ? snapshotRepoIds : []
  return ids.map(String)
}

function eventRepoNames(message?: ConversationMessage | null) {
  const ids = eventRepoIds(message)
  if (ids.length) return ids.map(repoId => repoNameMap.value[repoId] || repoId)
  return selectedRepoNames.value
}

function providerLabel(provider?: string) {
  return programmingToolLabel(provider, availableTools.value)
}

function shouldClamp(message: ConversationMessage) {
  return (message.content || '').length > 360
}

function toggleRepo(repoId: string) {
  if (activeConv.value) return
  const next = new Set(selectedRepoIds.value)
  if (next.has(repoId)) next.delete(repoId)
  else next.add(repoId)
  selectedRepoIds.value = [...next]
}

async function loadProjects() {
  loadingProjects.value = true
  try {
    const res = await projectsAPI.list()
    projects.value = res.projects || []
    const requestedProjectId = String(route.query.project_id || '')
    const initialProjectId = projects.value.some(project => project.id === requestedProjectId)
      ? requestedProjectId
      : projects.value[0]?.id || ''
    if (initialProjectId) {
      await selectProject(initialProjectId, false)
    }
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '加载项目失败')
  } finally {
    loadingProjects.value = false
  }
}

async function selectProject(projectId: string, syncRoute = true) {
  selectedProjectId.value = projectId
  const project = projects.value.find(item => item.id === projectId)
  selectedRepoIds.value = (project?.repos || []).map(repo => repo.site_id)
  activeConv.value = null
  messages.value = []
  taskStatuses.value = {}
  taskSnapshots.value = {}
  gitState.value = null
  graphOpen.value = false
  conversationGraphRepoId.value = ''
  conversationGraph.value = null
  conversationGraphError.value = ''
  conversationGraphRequestSeq += 1
  if (syncRoute) {
    await router.replace({ path: '/tasks', query: projectId ? { project_id: projectId } : {} })
  }
  await Promise.all([loadConversations(), loadProgrammingTools(projectId)])
  if (conversations.value.length) {
    await selectConversation(conversations.value[0])
  }
}

async function loadProgrammingTools(projectId: string) {
  providerAvailabilityLoading.value = true
  programmingToolsError.value = ''
  try {
    const res = await programmingToolsAPI.list(projectId)
    programmingTools.value = visibleProgrammingTools(res.tools || [])
    if (!activeConv.value) {
      const current = programmingTools.value.find(tool => tool.id === selectedProvider.value && tool.available)
      selectedProvider.value = current?.id
        || programmingTools.value.find(tool => tool.available)?.id
        || programmingTools.value[0]?.id
        || ''
    }
  } catch (error: any) {
    programmingTools.value = []
    if (!activeConv.value) selectedProvider.value = ''
    programmingToolsError.value = error?.response?.data?.detail || '无法加载编程工具状态，请检查网络后重试'
  } finally {
    providerAvailabilityLoading.value = false
  }
}

async function selectProjectFromPicker(projectId: string) {
  projectPickerOpen.value = false
  projectSearch.value = ''
  if (projectId !== selectedProjectId.value) {
    await selectProject(projectId)
  }
}

async function loadConversations() {
  if (!selectedProjectId.value) {
    conversations.value = []
    return
  }
  loadingConversations.value = true
  try {
    const res = await conversationsAPI.listProject(selectedProjectId.value)
    conversations.value = res.conversations || []
    if (activeConv.value) {
      const fresh = conversations.value.find(conv => conv.id === activeConv.value?.id)
      if (fresh) activeConv.value = fresh
    }
  } catch (error: any) {
    conversations.value = []
    toast.error(error?.response?.data?.detail || '加载会话失败')
  } finally {
    loadingConversations.value = false
  }
}

async function selectConversation(conv: Conversation) {
  activeConv.value = conv
  selectedRepoIds.value = conv.repo_ids?.length ? [...conv.repo_ids] : projectRepos.value.map(repo => repo.site_id)
  selectedProvider.value = conv.provider || availableTools.value.find(tool => tool.available)?.id || availableTools.value[0]?.id || ''
  gitState.value = null
  graphOpen.value = false
  conversationGraphRepoId.value = ''
  conversationGraph.value = null
  conversationGraphError.value = ''
  conversationGraphRequestSeq += 1
  loadingMessages.value = true
  try {
    const res = await conversationsAPI.get(conv.id)
    activeConv.value = res.conversation
    messages.value = res.conversation.messages || []
    seedTaskState(messages.value)
    await loadGitState()
    scrollToLatest(true)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '加载消息失败')
  } finally {
    loadingMessages.value = false
  }
}

async function loadGitState() {
  if (!activeConv.value) {
    gitState.value = null
    return
  }
  loadingGitState.value = true
  try {
    const res = await conversationsAPI.getGit(activeConv.value.id)
    gitState.value = res.git
    if (!conversationGraphRepoId.value || !res.git.repositories.some(repo => repo.site_id === conversationGraphRepoId.value)) {
      conversationGraphRepoId.value = res.git.repositories[0]?.site_id || ''
    }
  } catch (error: any) {
    gitState.value = null
    toast.error(error?.response?.data?.detail || '加载分支信息失败')
  } finally {
    loadingGitState.value = false
  }
}

async function openConversationGraph(repoId = '') {
  if (!activeConv.value) return
  const targetRepoId = repoId || conversationGraphRepoId.value || gitState.value?.repositories[0]?.site_id || ''
  if (!targetRepoId) {
    toast.warning('当前会话没有可展示的任务分支')
    return
  }
  graphOpen.value = true
  await selectConversationGraphRepository(targetRepoId)
}

async function selectConversationGraphRepository(repoId: string) {
  if (!repoId) return
  conversationGraphRepoId.value = repoId
  await loadConversationGraph()
}

async function loadConversationGraph() {
  if (!activeConv.value || !conversationGraphRepoId.value) return
  const requestSeq = ++conversationGraphRequestSeq
  const conversationId = activeConv.value.id
  const repoId = conversationGraphRepoId.value
  loadingConversationGraph.value = true
  conversationGraphError.value = ''
  try {
    const res = await gitAPI.getConversationGraph(conversationId, repoId)
    if (requestSeq !== conversationGraphRequestSeq) return
    conversationGraph.value = res.graph
  } catch (error: any) {
    if (requestSeq !== conversationGraphRequestSeq) return
    conversationGraph.value = null
    conversationGraphError.value = error?.response?.data?.detail || '无法读取任务分支的提交历史'
  } finally {
    if (requestSeq === conversationGraphRequestSeq) loadingConversationGraph.value = false
  }
}

async function rollbackConversationCommit(commit: GitGraphCommit) {
  if (!activeConv.value || !conversationGraphRepoId.value || rollingBackConversationGraph.value) return
  rollingBackConversationGraph.value = true
  try {
    const res = await gitAPI.rollbackConversation(activeConv.value.id, conversationGraphRepoId.value, commit.sha)
    conversationGraph.value = res.graph
    await loadGitState()
    toast.success(`任务分支已回滚到 ${commit.short_sha}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '回滚失败，请确认工作区干净且提交属于当前任务分支')
  } finally {
    rollingBackConversationGraph.value = false
  }
}

function seedTaskState(list: ConversationMessage[]) {
  const statuses: Record<string, string> = {}
  const snapshots: Record<string, Partial<Task>> = {}
  for (const msg of list) {
    if (msg.task_id) {
      const snapshot = metadata(msg).task_snapshot || {}
      snapshots[msg.task_id] = snapshot
      if (snapshot.status) statuses[msg.task_id] = snapshot.status
    }
  }
  taskStatuses.value = statuses
  taskSnapshots.value = snapshots
}

function openNewConversationDialog() {
  if (!selectedProject.value || !projectRepos.value.length) return
  newConversationTitle.value = ''
  newConversationRepoIds.value = projectRepos.value.map(repo => repo.site_id)
  const selected = availableTools.value.find(tool => tool.id === selectedProvider.value && tool.available)
  newConversationProvider.value = selected?.id || availableTools.value.find(tool => tool.available)?.id || ''
  showNewConversationDialog.value = true
}

function toggleNewConversationRepo(repoId: string) {
  const next = new Set(newConversationRepoIds.value)
  if (next.has(repoId)) next.delete(repoId)
  else next.add(repoId)
  newConversationRepoIds.value = [...next]
}

async function createConversation(title = '', repoIdsOverride?: string[], providerOverride?: string) {
  if (!selectedProject.value) return null
  if (!projectRepos.value.length) {
    toast.error('当前项目还没有仓库')
    return null
  }
  const repoIds = repoIdsOverride?.length
    ? repoIdsOverride
    : selectedRepoIds.value.length ? selectedRepoIds.value : projectRepos.value.map(repo => repo.site_id)
  const normalizedTitle = title.trim()
  if (!normalizedTitle) {
    showNewConversationDialog.value = true
    return null
  }
  creatingConversation.value = true
  try {
    const res = await conversationsAPI.createProject(selectedProject.value.id, {
      title: normalizedTitle,
      repo_ids: repoIds,
      provider: providerOverride || selectedProvider.value,
    })
    conversations.value.unshift(res.conversation)
    await selectConversation(res.conversation)
    showNewConversationDialog.value = false
    newConversationTitle.value = ''
    toast.success('开发会话和 worktree 已创建')
    return res.conversation
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '创建会话失败')
    return null
  } finally {
    creatingConversation.value = false
  }
}

async function confirmCreateConversation() {
  if (!newConversationRepoIds.value.length) {
    toast.error('请至少选择一个仓库')
    return
  }
  if (!newConversationTool.value?.available) {
    toast.error(programmingToolReason(newConversationTool.value))
    return
  }
  await createConversation(newConversationTitle.value, newConversationRepoIds.value, newConversationProvider.value)
}

function openArchiveDialog(conv: Conversation) {
  if (conv.completion_status === 'merging') {
    toast.error('会话正在合并，暂时不能归档')
    return
  }
  archiveTarget.value = conv
  showArchiveDialog.value = true
}

async function confirmArchiveConversation() {
  const conv = archiveTarget.value
  if (!conv || archivingConversation.value) return
  if (conv.completion_status === 'merging') {
    toast.error('会话正在合并，暂时不能归档')
    showArchiveDialog.value = false
    return
  }
  archivingConversation.value = true
  try {
    const res = await conversationsAPI.archive(conv.id)
    conversations.value = conversations.value.filter(item => item.id !== conv.id)
    if (activeConv.value?.id === conv.id) {
      activeConv.value = null
      messages.value = []
      gitState.value = null
      if (conversations.value.length) await selectConversation(conversations.value[0])
    }
    showArchiveDialog.value = false
    archiveTarget.value = null
    if (['warning', 'failed'].includes(res.conversation.cleanup_status || '')) {
      cleanupRetryConversation.value = res.conversation
      toast.warning('会话已归档，但工作区清理未完成')
    } else {
      if (cleanupRetryConversation.value?.id === conv.id) cleanupRetryConversation.value = null
      toast.success('会话已永久归档')
    }
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '归档会话失败')
  } finally {
    archivingConversation.value = false
  }
}

async function retryConversationCleanup() {
  const conv = cleanupRetryConversation.value
  if (!conv || retryingCleanup.value) return
  retryingCleanup.value = true
  try {
    const res = await conversationsAPI.cleanup(conv.id)
    if (['warning', 'failed'].includes(res.conversation.cleanup_status || '')) {
      cleanupRetryConversation.value = res.conversation
      toast.warning('清理仍未完成，请根据错误信息处理后重试')
    } else {
      cleanupRetryConversation.value = null
      toast.success('会话工作区已清理')
    }
  } catch (error: any) {
    cleanupRetryConversation.value = {
      ...conv,
      cleanup_status: 'failed',
      cleanup_error: error?.response?.data?.detail || '重试清理失败',
    }
  } finally {
    retryingCleanup.value = false
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || sending.value) return
  if (!selectedProject.value) {
    toast.error('请先选择项目')
    return
  }
  if (!selectedRepoIds.value.length) {
    toast.error('请至少选择一个仓库')
    return
  }
  if (!canUseSelectedProvider.value) {
    toast.error(selectedToolReason.value)
    return
  }
  if (activeConv.value && ['merging', 'completed'].includes(activeConv.value.completion_status || '')) {
    toast.error('该会话正在合并或已经合并，不能继续发送任务')
    return
  }
  sending.value = true
  try {
    if (!activeConv.value) {
      await createConversation(text)
    }
    if (!activeConv.value) return
    const res = await conversationsAPI.sendMessage(activeConv.value.id, text, {
      provider: selectedProvider.value,
      repo_ids: selectedRepoIds.value,
    })
    if (res.user_message) messages.value.push(res.user_message)
    if (res.assistant_message) messages.value.push(res.assistant_message)
    if (res.task_id && res.task) {
      taskStatuses.value = { ...taskStatuses.value, [res.task_id]: String(res.task.status || 'queued') }
      taskSnapshots.value = { ...taskSnapshots.value, [res.task_id]: res.task as Task }
    }
    input.value = ''
    quoteText.value = ''
    activeConv.value = {
      ...activeConv.value,
      title: activeConv.value.title === '新会话' ? text.slice(0, 80) : activeConv.value.title,
      repo_ids: [...selectedRepoIds.value],
      message_count: activeConv.value.message_count + 2,
      last_message_at: new Date().toISOString(),
    }
    await loadConversations()
    scrollToLatest()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '发送失败')
  } finally {
    sending.value = false
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function continueFrom(message: ConversationMessage) {
  quoteText.value = message.content.slice(0, 220)
  nextTick(() => composerRef.value?.focus())
}

function handleTaskStatusChange(taskId: string, status: string, task: Task | null) {
  if (status) taskStatuses.value = { ...taskStatuses.value, [taskId]: status }
  if (task) taskSnapshots.value = { ...taskSnapshots.value, [taskId]: task }
  if (['success', 'failed', 'canceled'].includes(status)) {
    window.setTimeout(async () => {
      if (!activeConv.value) return
      try {
        const res = await conversationsAPI.get(activeConv.value.id)
        activeConv.value = res.conversation
        messages.value = res.conversation.messages || messages.value
        if (['warning', 'failed'].includes(res.conversation.cleanup_status || '')) {
          cleanupRetryConversation.value = res.conversation
        } else if (cleanupRetryConversation.value?.id === res.conversation.id) {
          cleanupRetryConversation.value = null
        }
        await loadGitState()
        if (graphOpen.value && conversationGraphRepoId.value) await loadConversationGraph()
      } catch {
        // Timeline polling will retry on the next user refresh.
      }
    }, 400)
  }
}

function openDiff() {
  diffOpen.value = true
}

async function completeConversation() {
  if (!activeConv.value || completingConversation.value) return
  completingConversation.value = true
  try {
    const res = await conversationsAPI.complete(activeConv.value.id)
    activeConv.value = res.conversation
    if (res.assistant_message) messages.value.push(res.assistant_message)
    if (res.task_id && res.task) {
      taskStatuses.value = { ...taskStatuses.value, [res.task_id]: String(res.task.status || 'queued') }
      taskSnapshots.value = { ...taskSnapshots.value, [res.task_id]: res.task as Task }
    }
    showCompleteDialog.value = false
    await loadGitState()
    toast.success(`已提交给 ${providerLabel(activeConv.value.provider)} 合并`)
    scrollToLatest()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '合并会话失败')
  } finally {
    completingConversation.value = false
  }
}

function onTimelineScroll() {
  const el = timelineRef.value
  if (!el) return
  const near = el.scrollHeight - el.scrollTop - el.clientHeight < 140
  isNearBottom.value = near
  if (near) hasNewActivity.value = false
}

function scrollToLatest(immediate = false) {
  nextTick(() => {
    const el = timelineRef.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: immediate ? 'auto' : 'smooth' })
    hasNewActivity.value = false
  })
}

function handleDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (projectPickerRef.value && target && !projectPickerRef.value.contains(target)) {
    projectPickerOpen.value = false
  }
}

watch(() => messages.value.length, () => {
  if (isNearBottom.value) scrollToLatest()
  else hasNewActivity.value = true
})

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  loadProjects()
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>

<template>
  <Teleport defer to="#app-route-actions">
    <div class="ml-2 flex min-w-0 flex-1 items-center gap-2">
      <div ref="projectPickerRef" class="relative min-w-[13rem] max-w-[28rem] flex-1">
        <button
          type="button"
          class="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-left text-sm shadow-sm transition hover:bg-muted/50 focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="loadingProjects"
          @click="projectPickerOpen = !projectPickerOpen"
        >
          <span class="min-w-0 truncate font-medium">{{ selectedProjectName }}</span>
          <ChevronDown class="size-4 shrink-0 text-muted-foreground transition" :class="projectPickerOpen ? 'rotate-180' : ''" />
        </button>
        <div
          v-if="projectPickerOpen"
          class="absolute left-0 top-10 z-50 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-lg"
        >
          <div class="border-b p-2">
            <div class="relative">
              <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input v-model="projectSearch" class="h-8 pl-8" placeholder="搜索项目" @keydown.stop />
            </div>
          </div>
          <div class="max-h-72 overflow-y-auto p-1">
            <button
              v-for="project in filteredProjects"
              :key="project.id"
              type="button"
              class="flex w-full items-center gap-2 rounded-sm px-2 py-2 text-left text-sm transition hover:bg-accent hover:text-accent-foreground"
              :class="project.id === selectedProjectId ? 'bg-accent text-accent-foreground' : ''"
              @click="selectProjectFromPicker(project.id)"
            >
              <Check class="size-4 shrink-0" :class="project.id === selectedProjectId ? 'opacity-100' : 'opacity-0'" />
              <span class="min-w-0 flex-1 truncate">{{ project.name }}</span>
              <span class="shrink-0 text-xs text-muted-foreground">{{ project.repos?.length || 0 }} 仓库</span>
            </button>
            <div v-if="!filteredProjects.length" class="px-3 py-8 text-center text-sm text-muted-foreground">
              没有匹配项目
            </div>
          </div>
        </div>
      </div>
      <Button :disabled="!selectedProject || !projectRepos.length" @click="openNewConversationDialog">
        <MessageSquarePlus class="size-4" />
        新建会话
      </Button>
      <Button variant="outline" :disabled="loadingProjects || loadingConversations" @click="loadProjects">
        <RefreshCw class="size-4" :class="loadingProjects || loadingConversations ? 'animate-spin' : ''" />
        刷新
      </Button>
    </div>
  </Teleport>

  <div class="flex h-[calc(100vh-5rem)] min-h-[42rem] flex-col gap-3">
    <div
      v-if="cleanupRetryConversation"
      role="alert"
      class="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning"
    >
      <div class="min-w-0">
        <div class="font-medium">
          {{ cleanupRetryConversation.status === 'archived' ? '会话已归档，但工作区清理未完成' : '会话已合并，但工作区清理未完成' }}
        </div>
        <div class="mt-0.5 break-words text-xs">
          {{ cleanupRetryConversation.cleanup_error || 'worktree 或任务分支清理失败，请重试。' }}
        </div>
      </div>
      <Button variant="outline" size="sm" :disabled="retryingCleanup" @click="retryConversationCleanup">
        <Loader2 v-if="retryingCleanup" class="size-4 animate-spin" />
        {{ retryingCleanup ? '清理中' : '重试清理' }}
      </Button>
    </div>
    <div class="grid min-h-0 flex-1 gap-4 xl:grid-cols-[18rem_minmax(0,1fr)_20rem]">
      <aside class="surface flex min-h-0 flex-col overflow-hidden">
        <div class="border-b px-3 py-2">
          <div class="text-sm font-medium">会话</div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <div v-if="loadingConversations" class="px-3 py-8 text-center text-sm text-muted-foreground">加载中...</div>
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="mb-2 flex items-start gap-1 rounded-md border p-1 transition hover:border-primary/50"
            :class="activeConv?.id === conv.id ? 'border-primary bg-primary/5' : 'border-border bg-card'"
          >
            <button
              type="button"
              class="min-w-0 flex-1 rounded p-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              @click="selectConversation(conv)"
            >
              <span class="line-clamp-2 text-sm font-medium leading-snug">{{ conv.title || '新会话' }}</span>
              <span class="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span class="font-mono-data">{{ conv.message_count }} 条</span>
                <span class="truncate">{{ displayDate(conv.last_message_at || conv.created_at) }}</span>
              </span>
              <span v-if="conv.branch_name" class="mt-2 flex items-center justify-between gap-2 border-t pt-2 text-[11px] text-muted-foreground">
                <span class="flex min-w-0 items-center gap-1 font-mono-data">
                  <GitBranch class="size-3 shrink-0" />
                  <span class="truncate">{{ conv.branch_name }}</span>
                </span>
                <span>{{ conv.completion_status === 'completed' ? '已合并' : conv.completion_status === 'merging' ? '合并中' : '开发中' }}</span>
              </span>
            </button>
            <Button
              size="icon-sm"
              variant="ghost"
              class="size-8 shrink-0 text-muted-foreground hover:text-destructive"
              :disabled="conv.completion_status === 'merging' || (archivingConversation && archiveTarget?.id === conv.id)"
              :aria-label="`归档会话：${conv.title || '新会话'}`"
              :title="conv.completion_status === 'merging' ? '会话正在合并，暂时不能归档' : '永久归档会话'"
              @click="openArchiveDialog(conv)"
            >
              <Archive class="size-3.5" />
            </Button>
          </div>
          <div v-if="!loadingConversations && !conversations.length" class="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
            暂无会话
          </div>
        </div>
      </aside>

      <main class="surface flex min-h-0 flex-col overflow-hidden">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b p-3">
          <div class="flex min-w-0 flex-wrap gap-1.5">
            <Button
              v-for="item in FILTERS"
              :key="item.value"
              size="sm"
              :variant="filterMode === item.value ? 'default' : 'outline'"
              @click="filterMode = item.value"
            >
              {{ item.label }}
            </Button>
          </div>
          <div class="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
            <div class="relative min-w-[12rem] max-w-sm flex-[1_1_16rem]">
              <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input v-model="timelineSearch" class="pl-8" placeholder="搜索当前会话" />
            </div>
            <div v-if="activeConv" class="flex shrink-0 items-center gap-2">
              <Button
                v-if="activeConv.completion_status !== 'completed'"
                size="sm"
                :disabled="activeConv.completion_status === 'merging' || completingConversation || !gitState?.available"
                @click="showCompleteDialog = true"
              >
                <Loader2 v-if="activeConv.completion_status === 'merging' || completingConversation" class="size-4 animate-spin" />
                <GitMerge v-else class="size-4" />
                {{ activeConv.completion_status === 'merging' ? '合并中' : '合并会话' }}
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="text-muted-foreground"
                :disabled="activeConv.completion_status === 'merging' || (archivingConversation && archiveTarget?.id === activeConv.id)"
                @click="openArchiveDialog(activeConv)"
              >
                <Archive class="size-4" />
                归档会话
              </Button>
            </div>
            <Button variant="outline" size="sm" @click="scrollToLatest()">
              最新
            </Button>
          </div>
        </div>

        <div v-if="activeConv && gitState?.available" class="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/15 px-3 py-2 xl:hidden">
          <div class="flex min-w-0 items-center gap-2 text-xs">
            <GitBranch class="size-4 shrink-0 text-muted-foreground" />
            <span class="max-w-[16rem] truncate font-mono-data font-medium">{{ gitState.branch_name }}</span>
            <span class="text-muted-foreground">{{ totalChangedFiles }} 个文件</span>
          </div>
          <div class="flex items-center gap-2">
            <Button variant="outline" size="sm" class="h-8" @click="openConversationGraph()">
              <GitCommitHorizontal class="size-4" />
              提交树
            </Button>
            <Button variant="outline" size="sm" class="h-8" @click="openDiff">
              <GitCompareArrows class="size-4" />
              对比
            </Button>
          </div>
        </div>

        <div ref="timelineRef" class="relative min-h-0 flex-1 overflow-y-auto px-4 py-5" @scroll="onTimelineScroll">
          <div v-if="!activeConv && !loadingMessages" class="flex h-full items-center justify-center text-center">
            <div class="max-w-sm">
              <Bot class="mx-auto size-8 text-muted-foreground/40" />
              <p class="mt-3 text-sm text-muted-foreground">选择会话，或直接发送第一轮需求</p>
            </div>
          </div>
          <div v-else-if="loadingMessages" class="flex h-full items-center justify-center text-sm text-muted-foreground">
            加载中...
          </div>
          <div v-else class="space-y-5">
            <template v-for="event in filteredEvents" :key="event.id">
              <div v-if="event.type === 'system_note'" class="flex justify-center">
                <span class="rounded-md border bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground">
                  {{ event.content || event.message?.content }} · {{ displayDate(event.created_at) }}
                </span>
              </div>

              <div v-else-if="event.type === 'user_request'" class="flex justify-end">
                <div class="max-w-[min(44rem,92%)] rounded-lg bg-primary px-4 py-3 text-primary-foreground">
                  <div
                    class="whitespace-pre-wrap break-words text-sm leading-relaxed"
                    :class="shouldClamp(event.message) && !expandedRequests[event.message.id] ? 'line-clamp-8' : ''"
                  >
                    {{ event.message.content }}
                  </div>
                  <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-primary-foreground/75">
                    <div class="flex min-w-0 flex-wrap gap-1.5">
                      <span v-for="name in eventRepoNames(event.message)" :key="name" class="rounded border border-primary-foreground/25 px-1.5 py-0.5">
                        {{ name }}
                      </span>
                      <span class="rounded border border-primary-foreground/25 px-1.5 py-0.5">
                        {{ providerLabel(metadata(event.message).provider) }}
                      </span>
                    </div>
                    <span class="font-mono-data">{{ displayDate(event.message.created_at) }}</span>
                  </div>
                  <div class="mt-2 flex flex-wrap justify-end gap-1.5">
                    <Button
                      v-if="shouldClamp(event.message)"
                      size="sm"
                      variant="secondary"
                      class="h-7 px-2 text-xs"
                      @click="expandedRequests[event.message.id] = !expandedRequests[event.message.id]"
                    >
                      {{ expandedRequests[event.message.id] ? '收起' : '展开' }}
                    </Button>
                    <Button size="sm" variant="secondary" class="h-7 px-2 text-xs" @click="continueFrom(event.message)">
                      基于这条继续
                    </Button>
                  </div>
                </div>
              </div>

              <div v-else-if="event.type === 'task_run'" class="flex justify-start">
                <TimelineTaskRun
                  :task-id="event.taskId"
                  :snapshot="taskSnapshot(event.message)"
                  :provider="event.message.provider"
                  :repo-names="eventRepoNames(event.message)"
                  :created-at="event.message.created_at"
                  @status-change="handleTaskStatusChange"
                />
              </div>
            </template>
            <div v-if="activeConv && !filteredEvents.length" class="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">
              没有匹配的时间线事件
            </div>
          </div>

          <Button
            v-if="hasNewActivity"
            class="absolute bottom-4 left-1/2 -translate-x-1/2 shadow"
            size="sm"
            @click="scrollToLatest()"
          >
            有新动态
          </Button>
        </div>

        <div class="border-t bg-card p-3">
          <div v-if="quoteText" class="mb-2 flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <Sparkles class="mt-0.5 size-3.5 shrink-0" />
            <span class="line-clamp-2 flex-1">{{ quoteText }}</span>
            <Button size="icon-sm" variant="ghost" class="size-6" @click="quoteText = ''">
              <X class="size-3.5" />
            </Button>
          </div>
          <div
            v-if="!providerAvailabilityLoading && programmingToolsError"
            role="alert"
            class="mb-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"
          >
            {{ programmingToolsError }}。
            <button
              type="button"
              class="ml-1 font-medium underline underline-offset-2"
              @click="loadProgrammingTools(selectedProjectId)"
            >重新加载</button>
          </div>
          <div
            v-else-if="!providerAvailabilityLoading && !canUseSelectedProvider"
            role="alert"
            class="mb-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning"
          >
            {{ selectedToolReason }}。
            <button
              type="button"
              class="ml-1 font-medium underline underline-offset-2"
              @click="router.push(`/projects/${selectedProjectId}?section=model-config`)"
            >前往配置</button>
          </div>
          <div class="flex items-end gap-2">
            <textarea
              ref="composerRef"
              v-model="input"
              rows="3"
              class="min-h-[5.25rem] flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed outline-none focus:ring-2 focus:ring-ring"
              :placeholder="activeConv?.completion_status === 'completed' ? '会话已合并，如需继续请新建会话' : activeConv?.completion_status === 'merging' ? '正在合并会话分支…' : '描述下一轮需求...'"
              :disabled="sending || !selectedProject || !projectRepos.length || ['merging', 'completed'].includes(activeConv?.completion_status || '')"
              aria-label="开发需求"
              @keydown="handleKeydown"
            />
            <Button class="h-10 px-4" :disabled="!canSend" @click="sendMessage">
              <Send class="size-4" />
              {{ sending ? '发送中' : '发送' }}
            </Button>
          </div>
        </div>
      </main>

      <aside class="surface hidden min-h-0 flex-col overflow-hidden xl:flex">
        <div class="border-b p-4">
          <div class="text-sm font-semibold">{{ selectedProject?.name || '未选择项目' }}</div>
          <div class="mt-1 text-xs text-muted-foreground">{{ projectRepos.length }} 个仓库</div>
        </div>

        <div class="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          <section class="space-y-2">
            <div class="flex items-center gap-2 text-sm font-medium">
              <FolderGit2 class="size-4 text-muted-foreground" />
              本轮仓库
            </div>
            <div class="space-y-1.5">
              <label
                v-for="repo in projectRepos"
                :key="repo.site_id"
                class="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm"
                :class="selectedRepoIds.includes(repo.site_id) ? 'border-primary bg-primary/5' : 'border-border'"
              >
                <input
                  type="checkbox"
                  class="size-4 accent-[hsl(var(--primary))]"
                  :checked="selectedRepoIds.includes(repo.site_id)"
                  :disabled="Boolean(activeConv)"
                  @change="toggleRepo(repo.site_id)"
                />
                <span class="min-w-0 flex-1 truncate">{{ repo.name }}</span>
              </label>
              <div v-if="selectedProject && !projectRepos.length" class="rounded-md border border-dashed px-3 py-5 text-center text-xs text-muted-foreground">
                当前项目还没有仓库
              </div>
            </div>
          </section>

          <section class="space-y-2">
            <div class="text-sm font-medium">编程工具</div>
            <ProgrammingToolPicker
              v-model="selectedProvider"
              :tools="availableTools"
              :loading="providerAvailabilityLoading"
              :disabled="Boolean(activeConv)"
              disabled-reason="会话创建后编程工具保持固定"
            />
            <div v-if="!providerAvailabilityLoading && programmingToolsError" role="alert" class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-3 text-xs text-destructive">
              {{ programmingToolsError }}。
              <button type="button" class="ml-1 font-medium underline underline-offset-2" @click="loadProgrammingTools(selectedProjectId)">重新加载</button>
            </div>
            <div v-else-if="!providerAvailabilityLoading && !availableTools.length" role="alert" class="rounded-md border border-dashed px-3 py-3 text-xs text-muted-foreground">
              当前项目没有可见的编程工具，请先完成项目模型配置并检查适配器状态。
            </div>
            <div v-if="!providerAvailabilityLoading && availableTools.some(tool => !tool.available)" class="space-y-1 text-xs text-muted-foreground">
              <p v-for="tool in availableTools.filter(item => !item.available)" :key="`${tool.id}-reason`">
                {{ tool.label }}：{{ programmingToolReason(tool) }}
              </p>
            </div>
          </section>

          <section v-if="activeConv" class="space-y-2">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 text-sm font-medium">
                <GitBranch class="size-4 text-muted-foreground" />
                分支信息
              </div>
              <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  class="status-dot"
                  :data-tone="activeConv.completion_status === 'completed' ? 'success' : activeConv.completion_status === 'merging' ? 'warning' : activeConv.completion_status === 'failed' ? 'danger' : 'muted'"
                  :data-pulse="activeConv.completion_status === 'merging'"
                />
                {{ completionLabel }}
              </span>
            </div>
            <div v-if="loadingGitState" class="rounded-md border px-3 py-4 text-center text-xs text-muted-foreground">
              正在读取 Git 状态...
            </div>
            <div v-else-if="gitState?.available" class="space-y-2">
              <div class="rounded-md border bg-muted/25 p-3">
                <div class="text-[11px] text-muted-foreground">会话分支</div>
                <div class="mt-1 break-all font-mono-data text-xs font-medium">{{ gitState.branch_name }}</div>
              </div>
              <div
                v-for="repo in gitState.repositories"
                :key="repo.site_id"
                class="rounded-md border p-3 text-xs"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="font-medium">{{ repo.name }}</span>
                  <span class="font-mono-data text-muted-foreground">{{ repo.main_branch }}</span>
                </div>
                <div class="mt-2 flex flex-wrap items-center gap-2 text-muted-foreground">
                  <span class="rounded border px-1.5 py-0.5">领先 {{ repo.ahead }}</span>
                  <span class="rounded border px-1.5 py-0.5">落后 {{ repo.behind }}</span>
                  <span>{{ repo.changed_files }} 文件</span>
                </div>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <Button variant="outline" size="sm" class="min-w-0" @click="openConversationGraph()">
                  <GitCommitHorizontal class="size-4" />
                  提交树
                </Button>
                <Button variant="outline" size="sm" class="min-w-0" @click="openDiff">
                  <GitCompareArrows class="size-4" />
                  修改对比
                  <span class="font-mono-data text-xs text-muted-foreground">{{ totalChangedFiles }}</span>
                </Button>
              </div>
            </div>
            <div v-else class="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
              当前会话没有 worktree 信息
            </div>
            <div v-if="activeConv.completion_error" role="alert" class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {{ activeConv.completion_error }}
            </div>
          </section>

          <section class="space-y-2">
            <div class="text-sm font-medium">默认阶段</div>
            <div class="flex flex-wrap gap-1.5">
              <Badge variant="outline">研究</Badge>
              <Badge variant="outline">计划</Badge>
              <Badge variant="outline">执行</Badge>
              <Badge variant="outline">评审</Badge>
            </div>
          </section>

          <section class="space-y-2">
            <div class="text-sm font-medium">会话摘要</div>
            <div class="grid grid-cols-2 gap-2">
              <div class="rounded-md border bg-muted/30 p-3">
                <div class="text-xs text-muted-foreground">消息</div>
                <div class="stat-num mt-1 text-xl">{{ activeConv?.message_count || messages.length }}</div>
              </div>
              <div class="rounded-md border bg-muted/30 p-3">
                <div class="text-xs text-muted-foreground">状态</div>
                <div class="mt-1 flex items-center gap-1.5 text-sm">
                  <span class="status-dot" :data-tone="statusTone(activeTaskStatus)" :data-pulse="activeTaskStatus === 'running'" />
                  {{ STATUS_LABEL[activeTaskStatus] || '空闲' }}
                </div>
              </div>
            </div>
          </section>
        </div>

        <div v-if="activeConv" class="grid grid-cols-2 gap-2 border-t p-3">
          <Button
            v-if="activeConv.completion_status !== 'completed'"
            class="min-h-11 min-w-0"
            :disabled="activeConv.completion_status === 'merging' || completingConversation || !gitState?.available"
            @click="showCompleteDialog = true"
          >
            <Loader2 v-if="activeConv.completion_status === 'merging' || completingConversation" class="size-4 animate-spin" />
            <GitMerge v-else class="size-4" />
            {{ activeConv.completion_status === 'merging' ? '正在合并' : activeConv.completion_status === 'failed' ? '重新合并会话' : '合并会话' }}
          </Button>
          <Button
            variant="outline"
            class="min-h-11 min-w-0 text-muted-foreground"
            :class="activeConv.completion_status === 'completed' ? 'col-span-2' : ''"
            :disabled="activeConv.completion_status === 'merging' || (archivingConversation && archiveTarget?.id === activeConv.id)"
            @click="openArchiveDialog(activeConv)"
          >
            <Archive class="size-4" />
            归档会话
          </Button>
        </div>
      </aside>
    </div>
  </div>

  <Dialog v-model:open="showNewConversationDialog">
    <DialogContent class="sm:max-w-[520px]">
      <DialogHeader>
        <DialogTitle>新建开发会话</DialogTitle>
      </DialogHeader>
      <div class="space-y-4">
        <div class="space-y-2">
          <label for="conversation-title" class="text-sm font-medium">任务描述</label>
          <Input
            id="conversation-title"
            v-model="newConversationTitle"
            autofocus
            placeholder="例如：优化登录页并补充错误提示"
            @keydown.enter.prevent="confirmCreateConversation"
          />
          <p class="text-xs leading-relaxed text-muted-foreground">
            将创建 <span class="font-mono-data">{{ newConversationBranchPrefix }}任务描述</span> 分支，所有修改保存在项目的 <span class="font-mono-data">.worktree</span> 目录。
          </p>
        </div>
        <div class="space-y-2">
          <div class="text-sm font-medium">编程工具</div>
          <ProgrammingToolPicker
            v-model="newConversationProvider"
            :tools="availableTools"
            :loading="providerAvailabilityLoading"
          />
          <div v-if="programmingToolsError" role="alert" class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-3 text-xs text-destructive">
            {{ programmingToolsError }}。
            <button type="button" class="ml-1 font-medium underline underline-offset-2" @click="loadProgrammingTools(selectedProjectId)">重新加载</button>
          </div>
          <div v-else-if="!availableTools.length" role="alert" class="rounded-md border border-dashed px-3 py-3 text-xs text-muted-foreground">
            当前项目没有可用的编程工具，暂时无法创建开发会话。
          </div>
          <div v-if="availableTools.some(tool => !tool.available)" class="space-y-1 text-xs text-muted-foreground">
            <p v-for="tool in availableTools.filter(item => !item.available)" :key="`${tool.id}-dialog-reason`">
              {{ tool.label }}：{{ programmingToolReason(tool) }}
            </p>
          </div>
        </div>
        <div class="space-y-2">
          <div class="flex items-center justify-between text-sm font-medium">
            <span>参与仓库</span>
            <span class="text-xs font-normal text-muted-foreground">{{ newConversationRepoIds.length }} 个</span>
          </div>
          <div class="grid max-h-44 gap-2 overflow-y-auto sm:grid-cols-2">
            <label
              v-for="repo in projectRepos"
              :key="repo.site_id"
              class="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm"
              :class="newConversationRepoIds.includes(repo.site_id) ? 'border-primary bg-primary/5' : 'border-border'"
            >
              <input
                type="checkbox"
                class="size-4 accent-[hsl(var(--primary))]"
                :checked="newConversationRepoIds.includes(repo.site_id)"
                @change="toggleNewConversationRepo(repo.site_id)"
              />
              <span class="min-w-0 flex-1 truncate">{{ repo.name }}</span>
              <span class="font-mono-data text-[11px] text-muted-foreground">{{ repo.main_branch || '自动' }}</span>
            </label>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="creatingConversation" @click="showNewConversationDialog = false">取消</Button>
        <Button
          :disabled="creatingConversation || !newConversationTitle.trim() || !newConversationRepoIds.length || !newConversationTool?.available"
          @click="confirmCreateConversation"
        >
          <Loader2 v-if="creatingConversation" class="size-4 animate-spin" />
          {{ creatingConversation ? '创建中' : '创建会话' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="showArchiveDialog">
    <DialogContent class="sm:max-w-[500px]">
      <DialogHeader>
        <DialogTitle>永久归档开发会话？</DialogTitle>
      </DialogHeader>
      <div class="space-y-3 text-sm">
        <p class="leading-relaxed">
          「{{ archiveTarget?.title || '新会话' }}」归档后无法恢复。
        </p>
        <p class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 leading-relaxed text-destructive">
          系统将清理该会话的 worktree 和任务分支。请先确认需要保留的修改已经完成合并或另行备份。
        </p>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="archivingConversation" @click="showArchiveDialog = false">取消</Button>
        <Button variant="destructive" :disabled="archivingConversation" @click="confirmArchiveConversation">
          <Loader2 v-if="archivingConversation" class="size-4 animate-spin" />
          {{ archivingConversation ? '归档中' : '确认永久归档' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="showCompleteDialog">
    <DialogContent class="sm:max-w-[560px]">
      <DialogHeader>
        <DialogTitle>合并会话</DialogTitle>
      </DialogHeader>
      <div class="space-y-3 text-sm">
        <p class="leading-relaxed text-muted-foreground">
          将调用 {{ providerLabel(activeConv?.provider) }} 只执行 Merge；不运行测试，不做额外代码修改。Merge 成功后系统会自动 Push 到远端，任务会在时间线中显示。
        </p>
        <div class="divide-y rounded-md border">
          <div v-for="repo in gitState?.repositories || []" :key="repo.site_id" class="px-3 py-2.5">
            <div class="font-medium">{{ repo.name }}</div>
            <div class="mt-1 break-all font-mono-data text-xs text-muted-foreground">
              {{ repo.branch_name }} → {{ repo.main_branch }}
            </div>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">合并成功后会删除任务分支和 worktree；修改对比将从会话快照继续提供。</p>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="completingConversation" @click="showCompleteDialog = false">取消</Button>
        <Button :disabled="completingConversation" @click="completeConversation">
          <Loader2 v-if="completingConversation" class="size-4 animate-spin" />
          <GitMerge v-else class="size-4" />
          {{ completingConversation ? '提交中' : '确认合并' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="diffOpen">
    <DialogContent class="flex h-[min(92dvh,1000px)] max-w-[min(98vw,1600px)] flex-col gap-0 overflow-hidden p-0">
      <DialogHeader class="shrink-0 border-b px-5 py-3.5">
        <DialogTitle class="flex items-center gap-2">
          <GitCompareArrows class="size-5" />
          修改对比
        </DialogTitle>
        <DialogDescription>
          从左侧文件树选择文件，右侧按修改前和修改后并排展示；未改动区域可按需向上或向下展开。
        </DialogDescription>
      </DialogHeader>
      <ConversationDiffViewer
        v-if="activeConv"
        :conversation-id="activeConv.id"
        :repositories="gitState?.repositories || []"
      />
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="graphOpen">
    <DialogContent class="flex max-h-[90dvh] max-w-[min(96vw,1120px)] flex-col gap-0 overflow-hidden p-0">
      <DialogHeader class="shrink-0 border-b px-4 py-4 sm:px-5">
        <DialogTitle class="flex items-center gap-2">
          <GitCommitHorizontal class="size-5" />
          任务分支提交树
        </DialogTitle>
        <DialogDescription>
          同时展示任务分支和主分支引用。选择 Commit 可查看详情；可用状态下支持将当前任务分支回滚到历史提交。
        </DialogDescription>
      </DialogHeader>

      <div class="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
        <div v-if="(gitState?.repositories || []).length > 1" class="mb-3 flex flex-wrap gap-2" role="group" aria-label="选择任务仓库提交树">
          <button
            v-for="repo in gitState?.repositories || []"
            :key="repo.site_id"
            type="button"
            :disabled="rollingBackConversationGraph"
            class="flex min-h-10 min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            :class="[
              conversationGraphRepoId === repo.site_id ? 'border-primary bg-primary/5 text-primary' : 'border-border bg-card',
              rollingBackConversationGraph ? 'cursor-not-allowed opacity-50' : '',
            ]"
            :aria-pressed="conversationGraphRepoId === repo.site_id"
            @click="selectConversationGraphRepository(repo.site_id)"
          >
            <FolderGit2 class="size-4 shrink-0" />
            <span class="max-w-48 truncate font-medium">{{ repo.name }}</span>
            <span class="hidden font-mono-data text-xs text-muted-foreground sm:inline">{{ repo.branch_name }}</span>
          </button>
        </div>

        <GitCommitGraph
          :graph="conversationGraph"
          :loading="loadingConversationGraph"
          :error="conversationGraphError"
          :rollback-pending="rollingBackConversationGraph"
          :rollback-disabled-reason="conversationRollbackDisabledReason"
          empty-text="当前任务分支还没有可展示的提交"
          @retry="loadConversationGraph"
          @rollback="rollbackConversationCommit"
        />
      </div>
    </DialogContent>
  </Dialog>
</template>
