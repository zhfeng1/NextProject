<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardContent, CardFooter } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import type { Project } from '@/types/models'
import {
  Plus,
  FolderKanban,
  Trash2,
  MessageSquarePlus,
  Search,
  FolderGit2,
  Loader2,
  TriangleAlert,
  Boxes,
  X,
  ArrowUpDown,
  ArrowRight,
  FolderPlus,
  RefreshCw,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const router = useRouter()
const projectStore = useProjectStore()

type ProjectSort = 'updated' | 'name' | 'repos'
type StatusTone = 'success' | 'muted' | 'warning' | 'danger'

const searchQuery = ref('')
const sortBy = ref<ProjectSort>('updated')
const loadError = ref('')
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })
const showDeleteDialog = ref(false)
const deleting = ref(false)
const projectPendingDelete = ref<Project | null>(null)

const totalRepoCount = computed(() => (
  projectStore.projects.reduce((total, project) => total + repoCount(project), 0)
))
const normalRepoCount = computed(() => (
  projectStore.projects.reduce((total, project) => (
    total + (project.repos || []).filter(repo => !['building', 'error'].includes(repo.status)).length
  ), 0)
))
const buildingRepoCount = computed(() => (
  projectStore.projects.reduce((total, project) => (
    total + (project.repos || []).filter(repo => repo.status === 'building').length
  ), 0)
))
const errorRepoCount = computed(() => (
  projectStore.projects.reduce((total, project) => (
    total + (project.repos || []).filter(repo => repo.status === 'error').length
  ), 0)
))
const initialLoading = computed(() => projectStore.loading && !projectStore.projects.length)

const filteredProjects = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  const projects = projectStore.projects.filter((project) => {
    if (!query) return true
    const searchText = [
      project.name,
      project.description,
      project.id,
      ...(project.repos || []).map(repo => repo.name),
    ].join(' ').toLocaleLowerCase()
    return searchText.includes(query)
  })

  return [...projects].sort((left, right) => {
    if (sortBy.value === 'name') return left.name.localeCompare(right.name, 'zh-CN')
    if (sortBy.value === 'repos') return repoCount(right) - repoCount(left)
    return projectTimestamp(right) - projectTimestamp(left)
  })
})

async function loadProjects() {
  loadError.value = ''
  try {
    await projectStore.fetchProjects()
  } catch (error: any) {
    loadError.value = error?.response?.data?.detail || '项目列表加载失败，请检查服务状态后重试。'
  }
}

onMounted(loadProjects)

async function handleCreate() {
  if (!createForm.value.name.trim() || creating.value) return
  creating.value = true
  try {
    const project = await projectStore.createProject({
      name: createForm.value.name.trim(),
      description: createForm.value.description.trim() || undefined,
    })
    showCreateDialog.value = false
    createForm.value = { name: '', description: '' }
    toast.success('项目创建成功')
    router.push(`/projects/${project.id}`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '创建项目失败')
  } finally {
    creating.value = false
  }
}

function requestDelete(project: Project) {
  if (deleting.value) return
  projectPendingDelete.value = project
  showDeleteDialog.value = true
}

function handleCreateDialogOpenChange(open: boolean) {
  if (!open && creating.value) return
  showCreateDialog.value = open
}

function handleDeleteDialogOpenChange(open: boolean) {
  if (!open && deleting.value) return
  showDeleteDialog.value = open
  if (!open) projectPendingDelete.value = null
}

async function clearSearch() {
  searchQuery.value = ''
  await nextTick()
  document.getElementById('project-search')?.focus()
}

async function handleDelete() {
  if (!projectPendingDelete.value || deleting.value) return
  const project = projectPendingDelete.value
  deleting.value = true
  try {
    await projectStore.deleteProject(project.id)
    showDeleteDialog.value = false
    projectPendingDelete.value = null
    toast.success(`项目「${project.name}」已删除`)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '删除项目失败')
  } finally {
    deleting.value = false
  }
}

function openProjectConversation(project: Project) {
  if (repoCount(project) === 0) {
    router.push(`/projects/${project.id}`)
    return
  }
  router.push({ path: '/tasks', query: { project_id: project.id } })
}

function repoCount(project: Project) {
  return project.repo_count ?? (project.repos?.length ?? 0)
}

function projectTimestamp(project: Project) {
  return Date.parse(project.updated_at || project.created_at || '') || 0
}

function shortDate(value?: string) {
  if (!value) return '未记录'
  return value.slice(0, 10)
}

function projectStatus(project: Project): { label: string; tone: StatusTone } {
  const repos = project.repos || []
  if (repos.some(repo => repo.status === 'error')) return { label: '需关注', tone: 'danger' }
  if (repos.some(repo => repo.status === 'building')) return { label: '构建中', tone: 'warning' }
  if (repos.some(repo => repo.status === 'running')) return { label: '运行中', tone: 'success' }
  if (repoCount(project) === 0) return { label: '待添加仓库', tone: 'muted' }
  return { label: '已停止', tone: 'muted' }
}
</script>

<template>
  <div class="space-y-5 pb-8">
    <section class="overflow-hidden rounded-2xl border bg-card shadow-sm">
      <div class="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between md:p-6">
        <div class="flex min-w-0 items-start gap-4">
          <div class="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Boxes class="size-6" />
          </div>
          <div class="min-w-0">
            <h1 class="text-2xl font-semibold tracking-tight">项目管理</h1>
            <p class="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              集中管理代码仓库、Git 历史、模型配置和多轮开发会话。
            </p>
          </div>
        </div>
        <Button class="min-h-11 shrink-0" @click="showCreateDialog = true">
          <Plus class="size-4" />
          新建项目
        </Button>
      </div>

      <div class="grid grid-cols-2 border-t bg-muted/15 md:grid-cols-4">
        <div class="flex min-w-0 items-center gap-3 border-b p-4 md:border-b-0 md:border-r">
          <FolderKanban class="size-5 shrink-0 text-primary" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ initialLoading ? '—' : projectStore.projects.length }}</div>
            <div class="truncate text-xs text-muted-foreground">项目总数</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 border-b border-l p-4 md:border-b-0 md:border-l-0 md:border-r">
          <FolderGit2 class="size-5 shrink-0 text-muted-foreground" />
          <div class="min-w-0">
            <div class="flex items-baseline gap-1.5">
              <span class="text-xl font-semibold tabular-nums">{{ initialLoading ? '—' : totalRepoCount }}</span>
              <span v-if="!initialLoading && normalRepoCount" class="text-xs text-muted-foreground">{{ normalRepoCount }} 正常</span>
            </div>
            <div class="truncate text-xs text-muted-foreground">代码仓库</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 p-4 md:border-r">
          <Loader2 class="size-5 shrink-0 text-warning" :class="buildingRepoCount ? 'animate-spin' : ''" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ initialLoading ? '—' : buildingRepoCount }}</div>
            <div class="truncate text-xs text-muted-foreground">构建中</div>
          </div>
        </div>
        <div class="flex min-w-0 items-center gap-3 border-l p-4 md:border-l-0">
          <TriangleAlert class="size-5 shrink-0" :class="errorRepoCount ? 'text-destructive' : 'text-muted-foreground'" />
          <div class="min-w-0">
            <div class="text-xl font-semibold tabular-nums">{{ initialLoading ? '—' : errorRepoCount }}</div>
            <div class="truncate text-xs text-muted-foreground">异常仓库</div>
          </div>
        </div>
      </div>
    </section>

    <section aria-labelledby="project-list-heading" class="space-y-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div class="flex items-center gap-2">
            <h2 id="project-list-heading" class="text-base font-semibold">所有项目</h2>
            <span class="rounded-full border bg-muted/40 px-2 py-0.5 text-xs font-medium tabular-nums text-muted-foreground">
              {{ filteredProjects.length }}
            </span>
          </div>
          <p class="mt-1 text-sm text-muted-foreground">选择项目查看仓库和 Git 状态，或直接开启开发会话。</p>
        </div>

        <div class="grid w-full gap-2 sm:grid-cols-[minmax(0,1fr)_180px] lg:w-auto lg:grid-cols-[320px_180px]">
          <div class="relative min-w-0">
            <Label for="project-search" class="sr-only">搜索项目</Label>
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="project-search"
              v-model="searchQuery"
              type="search"
              class="h-11 w-full pl-9 pr-11"
              placeholder="搜索名称、描述或仓库…"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="absolute right-0 top-0 flex size-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              aria-label="清除搜索"
              @click="clearSearch"
            >
              <X class="size-4" />
            </button>
          </div>
          <div class="relative min-w-0">
            <Label for="project-sort" class="sr-only">项目排序</Label>
            <ArrowUpDown class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <select
              id="project-sort"
              v-model="sortBy"
              class="h-11 w-full rounded-md border border-input bg-background py-2 pl-9 pr-8 text-sm shadow-sm outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="updated">最近更新</option>
              <option value="name">按名称排序</option>
              <option value="repos">仓库数量</option>
            </select>
          </div>
        </div>
      </div>

      <div
        v-if="loadError && projectStore.projects.length"
        role="alert"
        class="flex flex-col gap-3 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning sm:flex-row sm:items-center sm:justify-between"
      >
        <span>{{ loadError }}</span>
        <Button variant="outline" size="sm" class="shrink-0" :disabled="projectStore.loading" @click="loadProjects">
          <Loader2 v-if="projectStore.loading" class="size-4 animate-spin" />
          <RefreshCw v-else class="size-4" />
          {{ projectStore.loading ? '加载中' : '重试' }}
        </Button>
      </div>

      <div
        v-if="projectStore.loading && !projectStore.projects.length"
        class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        role="status"
        aria-live="polite"
        aria-label="正在加载项目"
      >
        <span class="sr-only">正在加载项目列表</span>
        <div v-for="index in 6" :key="index" class="overflow-hidden rounded-xl border bg-card">
          <div class="animate-pulse space-y-4 p-5">
            <div class="flex items-center gap-3">
              <div class="size-10 rounded-lg bg-muted" />
              <div class="h-4 w-2/5 rounded bg-muted" />
            </div>
            <div class="space-y-2">
              <div class="h-3 w-full rounded bg-muted" />
              <div class="h-3 w-3/4 rounded bg-muted" />
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div class="h-14 rounded-lg bg-muted/70" />
              <div class="h-14 rounded-lg bg-muted/70" />
            </div>
          </div>
          <div class="h-14 border-t bg-muted/20" />
        </div>
      </div>

      <div v-else-if="loadError && !projectStore.projects.length" class="rounded-xl border border-dashed bg-card px-5 py-16 text-center">
        <div class="mx-auto flex size-12 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
          <TriangleAlert class="size-6" />
        </div>
        <h3 class="mt-4 text-sm font-semibold">项目列表加载失败</h3>
        <p class="mx-auto mt-1 max-w-lg text-sm leading-relaxed text-muted-foreground">{{ loadError }}</p>
        <Button variant="outline" class="mt-4" :disabled="projectStore.loading" @click="loadProjects">
          <Loader2 v-if="projectStore.loading" class="size-4 animate-spin" />
          <RefreshCw v-else class="size-4" />
          {{ projectStore.loading ? '加载中' : '重新加载' }}
        </Button>
      </div>

      <div v-else-if="filteredProjects.length" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card
          v-for="project in filteredProjects"
          :key="project.id"
          class="group flex min-w-0 flex-col overflow-hidden rounded-xl shadow-none transition-colors duration-200 hover:border-primary/35"
        >
          <router-link
            :to="`/projects/${project.id}`"
            class="flex min-w-0 flex-1 flex-col focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            :aria-label="`查看项目：${project.name}`"
          >
            <CardHeader class="pb-3">
              <div class="flex min-w-0 items-start gap-3">
                <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <FolderKanban class="size-5" />
                </div>
                <div class="min-w-0 flex-1">
                  <h3 class="truncate text-base font-semibold">{{ project.name }}</h3>
                  <div class="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span class="status-dot" :data-tone="projectStatus(project).tone" :data-pulse="projectStatus(project).tone === 'warning'" />
                    <span>{{ projectStatus(project).label }}</span>
                  </div>
                </div>
              </div>
            </CardHeader>

            <CardContent class="flex-1 space-y-4">
              <p class="min-h-10 line-clamp-2 text-sm leading-relaxed text-muted-foreground">
                {{ project.description || '暂无项目描述，可进入项目后管理仓库、Git 历史和模型配置。' }}
              </p>
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div class="rounded-lg border bg-muted/20 px-3 py-2.5">
                  <div class="flex items-center gap-1.5 text-muted-foreground">
                    <FolderGit2 class="size-3.5" />
                    代码仓库
                  </div>
                  <div class="mt-1 font-mono-data text-sm font-semibold text-foreground">{{ repoCount(project) }}</div>
                </div>
                <div class="rounded-lg border bg-muted/20 px-3 py-2.5">
                  <div class="text-muted-foreground">最近更新</div>
                  <div class="mt-1 truncate font-mono-data text-sm font-semibold text-foreground">
                    {{ shortDate(project.updated_at || project.created_at) }}
                  </div>
                </div>
              </div>
              <div class="flex items-center justify-between text-sm font-medium text-primary">
                <span>查看项目</span>
                <ArrowRight class="size-4 transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transform-none" />
              </div>
            </CardContent>
          </router-link>

          <CardFooter class="justify-between gap-2 border-t bg-muted/10 px-3 py-2.5">
            <Button variant="ghost" size="sm" class="min-h-11 min-w-0 sm:min-h-10" @click="openProjectConversation(project)">
              <FolderPlus v-if="repoCount(project) === 0" class="size-4" />
              <MessageSquarePlus v-else class="size-4" />
              {{ repoCount(project) === 0 ? '添加仓库' : '开发会话' }}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="size-11 shrink-0 text-muted-foreground hover:text-destructive sm:size-10"
              :aria-label="`删除项目：${project.name}`"
              :title="`删除项目：${project.name}`"
              @click="requestDelete(project)"
            >
              <Trash2 class="size-4" />
            </Button>
          </CardFooter>
        </Card>
      </div>

      <div v-else-if="searchQuery.trim()" class="rounded-xl border border-dashed bg-card px-5 py-16 text-center">
        <div class="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <Search class="size-6" />
        </div>
        <h3 class="mt-4 text-sm font-semibold">没有匹配的项目</h3>
        <p class="mx-auto mt-1 max-w-lg break-words text-sm leading-relaxed text-muted-foreground">
          未找到与“{{ searchQuery.trim() }}”匹配的名称、描述或仓库。
        </p>
        <Button variant="outline" class="mt-4" @click="clearSearch">
          <X class="size-4" />
          清除搜索
        </Button>
      </div>

      <div v-else class="rounded-xl border border-dashed bg-card px-5 py-20 text-center">
        <div class="mx-auto flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <FolderKanban class="size-6" />
        </div>
        <h3 class="mt-4 text-sm font-semibold">还没有项目</h3>
        <p class="mx-auto mt-1 max-w-lg text-sm leading-relaxed text-muted-foreground">
          创建第一个项目后，系统会自动准备默认仓库，随后即可发起开发会话。
        </p>
        <Button class="mt-4" @click="showCreateDialog = true">
          <Plus class="size-4" />
          新建第一个项目
        </Button>
      </div>
    </section>

    <Dialog :open="showCreateDialog" @update:open="handleCreateDialogOpenChange">
      <DialogContent class="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
          <DialogDescription>创建项目后会自动准备默认代码仓库，也可以稍后再导入其他 Git 仓库。</DialogDescription>
        </DialogHeader>
        <form id="create-project-form" class="space-y-4" @submit.prevent="handleCreate">
          <div class="space-y-2">
            <Label for="project-name">项目名称 <span class="text-destructive">*</span></Label>
            <Input
              id="project-name"
              v-model="createForm.name"
              required
              aria-required="true"
              maxlength="120"
              placeholder="例如 NextProject"
            />
          </div>
          <div class="space-y-2">
            <Label for="project-description">项目描述</Label>
            <textarea
              id="project-description"
              v-model="createForm.description"
              rows="4"
              maxlength="500"
              class="min-h-24 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring"
              placeholder="简要说明项目目标和主要用途（可选）"
            />
            <p class="text-xs text-muted-foreground">清晰的描述有助于在项目较多时快速查找。</p>
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" :disabled="creating" @click="showCreateDialog = false">取消</Button>
          <Button type="submit" form="create-project-form" :disabled="creating || !createForm.name.trim()">
            <Loader2 v-if="creating" class="size-4 animate-spin" />
            {{ creating ? '创建中' : '创建项目' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog :open="showDeleteDialog" @update:open="handleDeleteDialogOpenChange">
      <DialogContent class="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>删除项目</DialogTitle>
          <DialogDescription>
            此操作不可恢复。项目和关联仓库会从系统中移除，服务器上的项目目录将被清理；历史任务记录不会因此自动删除。
          </DialogDescription>
        </DialogHeader>
        <div v-if="projectPendingDelete" class="rounded-lg border border-destructive/25 bg-destructive/5 p-4">
          <div class="font-medium">{{ projectPendingDelete.name }}</div>
          <div class="mt-1 text-sm text-muted-foreground">
            包含 {{ repoCount(projectPendingDelete) }} 个代码仓库
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" :disabled="deleting" @click="showDeleteDialog = false">取消</Button>
          <Button
            variant="destructive"
            :disabled="deleting || !projectPendingDelete"
            @click="handleDelete"
          >
            <Loader2 v-if="deleting" class="size-4 animate-spin" />
            {{ deleting ? '删除中' : '确认删除' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
