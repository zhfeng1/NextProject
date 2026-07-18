<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { conversationsAPI, type Conversation } from '@/api/conversations'
import { projectsAPI } from '@/api/projects'
import { gitAPI, type GitGraph, type GitGraphCommit } from '@/api/git'
import { formatDate } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Plus,
  ArrowLeft,
  GitBranch,
  Code,
  Trash2,
  GitFork,
  FolderGit2,
  Bot,
  Loader2,
  Settings2,
  RefreshCw,
  GitCommitHorizontal,
  Archive,
  Boxes,
  CircleCheckBig,
  MessageSquare,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import BuildLogModal from '@/components/BuildLogModal.vue'
import ModelProviderSettings from '@/components/ModelProviderSettings.vue'
import GitCommitGraph from '@/components/GitCommitGraph.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

type ProjectSection = 'repositories' | 'git' | 'models' | 'archive'

const SECTION_QUERY: Record<ProjectSection, string | undefined> = {
  repositories: undefined,
  git: 'git',
  models: 'model-config',
  archive: 'archive',
}

const projectId = computed(() => String(route.params.id || ''))
const project = computed(() => projectStore.currentProject)

const showAddRepoDialog = ref(false)
const addingRepo = ref(false)
const addRepoForm = ref({
  mode: 'starter' as 'starter' | 'git',
  name: '',
  git_url: '',
  git_branch: '',
  git_username: '',
  git_password: '',
  start_command: '',
})

const buildLogOpen = ref(false)
const buildLogSiteId = ref('')
const buildLogSiteName = ref('')
const archivedConversations = ref<Conversation[]>([])
const loadingArchivedConversations = ref(false)
const cleaningConversationId = ref('')
const showMainBranchDialog = ref(false)
const mainBranchRepoId = ref('')
const mainBranchRepoName = ref('')
const mainBranchInput = ref('')
const savingMainBranch = ref(false)
const graphRepoId = ref('')
const projectGraph = ref<GitGraph | null>(null)
const loadingProjectGraph = ref(false)
const projectGraphError = ref('')
const rollingBackProjectGraph = ref(false)
const selectedProjectGraphBranch = ref('')
let projectGraphRequestSeq = 0
let archivedConversationsRequestSeq = 0
let projectContextRequestSeq = 0

const graphRepository = computed(() => (
  project.value?.repos?.find(repo => repo.site_id === graphRepoId.value) || null
))
const projectGraphBranches = computed(() => {
  const localBranches = (projectGraph.value?.branches || [])
    .filter(branch => branch.type === 'local_branch')
    .map(branch => branch.name)
  const selected = projectGraph.value?.branch || selectedProjectGraphBranch.value
  return [...new Set([selected, ...localBranches].filter(Boolean))]
})
const projectRollbackDisabledReason = computed(() => {
  if (!projectGraph.value) return ''
  if (projectGraph.value.branch !== projectGraph.value.default_branch) {
    return `仓库页仅支持回滚主分支 ${projectGraph.value.default_branch}，任务分支请在任务详情操作`
  }
  return ''
})

const readyRepoCount = computed(() => (
  project.value?.repos?.filter(repo => !['building', 'error'].includes(repo.status)).length || 0
))
const buildingRepoCount = computed(() => (
  project.value?.repos?.filter(repo => repo.status === 'building').length || 0
))
const cleanupAttentionCount = computed(() => (
  archivedConversations.value.filter(cleanupNeedsAttention).length
))

function normalizeSection(value: unknown): ProjectSection {
  const section = Array.isArray(value) ? value[0] : String(value || '')
  if (section === 'git') return 'git'
  if (section === 'models' || section === 'model-config') return 'models'
  if (section === 'archive' || section === 'archived') return 'archive'
  return 'repositories'
}

const activeSection = computed<ProjectSection>(() => normalizeSection(route.query.section))
const sectionTabs = computed(() => [
  {
    id: 'repositories' as const,
    label: '代码仓库',
    description: '仓库与主分支',
    icon: FolderGit2,
    count: project.value?.repos?.length || 0,
  },
  {
    id: 'git' as const,
    label: 'Git 历史',
    description: '分支与 Commit',
    icon: GitCommitHorizontal,
    count: project.value?.repos?.length || 0,
  },
  {
    id: 'models' as const,
    label: '模型配置',
    description: 'Provider 覆盖',
    icon: Bot,
    count: null,
  },
  {
    id: 'archive' as const,
    label: '归档会话',
    description: '历史与清理',
    icon: Archive,
    count: archivedConversations.value.length,
  },
])

function openBuildLog(siteId: string, name: string) {
  buildLogSiteId.value = siteId
  buildLogSiteName.value = name
  buildLogOpen.value = true
}

async function setActiveSection(section: ProjectSection) {
  await router.replace({
    path: `/projects/${projectId.value}`,
    query: { ...route.query, section: SECTION_QUERY[section] },
  })
  if (section === 'git' && graphRepoId.value && !projectGraph.value) {
    await loadProjectGraph()
  }
}

function handleSectionTabKeydown(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const tabs = sectionTabs.value
  let nextIndex = index
  if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length
  if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = tabs.length - 1
  const nextTab = tabs[nextIndex]
  setActiveSection(nextTab.id).then(() => {
    document.getElementById(`project-tab-${nextTab.id}`)?.focus()
  })
}

async function loadProjectContext(id: string) {
  if (!id) return
  const requestSeq = ++projectContextRequestSeq
  projectGraphRequestSeq += 1
  graphRepoId.value = ''
  selectedProjectGraphBranch.value = ''
  projectGraph.value = null
  projectGraphError.value = ''
  archivedConversations.value = []

  try {
    const [projectResponse] = await Promise.all([
      projectsAPI.get(id),
      loadArchivedConversations(id),
    ])
    if (requestSeq !== projectContextRequestSeq || id !== projectId.value) return
    projectStore.currentProject = projectResponse.project
    const firstRepoId = projectResponse.project.repos?.[0]?.site_id || ''
    graphRepoId.value = firstRepoId
    if (firstRepoId && activeSection.value === 'git') await loadProjectGraph()
  } catch (error: any) {
    if (requestSeq === projectContextRequestSeq && id === projectId.value) {
      toast.error(error?.response?.data?.detail || '加载项目详情失败')
    }
  }
}

async function refreshCurrentProject(id = projectId.value) {
  const response = await projectsAPI.get(id)
  if (id === projectId.value) projectStore.currentProject = response.project
  return response.project
}

onMounted(() => loadProjectContext(projectId.value))

watch(projectId, (id, previousId) => {
  if (id && id !== previousId) loadProjectContext(id)
})

watch(activeSection, async (section) => {
  if (section === 'git' && graphRepoId.value && !projectGraph.value) {
    await loadProjectGraph()
  }
})

let pollTimer: ReturnType<typeof setInterval> | null = null
const hasBuildingRepos = computed(() => project.value?.repos?.some(r => r.status === 'building') ?? false)

watch(hasBuildingRepos, (building) => {
  if (building && !pollTimer) {
    pollTimer = setInterval(() => {
      refreshCurrentProject().then(() => {
        if (!hasBuildingRepos.value && pollTimer) {
          clearInterval(pollTimer)
          pollTimer = null
          toast.success('仓库克隆已完成')
        }
      })
    }, 5000)
  } else if (!building && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}, { immediate: true })

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

const handleAddRepo = async () => {
  if (!addRepoForm.value.name.trim()) return
  if (addRepoForm.value.mode === 'git' && !addRepoForm.value.git_url.trim()) {
    toast.warning('请输入 Git URL')
    return
  }
  if (addRepoForm.value.git_password && !addRepoForm.value.git_username) {
    toast.warning('填写 Git 密码时请同时填写用户名')
    return
  }
  addingRepo.value = true
  try {
    await projectStore.addRepo(projectId.value, {
      name: addRepoForm.value.name.trim(),
      starter: addRepoForm.value.mode === 'starter' ? 'python-vue' : undefined,
      git_url: addRepoForm.value.mode === 'git' ? (addRepoForm.value.git_url || undefined) : undefined,
      git_branch: addRepoForm.value.mode === 'git' ? (addRepoForm.value.git_branch || undefined) : undefined,
      git_username: addRepoForm.value.mode === 'git' ? (addRepoForm.value.git_username || undefined) : undefined,
      git_password: addRepoForm.value.mode === 'git' ? (addRepoForm.value.git_password || undefined) : undefined,
      start_command: addRepoForm.value.mode === 'git' ? (addRepoForm.value.start_command || undefined) : undefined,
    })
    showAddRepoDialog.value = false
    addRepoForm.value = { mode: 'starter', name: '', git_url: '', git_branch: '', git_username: '', git_password: '', start_command: '' }
    toast.success('仓库添加成功')
    if (!graphRepoId.value) {
      const firstRepoId = project.value?.repos?.[0]?.site_id || ''
      graphRepoId.value = firstRepoId
      if (firstRepoId && activeSection.value === 'git') await loadProjectGraph()
    }
  } catch {
    toast.error('添加仓库失败')
  } finally {
    addingRepo.value = false
  }
}

const handleDeleteRepo = async (repoId: string, repoName: string) => {
  if (!confirm(`确认删除仓库「${repoName}」？此操作不可恢复。`)) return
  try {
    await projectStore.deleteRepo(projectId.value, repoId)
    if (graphRepoId.value === repoId) {
      const nextRepoId = project.value?.repos?.[0]?.site_id || ''
      graphRepoId.value = nextRepoId
      selectedProjectGraphBranch.value = ''
      projectGraph.value = null
      projectGraphError.value = ''
      projectGraphRequestSeq += 1
      if (nextRepoId && activeSection.value === 'git') await loadProjectGraph()
    }
    toast.success('仓库已删除')
  } catch {
    toast.error('删除仓库失败')
  }
}

function openMainBranchDialog(repo: { site_id: string; name: string; main_branch?: string }) {
  mainBranchRepoId.value = repo.site_id
  mainBranchRepoName.value = repo.name
  mainBranchInput.value = repo.main_branch || ''
  showMainBranchDialog.value = true
}

async function saveMainBranch() {
  const branch = mainBranchInput.value.trim()
  if (!branch || !mainBranchRepoId.value) return
  savingMainBranch.value = true
  try {
    await projectsAPI.updateRepoMainBranch(projectId.value, mainBranchRepoId.value, branch)
    await refreshCurrentProject()
    if (graphRepoId.value === mainBranchRepoId.value) {
      selectedProjectGraphBranch.value = ''
      projectGraph.value = null
      projectGraphError.value = ''
      projectGraphRequestSeq += 1
      if (activeSection.value === 'git') await loadProjectGraph()
    }
    showMainBranchDialog.value = false
    toast.success('主分支已更新')
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '更新主分支失败')
  } finally {
    savingMainBranch.value = false
  }
}

function repoStatusTone(status: string): 'success' | 'muted' | 'warning' | 'danger' {
  return ({ running: 'success', ready: 'success', stopped: 'muted', building: 'warning', error: 'danger' } as const)[status as 'running'] ?? 'muted'
}

function repoStatusLabel(status: string) {
  return ({
    running: '运行中',
    ready: '已就绪',
    stopped: '已停止',
    building: '构建中',
    error: '异常',
  } as Record<string, string>)[status] || status
}

function displayDate(value?: string | null) {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

async function loadArchivedConversations(id = projectId.value) {
  const requestSeq = ++archivedConversationsRequestSeq
  loadingArchivedConversations.value = true
  try {
    const res = await conversationsAPI.listProject(id, 100, 'archived')
    if (requestSeq !== archivedConversationsRequestSeq || id !== projectId.value) return
    archivedConversations.value = res.conversations || []
  } catch {
    if (requestSeq === archivedConversationsRequestSeq && id === projectId.value) {
      toast.error('加载归档会话失败')
    }
  } finally {
    if (requestSeq === archivedConversationsRequestSeq) loadingArchivedConversations.value = false
  }
}

function cleanupNeedsAttention(conv: Conversation) {
  return ['warning', 'failed'].includes(conv.cleanup_status || '')
}

function cleanupStatusLabel(status?: string) {
  return ({
    retained: '未清理',
    cleaning: '清理中',
    cleaned: '已清理',
    pending: '清理中',
    running: '清理中',
    completed: '已清理',
    success: '已清理',
    warning: '清理未完成',
    failed: '清理失败',
  } as Record<string, string>)[status || ''] || status || '未记录'
}

async function retryConversationCleanup(conv: Conversation) {
  cleaningConversationId.value = conv.id
  try {
    const res = await conversationsAPI.cleanup(conv.id)
    const index = archivedConversations.value.findIndex(item => item.id === conv.id)
    if (index !== -1) archivedConversations.value[index] = res.conversation
    if (cleanupNeedsAttention(res.conversation)) {
      toast.warning('清理仍未完成，请根据错误信息处理后重试')
    } else {
      toast.success('会话工作区已清理')
    }
  } catch (error: any) {
    const index = archivedConversations.value.findIndex(item => item.id === conv.id)
    if (index !== -1) {
      archivedConversations.value[index] = {
        ...conv,
        cleanup_status: 'failed',
        cleanup_error: error?.response?.data?.detail || '重试清理失败',
      }
    }
    toast.error(error?.response?.data?.detail || '重试清理失败')
  } finally {
    cleaningConversationId.value = ''
  }
}

async function selectGraphRepository(repoId: string) {
  if (!repoId) return
  graphRepoId.value = repoId
  selectedProjectGraphBranch.value = ''
  projectGraph.value = null
  await loadProjectGraph()
}

async function loadProjectGraph() {
  if (!graphRepoId.value) return
  const requestSeq = ++projectGraphRequestSeq
  const requestedRepoId = graphRepoId.value
  const requestedBranch = selectedProjectGraphBranch.value
  loadingProjectGraph.value = true
  projectGraphError.value = ''
  try {
    const res = await gitAPI.getProjectGraph(projectId.value, requestedRepoId, 200, 0, requestedBranch)
    if (requestSeq !== projectGraphRequestSeq) return
    projectGraph.value = res.graph
    selectedProjectGraphBranch.value = res.graph.branch
  } catch (error: any) {
    if (requestSeq !== projectGraphRequestSeq) return
    projectGraph.value = null
    projectGraphError.value = error?.response?.data?.detail || '无法读取仓库的提交历史'
  } finally {
    if (requestSeq === projectGraphRequestSeq) loadingProjectGraph.value = false
  }
}

async function selectProjectGraphBranch(event: Event) {
  selectedProjectGraphBranch.value = (event.target as HTMLSelectElement).value
  await loadProjectGraph()
}

async function rollbackProjectCommit(commit: GitGraphCommit) {
  if (!graphRepoId.value || rollingBackProjectGraph.value) return
  rollingBackProjectGraph.value = true
  try {
    const res = await gitAPI.rollbackProject(projectId.value, graphRepoId.value, commit.sha)
    projectGraph.value = res.graph
    toast.success(`${graphRepository.value?.name || '仓库'} 已回滚到 ${commit.short_sha}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '回滚失败，请确认工作区干净且提交属于当前主分支')
  } finally {
    rollingBackProjectGraph.value = false
  }
}
</script>

<template>
  <div v-if="project" class="space-y-5 pb-8">
    <div class="flex items-center gap-2 text-sm text-muted-foreground">
      <Button variant="ghost" size="sm" class="-ml-2" @click="router.push('/projects')">
        <ArrowLeft class="size-4" />
        返回项目
      </Button>
      <span aria-hidden="true">/</span>
      <span class="max-w-48 truncate font-medium text-foreground">{{ project.name }}</span>
    </div>

    <section class="overflow-hidden rounded-2xl border bg-card shadow-sm">
      <div class="flex flex-col gap-5 p-5 md:p-6 lg:flex-row lg:items-center lg:justify-between">
        <div class="flex min-w-0 items-start gap-4">
          <div class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Boxes class="size-6" />
          </div>
          <div class="min-w-0">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <h1 class="min-w-0 max-w-full flex-1 truncate text-2xl font-semibold tracking-tight">{{ project.name }}</h1>
              <span class="rounded-full border bg-muted/40 px-2 py-0.5 text-xs font-medium text-muted-foreground">项目</span>
            </div>
            <p class="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
              {{ project.description || '管理项目仓库、Git 历史、编程工具模型配置和已归档的开发会话。' }}
            </p>
          </div>
        </div>
        <div class="flex flex-wrap gap-2 lg:justify-end">
          <Button @click="router.push({ path: '/tasks', query: { project_id: projectId } })">
            <MessageSquare class="size-4" />
            开发会话
          </Button>
          <Button v-if="project.repos?.length" variant="outline" @click="router.push(`/projects/${projectId}/edit`)">
            <Code class="size-4" />
            打开编辑器
          </Button>
        </div>
      </div>

      <div class="grid grid-cols-2 border-t bg-muted/15 md:grid-cols-4">
        <div class="flex min-w-0 items-center gap-3 border-b p-4 md:border-b-0 md:border-r">
          <FolderGit2 class="size-5 shrink-0 text-muted-foreground" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ project.repos?.length || 0 }}</div>
            <div class="truncate text-xs text-muted-foreground">代码仓库</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 border-b border-l p-4 md:border-b-0 md:border-l-0 md:border-r">
          <CircleCheckBig class="size-5 shrink-0 text-success" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ readyRepoCount }}</div>
            <div class="truncate text-xs text-muted-foreground">可用仓库</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 p-4 md:border-r">
          <Loader2 class="size-5 shrink-0 text-warning" :class="buildingRepoCount ? 'animate-spin' : ''" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ buildingRepoCount }}</div>
            <div class="truncate text-xs text-muted-foreground">构建中</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 border-l p-4 md:border-l-0">
          <Archive class="size-5 shrink-0 text-muted-foreground" />
          <div class="min-w-0">
            <div class="flex items-baseline gap-1.5">
              <span class="text-xl font-semibold tabular-nums">{{ archivedConversations.length }}</span>
              <span v-if="cleanupAttentionCount" class="text-xs font-medium text-warning">{{ cleanupAttentionCount }} 待清理</span>
            </div>
            <div class="truncate text-xs text-muted-foreground">归档会话</div>
          </div>
        </div>
      </div>
    </section>

    <nav aria-label="项目详情分区" class="rounded-xl border bg-muted/25 p-1.5">
      <div role="tablist" aria-label="项目详情" class="grid grid-cols-2 gap-1.5 md:grid-cols-4">
        <button
          v-for="(tab, index) in sectionTabs"
          :id="`project-tab-${tab.id}`"
          :key="tab.id"
          type="button"
          role="tab"
          :aria-selected="activeSection === tab.id"
          :aria-controls="activeSection === tab.id ? `project-section-${tab.id}` : undefined"
          :tabindex="activeSection === tab.id ? 0 : -1"
          class="flex min-h-12 min-w-0 items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors duration-200 hover:bg-background/70 focus-visible:ring-2 focus-visible:ring-ring"
          :class="activeSection === tab.id ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground'"
          @click="setActiveSection(tab.id)"
          @keydown="handleSectionTabKeydown($event, index)"
        >
          <component :is="tab.icon" class="size-4 shrink-0" :class="activeSection === tab.id ? 'text-primary' : ''" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium">{{ tab.label }}</span>
            <span class="hidden truncate text-[11px] text-muted-foreground sm:block">{{ tab.description }}</span>
          </span>
          <span
            v-if="tab.count !== null"
            class="rounded-full border bg-muted/50 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
          >
            {{ tab.count }}
          </span>
        </button>
      </div>
    </nav>

    <section
      v-if="activeSection === 'repositories'"
      id="project-section-repositories"
      role="tabpanel"
      aria-labelledby="project-tab-repositories"
      class="overflow-hidden rounded-xl border bg-card"
    >
      <div class="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between md:p-5">
        <div>
          <h2 class="text-base font-semibold">代码仓库</h2>
          <p class="mt-1 text-sm text-muted-foreground">管理仓库状态、主分支和项目代码入口。</p>
        </div>
        <Button @click="showAddRepoDialog = true">
          <Plus class="size-4" />
          添加仓库
        </Button>
      </div>

      <div v-if="project.repos?.length" class="grid gap-4 p-4 md:grid-cols-2 md:p-5 xl:grid-cols-3">
        <Card
          v-for="repo in project.repos"
          :key="repo.site_id"
          class="group flex min-w-0 flex-col shadow-none transition-colors duration-200 hover:border-primary/35"
        >
          <CardHeader class="pb-2">
            <CardTitle class="flex min-w-0 items-center gap-2 text-base font-semibold">
              <div class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <GitBranch class="size-4" />
              </div>
              <span class="min-w-0 flex-1 truncate">{{ repo.name }}</span>
              <span class="status-dot" :data-tone="repoStatusTone(repo.status)" :data-pulse="repo.status === 'building'" />
            </CardTitle>
          </CardHeader>
          <CardContent class="flex-1 space-y-3 text-sm">
            <button
              v-if="repo.status === 'building'"
              type="button"
              class="flex min-h-10 w-full items-center justify-between rounded-md border border-warning/25 bg-warning/5 px-3 text-left text-warning transition-colors hover:bg-warning/10"
              @click.stop="openBuildLog(repo.site_id, repo.name)"
            >
              <span class="flex items-center gap-2 font-medium">
                <Loader2 class="size-4 animate-spin" />
                正在构建
              </span>
              <span class="text-xs">查看日志</span>
            </button>
            <div v-else class="flex items-center justify-between text-xs">
              <span class="text-muted-foreground">运行状态</span>
              <span class="font-medium">{{ repoStatusLabel(repo.status) }}</span>
            </div>
            <div class="flex items-center gap-2 rounded-md border bg-muted/25 px-3 py-2.5 text-xs">
              <GitBranch class="size-3.5 shrink-0 text-muted-foreground" />
              <span class="text-muted-foreground">主分支</span>
              <span class="min-w-0 flex-1 truncate text-right font-mono-data font-medium">{{ repo.main_branch || '自动检测' }}</span>
            </div>
            <div class="flex items-center justify-between text-xs text-muted-foreground">
              <span>创建时间</span>
              <span class="font-mono-data">{{ formatDate(repo.created_at) }}</span>
            </div>
          </CardContent>
          <div class="grid grid-cols-2 gap-2 border-t p-3">
            <Button variant="ghost" size="sm" class="min-w-0 text-muted-foreground" @click.stop="openMainBranchDialog(repo)">
              <Settings2 class="size-3.5" />
              主分支
            </Button>
            <Button variant="ghost" size="sm" class="min-w-0 text-muted-foreground hover:text-destructive" @click.stop="handleDeleteRepo(repo.site_id, repo.name)">
              <Trash2 class="size-3.5" />
              删除
            </Button>
          </div>
        </Card>
      </div>

      <div v-else class="px-5 py-20 text-center">
        <div class="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <FolderGit2 class="size-6" />
        </div>
        <h3 class="mt-4 text-sm font-semibold">项目还没有代码仓库</h3>
        <p class="mt-1 text-sm text-muted-foreground">添加 Python 起始仓库，或从现有 Git 地址导入。</p>
        <Button class="mt-4" @click="showAddRepoDialog = true">
          <Plus class="size-4" />
          添加第一个仓库
        </Button>
      </div>
    </section>

    <section
      v-else-if="activeSection === 'git'"
      id="project-section-git"
      role="tabpanel"
      aria-labelledby="project-tab-git"
      class="space-y-4 rounded-xl border bg-card p-4 md:p-5"
    >
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 class="flex items-center gap-2 text-base font-semibold">
            <GitCommitHorizontal class="size-5 text-muted-foreground" />
            Git 历史
          </h2>
          <p class="mt-1 text-sm text-muted-foreground">查看仓库分支树和 Commit，主分支支持安全确认后回滚。</p>
        </div>
        <Button variant="outline" size="sm" :disabled="loadingProjectGraph || !graphRepoId" @click="loadProjectGraph">
          <RefreshCw class="size-4" :class="loadingProjectGraph ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>

      <template v-if="project.repos?.length">
        <div class="flex max-w-full flex-wrap gap-2" role="group" aria-label="选择仓库提交树">
          <button
            v-for="repo in project.repos"
            :key="repo.site_id"
            type="button"
            :disabled="rollingBackProjectGraph"
            class="flex min-h-11 w-full max-w-full min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors duration-200 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring sm:w-auto"
            :class="[
              graphRepoId === repo.site_id ? 'border-primary bg-primary/5 text-primary' : 'border-border bg-background',
              rollingBackProjectGraph ? 'cursor-not-allowed opacity-50' : '',
            ]"
            :aria-pressed="graphRepoId === repo.site_id"
            @click="selectGraphRepository(repo.site_id)"
          >
            <FolderGit2 class="size-4 shrink-0" />
            <span class="min-w-0 flex-1 truncate font-medium sm:max-w-48">{{ repo.name }}</span>
            <span class="max-w-28 min-w-0 truncate font-mono-data text-xs text-muted-foreground">{{ repo.main_branch || '自动' }}</span>
          </button>
        </div>

        <div v-if="projectGraphBranches.length" class="flex flex-col gap-2 rounded-lg border bg-muted/20 p-3 sm:flex-row sm:items-center">
          <Label for="project-graph-branch" class="shrink-0">查看分支</Label>
          <div class="relative min-w-0 sm:w-80">
            <GitBranch class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <select
              id="project-graph-branch"
              :value="selectedProjectGraphBranch"
              class="h-11 w-full rounded-md border border-input bg-background py-2 pl-9 pr-8 font-mono-data text-sm shadow-sm outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loadingProjectGraph || rollingBackProjectGraph"
              @change="selectProjectGraphBranch"
            >
              <option v-for="branch in projectGraphBranches" :key="branch" :value="branch">{{ branch }}</option>
            </select>
          </div>
          <span class="text-xs leading-relaxed text-muted-foreground">
            默认主分支：<span class="font-mono-data">{{ projectGraph?.default_branch || graphRepository?.main_branch || '自动检测' }}</span>
          </span>
        </div>

        <GitCommitGraph
          :graph="projectGraph"
          :loading="loadingProjectGraph"
          :error="projectGraphError"
          :rollback-pending="rollingBackProjectGraph"
          :rollback-disabled-reason="projectRollbackDisabledReason"
          @retry="loadProjectGraph"
          @rollback="rollbackProjectCommit"
        />
      </template>

      <div v-else class="rounded-lg border border-dashed px-5 py-16 text-center">
        <FolderGit2 class="mx-auto size-8 text-muted-foreground/50" />
        <p class="mt-3 text-sm text-muted-foreground">添加仓库后即可查看分支和 Commit 历史。</p>
        <Button variant="outline" class="mt-4" @click="setActiveSection('repositories')">前往添加仓库</Button>
      </div>
    </section>

    <section
      v-else-if="activeSection === 'models'"
      id="project-section-models"
      role="tabpanel"
      aria-labelledby="project-tab-models"
      class="rounded-xl border bg-card p-4 md:p-5"
    >
      <ModelProviderSettings
        scope-type="project"
        :project-id="projectId"
        title="项目模型配置"
        description="仅在这个项目内覆盖全局 Provider；未配置兼容项时自动使用全局模型。"
      />
    </section>

    <section
      v-else
      id="project-section-archive"
      role="tabpanel"
      aria-labelledby="project-tab-archive"
      class="overflow-hidden rounded-xl border bg-card"
    >
      <div class="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between md:p-5">
        <div>
          <h2 class="text-base font-semibold">归档会话</h2>
          <p class="mt-1 text-sm text-muted-foreground">归档不可恢复；系统会清理对应 worktree 和本地任务分支。</p>
        </div>
        <Button variant="outline" size="sm" :disabled="loadingArchivedConversations" @click="loadArchivedConversations">
          <RefreshCw class="size-4" :class="loadingArchivedConversations ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>

      <div v-if="loadingArchivedConversations" class="px-5 py-16 text-center text-sm text-muted-foreground">
        <Loader2 class="mx-auto mb-3 size-5 animate-spin" />
        正在加载归档会话
      </div>
      <div v-else-if="archivedConversations.length" class="divide-y">
        <div
          v-for="conv in archivedConversations"
          :key="conv.id"
          class="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between md:px-5"
        >
          <div class="min-w-0">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <h3 class="truncate text-sm font-medium">{{ conv.title || '新会话' }}</h3>
              <span class="rounded-full border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
                {{ cleanupStatusLabel(conv.cleanup_status) }}
              </span>
            </div>
            <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{{ conv.message_count }} 条消息</span>
              <span>{{ displayDate(conv.last_message_at || conv.updated_at || conv.created_at) }}</span>
              <span v-if="conv.branch_name" class="font-mono-data">{{ conv.branch_name }}</span>
            </div>
            <div
              v-if="cleanupNeedsAttention(conv)"
              role="alert"
              class="mt-2 max-w-3xl break-words rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-relaxed text-warning"
            >
              {{ conv.cleanup_error || 'worktree 或任务分支清理未完成，请重试。' }}
            </div>
          </div>
          <Button
            v-if="cleanupNeedsAttention(conv)"
            variant="outline"
            size="sm"
            class="shrink-0"
            :disabled="cleaningConversationId === conv.id"
            @click="retryConversationCleanup(conv)"
          >
            <Loader2 v-if="cleaningConversationId === conv.id" class="size-4 animate-spin" />
            {{ cleaningConversationId === conv.id ? '清理中' : '重试清理' }}
          </Button>
        </div>
      </div>
      <div v-else class="px-5 py-20 text-center">
        <Archive class="mx-auto size-8 text-muted-foreground/50" />
        <h3 class="mt-3 text-sm font-semibold">暂无归档会话</h3>
        <p class="mt-1 text-sm text-muted-foreground">已合并或放弃的开发会话归档后会显示在这里。</p>
      </div>
    </section>

    <Dialog v-model:open="showAddRepoDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加仓库</DialogTitle>
          <DialogDescription>创建默认 Python + Vue 仓库，或导入已有 Git 仓库。</DialogDescription>
        </DialogHeader>
        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-2 rounded-md bg-muted p-1">
            <Button
              variant="ghost"
              size="sm"
              :class="addRepoForm.mode === 'starter' ? 'bg-background shadow-sm' : 'text-muted-foreground'"
              @click="addRepoForm.mode = 'starter'"
            >
              <Code class="size-4" />
              Python
            </Button>
            <Button
              variant="ghost"
              size="sm"
              :class="addRepoForm.mode === 'git' ? 'bg-background shadow-sm' : 'text-muted-foreground'"
              @click="addRepoForm.mode = 'git'"
            >
              <GitFork class="size-4" />
              Git
            </Button>
          </div>
          <div class="space-y-2">
            <Label for="add-repo-name">仓库名称 <span class="text-destructive">*</span></Label>
            <Input id="add-repo-name" v-model="addRepoForm.name" :placeholder="addRepoForm.mode === 'starter' ? 'app' : '输入仓库名称'" />
          </div>
          <div v-if="addRepoForm.mode === 'git'" class="space-y-2">
            <Label for="add-repo-git-url">Git URL <span class="text-destructive">*</span></Label>
            <Input id="add-repo-git-url" v-model="addRepoForm.git_url" placeholder="https://github.com/user/repo.git" />
          </div>
          <div v-if="addRepoForm.mode === 'git'" class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label for="add-repo-git-branch">主分支 / 克隆分支</Label>
              <Input id="add-repo-git-branch" v-model="addRepoForm.git_branch" placeholder="例如 main 或 dev（可选）" />
            </div>
            <div class="space-y-2">
              <Label for="add-repo-git-username">Git 用户名</Label>
              <Input id="add-repo-git-username" v-model="addRepoForm.git_username" placeholder="私有仓库可填" />
            </div>
          </div>
          <div v-if="addRepoForm.mode === 'git'" class="space-y-2">
            <Label for="add-repo-git-password">Git 密码 / Token</Label>
            <Input id="add-repo-git-password" v-model="addRepoForm.git_password" type="password" placeholder="PAT 或访问令牌（可选）" />
          </div>
          <div v-if="addRepoForm.mode === 'git'" class="space-y-2">
            <Label for="add-repo-start-command">启动命令</Label>
            <Input id="add-repo-start-command" v-model="addRepoForm.start_command" placeholder="python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAddRepoDialog = false">取消</Button>
          <Button @click="handleAddRepo" :disabled="addingRepo || !addRepoForm.name.trim()">
            {{ addingRepo ? '添加中…' : '添加' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="showMainBranchDialog">
      <DialogContent class="sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle>设置主分支</DialogTitle>
          <DialogDescription>主分支决定新会话的创建基线，以及合并会话时的目标分支。</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <div class="text-sm text-muted-foreground">仓库：{{ mainBranchRepoName }}</div>
          <div class="space-y-2">
            <Label for="main-branch">主分支名称</Label>
            <Input
              id="main-branch"
              v-model="mainBranchInput"
              aria-describedby="main-branch-help"
              placeholder="例如 dev"
              @keydown.enter.prevent="saveMainBranch"
            />
            <p id="main-branch-help" class="text-xs leading-relaxed text-muted-foreground">
              新开发会话会从该分支创建 worktree，合并会话时也会合并回该分支。分支必须已存在于本地或 origin。
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" :disabled="savingMainBranch" @click="showMainBranchDialog = false">取消</Button>
          <Button :disabled="savingMainBranch || !mainBranchInput.trim()" @click="saveMainBranch">
            <Loader2 v-if="savingMainBranch" class="size-4 animate-spin" />
            {{ savingMainBranch ? '保存中' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <BuildLogModal
      v-model:open="buildLogOpen"
      :site-id="buildLogSiteId"
      :site-name="buildLogSiteName"
    />
  </div>
</template>
