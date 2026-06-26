<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { formatDate } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, ArrowLeft, GitBranch, Code, Trash2, GitFork, FolderGit2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import BuildLogModal from '@/components/BuildLogModal.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

const projectId = route.params.id as string
const project = computed(() => projectStore.currentProject)

const showAddRepoDialog = ref(false)
const addingRepo = ref(false)
const addRepoForm = ref({ name: '', git_url: '', git_branch: '', git_username: '', git_password: '' })

const buildLogOpen = ref(false)
const buildLogSiteId = ref('')
const buildLogSiteName = ref('')

function openBuildLog(siteId: string, name: string) {
  buildLogSiteId.value = siteId
  buildLogSiteName.value = name
  buildLogOpen.value = true
}

onMounted(() => {
  projectStore.fetchProject(projectId)
})

let pollTimer: ReturnType<typeof setInterval> | null = null
const hasBuildingRepos = computed(() => project.value?.repos?.some(r => r.status === 'building') ?? false)

watch(hasBuildingRepos, (building) => {
  if (building && !pollTimer) {
    pollTimer = setInterval(() => {
      projectStore.fetchProject(projectId).then(() => {
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
  addingRepo.value = true
  try {
    await projectStore.addRepo(projectId, {
      name: addRepoForm.value.name.trim(),
      git_url: addRepoForm.value.git_url || undefined,
      git_branch: addRepoForm.value.git_branch || undefined,
      git_username: addRepoForm.value.git_username || undefined,
      git_password: addRepoForm.value.git_password || undefined,
    })
    showAddRepoDialog.value = false
    addRepoForm.value = { name: '', git_url: '', git_branch: '', git_username: '', git_password: '' }
    toast.success('仓库添加成功')
  } catch {
    toast.error('添加仓库失败')
  } finally {
    addingRepo.value = false
  }
}

const handleDeleteRepo = async (repoId: string, repoName: string) => {
  if (!confirm(`确认删除仓库「${repoName}」？此操作不可恢复。`)) return
  try {
    await projectStore.deleteRepo(projectId, repoId)
    toast.success('仓库已删除')
  } catch {
    toast.error('删除仓库失败')
  }
}

function repoStatusTone(status: string): 'success' | 'muted' | 'warning' | 'danger' {
  return ({ running: 'success', ready: 'success', stopped: 'muted', building: 'warning', error: 'danger' } as const)[status as 'running'] ?? 'muted'
}
</script>

<template>
  <div class="space-y-6" v-if="project">
    <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div class="flex items-start gap-3">
        <Button variant="ghost" size="sm" class="-ml-2 text-muted-foreground" @click="router.push('/projects')">
          <ArrowLeft class="size-4" />
          项目
        </Button>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">{{ project.name }}</h1>
          <p class="mt-0.5 text-sm text-muted-foreground" v-if="project.description">{{ project.description }}</p>
        </div>
      </div>
      <div class="flex gap-2">
        <Button @click="showAddRepoDialog = true">
          <Plus class="size-4" />
          添加仓库
        </Button>
        <Button variant="outline" @click="router.push(`/projects/${projectId}/edit`)" v-if="project.repos?.length">
          <Code class="size-4" />
          打开编辑器
        </Button>
      </div>
    </div>

    <div v-if="project.repos?.length" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card v-for="repo in project.repos" :key="repo.site_id" class="flex flex-col shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="flex items-center gap-2 text-base font-semibold">
            <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <GitBranch class="size-4" />
            </div>
            <span class="truncate">{{ repo.name }}</span>
          </CardTitle>
        </CardHeader>
        <CardContent class="flex-1 space-y-2 text-sm">
          <button
            v-if="repo.status === 'building'"
            type="button"
            class="flex items-center gap-1.5 text-warning hover:underline"
            @click.stop="openBuildLog(repo.site_id, repo.name)"
          >
            <span class="status-dot" data-tone="warning" data-pulse="true" />
            构建中 · 看日志
          </button>
          <span v-else class="flex items-center gap-1.5 text-muted-foreground">
            <span class="status-dot" :data-tone="repoStatusTone(repo.status)" />
            <span class="font-mono-data text-xs">{{ repo.status }}</span>
          </span>
          <div class="font-mono-data text-xs text-muted-foreground">
            {{ formatDate(repo.created_at) }}
          </div>
        </CardContent>
        <div class="border-t p-3 pt-2">
          <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" @click.stop="handleDeleteRepo(repo.site_id, repo.name)">
            <Trash2 class="size-3.5" />
            删除
          </Button>
        </div>
      </Card>
    </div>

    <div v-else class="rounded-xl border border-dashed py-20 text-center">
      <FolderGit2 class="mx-auto size-8 text-muted-foreground/40" />
      <p class="mt-3 text-sm text-muted-foreground">还没有仓库，点击「添加仓库」开始</p>
    </div>

    <Dialog v-model:open="showAddRepoDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加仓库</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div class="space-y-2">
            <Label>仓库名称 <span class="text-destructive">*</span></Label>
            <Input v-model="addRepoForm.name" placeholder="输入仓库名称" />
          </div>
          <div class="space-y-2">
            <Label>Git URL</Label>
            <Input v-model="addRepoForm.git_url" placeholder="https://github.com/user/repo.git（可选）" />
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label>Git 分支</Label>
              <Input v-model="addRepoForm.git_branch" placeholder="默认分支（可选）" />
            </div>
            <div class="space-y-2">
              <Label>Git 用户名</Label>
              <Input v-model="addRepoForm.git_username" placeholder="私有仓库可填" />
            </div>
          </div>
          <div class="space-y-2">
            <Label>Git 密码 / Token</Label>
            <Input v-model="addRepoForm.git_password" type="password" placeholder="PAT 或访问令牌（可选）" />
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

    <BuildLogModal
      v-model:open="buildLogOpen"
      :site-id="buildLogSiteId"
      :site-name="buildLogSiteName"
    />
  </div>
</template>
