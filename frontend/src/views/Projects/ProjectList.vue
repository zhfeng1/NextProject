<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { formatDate } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Plus, FolderKanban, Trash2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const router = useRouter()
const projectStore = useProjectStore()

const filter = ref({ search: '' })
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })

const filteredProjects = computed(() => {
  if (!filter.value.search) return projectStore.projects
  const q = filter.value.search.toLowerCase()
  return projectStore.projects.filter(p => p.name.toLowerCase().includes(q))
})

onMounted(() => {
  projectStore.fetchProjects()
})

const handleCreate = async () => {
  if (!createForm.value.name.trim()) return
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
  } catch {
    toast.error('创建项目失败')
  } finally {
    creating.value = false
  }
}

const handleDelete = async (projectId: string) => {
  if (!window.confirm('确定删除这个项目吗？')) return
  try {
    await projectStore.deleteProject(projectId)
    toast.success('项目已删除')
  } catch {
    toast.error('删除项目失败')
  }
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">项目管理</h1>
      <div class="flex items-center gap-4">
        <Input v-model="filter.search" placeholder="搜索项目..." class="w-64" />
        <Button @click="showCreateDialog = true">
          <Plus class="w-4 h-4 mr-2" />
          新建项目
        </Button>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="project in filteredProjects"
        :key="project.id"
        class="flex flex-col cursor-pointer hover:shadow-md transition-shadow"
        @click="router.push(`/projects/${project.id}`)"
      >
        <CardHeader>
          <CardTitle class="text-lg font-bold flex items-center gap-2">
            <FolderKanban class="w-5 h-5 text-muted-foreground" />
            {{ project.name }}
          </CardTitle>
        </CardHeader>
        <CardContent class="flex-1 text-sm text-muted-foreground space-y-1">
          <p v-if="project.description">{{ project.description }}</p>
          <p>仓库数: {{ project.repo_count }}</p>
          <p>创建于: {{ formatDate(project.created_at) }}</p>
        </CardContent>
        <CardFooter class="justify-end">
          <Button variant="ghost" size="sm" @click.stop="handleDelete(project.id)">
            <Trash2 class="w-4 h-4" />
          </Button>
        </CardFooter>
      </Card>
    </div>

    <Dialog v-model:open="showCreateDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div>
            <Label>项目名称</Label>
            <Input v-model="createForm.name" placeholder="输入项目名称" />
          </div>
          <div>
            <Label>项目描述</Label>
            <Input v-model="createForm.description" placeholder="可选描述" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">取消</Button>
          <Button @click="handleCreate" :disabled="creating || !createForm.name.trim()">
            {{ creating ? '创建中...' : '创建' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
