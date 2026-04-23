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
import { Plus, ArrowLeft, GitBranch, Code } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

const projectId = route.params.id as string
const project = computed(() => projectStore.currentProject)

const showAddRepoDialog = ref(false)
const addingRepo = ref(false)
const addRepoForm = ref({ name: '', git_url: '', git_branch: '', git_username: '', git_password: '' })

onMounted(() => {
  projectStore.fetchProject(projectId)
})

// R-16/R-19: 轮询检测 building 状态的仓库是否完成
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
</script>

<template>
  <div class="space-y-6" v-if="project">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-4">
        <Button variant="ghost" @click="router.push('/projects')">
          <ArrowLeft class="w-4 h-4 mr-2" />
          返回列表
        </Button>
        <div>
          <h1 class="text-2xl font-bold">{{ project.name }}</h1>
          <p class="text-muted-foreground" v-if="project.description">{{ project.description }}</p>
        </div>
      </div>
      <div class="flex gap-2">
        <Button @click="showAddRepoDialog = true">
          <Plus class="w-4 h-4 mr-2" />
          添加仓库
        </Button>
        <Button variant="outline" @click="router.push(`/projects/${projectId}/edit`)" v-if="project.repos?.length">
          <Code class="w-4 h-4 mr-2" />
          打开编辑器
        </Button>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card v-for="repo in project.repos" :key="repo.site_id" class="flex flex-col">
        <CardHeader>
          <CardTitle class="text-lg flex items-center gap-2">
            <GitBranch class="w-5 h-5" />
            {{ repo.name }}
          </CardTitle>
        </CardHeader>
        <CardContent class="text-sm text-muted-foreground space-y-1">
          <span :class="repo.status === 'building' ? 'text-yellow-500' : repo.status === 'running' ? 'text-green-500' : repo.status === 'error' ? 'text-red-500' : 'text-gray-500'">
            {{ repo.status }}
          </span>
          <p>创建于: {{ formatDate(repo.created_at) }}</p>
        </CardContent>
      </Card>
    </div>

    <div v-if="!project.repos?.length" class="text-center text-muted-foreground py-12">
      <p>暂无仓库，点击"添加仓库"开始</p>
    </div>

    <Dialog v-model:open="showAddRepoDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加仓库</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div>
            <Label>仓库名称</Label>
            <Input v-model="addRepoForm.name" placeholder="输入仓库名称" />
          </div>
          <div>
            <Label>Git URL</Label>
            <Input v-model="addRepoForm.git_url" placeholder="https://github.com/user/repo.git (可选)" />
          </div>
          <div>
            <Label>Git 分支</Label>
            <Input v-model="addRepoForm.git_branch" placeholder="默认分支 (可选)" />
          </div>
          <div>
            <Label>Git 用户名</Label>
            <Input v-model="addRepoForm.git_username" placeholder="私有仓库可填 (可选)" />
          </div>
          <div>
            <Label>Git 密码/Token</Label>
            <Input v-model="addRepoForm.git_password" type="password" placeholder="PAT 或访问令牌 (可选)" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAddRepoDialog = false">取消</Button>
          <Button @click="handleAddRepo" :disabled="addingRepo || !addRepoForm.name.trim()">
            {{ addingRepo ? '添加中...' : '添加' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
