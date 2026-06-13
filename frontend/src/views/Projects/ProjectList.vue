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
import { Badge } from '@/components/ui/badge'
import { projectsAPI } from '@/api/projects'
import { mcpAPI } from '@/api/mcp'
import { skillsAPI } from '@/api/skills'
import type { MCPService, Project, Skill } from '@/types/models'
import { Plus, FolderKanban, Trash2, Send } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const router = useRouter()
const projectStore = useProjectStore()

const filter = ref({ search: '' })
const showCreateDialog = ref(false)
const showTaskDialog = ref(false)
const creating = ref(false)
const submittingTask = ref(false)
const createForm = ref({ name: '', description: '' })
const taskProject = ref<Project | null>(null)
const mcpServices = ref<MCPService[]>([])
const skills = ref<Skill[]>([])
const taskForm = ref({
  title: '',
  prompt: '',
  provider: 'codex',
  priority: 'medium',
  repo_ids: [] as string[],
  workflow_stages: ['research', 'plan', 'execute', 'review'] as string[],
  enabled_mcp_services: [] as string[],
  enabled_skill_ids: [] as string[],
})

const WORKFLOW_STAGES = [
  { key: 'research', label: '研究' },
  { key: 'ideate', label: '构思' },
  { key: 'plan', label: '计划' },
  { key: 'execute', label: '执行' },
  { key: 'optimize', label: '优化' },
  { key: 'review', label: '评审' },
]

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

const openTaskDialog = async (project: Project) => {
  taskProject.value = project
  taskForm.value = {
    title: '',
    prompt: '',
    provider: 'codex',
    priority: 'medium',
    repo_ids: (project.repos || []).map(repo => repo.site_id),
    workflow_stages: ['research', 'plan', 'execute', 'review'],
    enabled_mcp_services: [],
    enabled_skill_ids: [],
  }
  showTaskDialog.value = true
  try {
    const [mcpRes, skillRes] = await Promise.all([
      mcpAPI.list(),
      skillsAPI.list(),
    ])
    const repoIds = new Set((project.repos || []).map(repo => repo.site_id))
    mcpServices.value = (mcpRes.services || []).filter(service =>
      service.enabled
      && (
        service.scope_type === 'global'
        || (service.scope_type === 'project' && service.project_id === project.id)
        || (service.scope_type === 'repo' && repoIds.has(service.site_id))
      )
    )
    skills.value = (skillRes.skills || []).filter(skill =>
      skill.enabled
      && (
        skill.scope_type === 'global'
        || (skill.scope_type === 'project' && skill.project_id === project.id)
        || (skill.scope_type === 'repo' && repoIds.has(skill.site_id))
      )
    )
  } catch {
    mcpServices.value = []
    skills.value = []
  }
}

const toggleInList = (list: string[], value: string) => {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

const submitProjectTask = async () => {
  if (!taskProject.value || !taskForm.value.prompt.trim() || !taskForm.value.repo_ids.length) return
  submittingTask.value = true
  try {
    const res = await projectsAPI.createTask(taskProject.value.id, {
      repo_ids: taskForm.value.repo_ids,
      provider: taskForm.value.provider,
      title: taskForm.value.title.trim() || taskForm.value.prompt.trim().slice(0, 80),
      prompt: taskForm.value.prompt.trim(),
      priority: taskForm.value.priority,
      workflow_stages: taskForm.value.workflow_stages,
      mcp_service_ids: taskForm.value.enabled_mcp_services,
      skill_ids: taskForm.value.enabled_skill_ids,
    })
    toast.success(`任务已提交: ${res.task_id}`)
    showTaskDialog.value = false
    router.push('/tasks')
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '提交任务失败')
  } finally {
    submittingTask.value = false
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
          <Button variant="outline" size="sm" class="mr-2" @click.stop="openTaskDialog(project)">
            <Send class="w-4 h-4 mr-2" />
            提交任务
          </Button>
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

    <Dialog v-model:open="showTaskDialog">
      <DialogContent class="sm:max-w-[820px]">
        <DialogHeader>
          <DialogTitle>提交多仓任务</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-2">
          <div class="flex items-center gap-2 text-sm text-muted-foreground">
            <FolderKanban class="h-4 w-4" />
            <span>{{ taskProject?.name }}</span>
            <Badge variant="secondary">{{ taskForm.repo_ids.length }} 个仓库</Badge>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <div class="space-y-1.5">
              <Label>标题</Label>
              <Input v-model="taskForm.title" placeholder="例如：前后端登录态统一调整" />
            </div>
            <div class="space-y-1.5">
              <Label>Provider</Label>
              <select v-model="taskForm.provider" class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm">
                <option value="codex">Codex</option>
                <option value="claude_code">Claude Code</option>
                <option value="gemini_cli">Gemini CLI</option>
              </select>
            </div>
          </div>
          <div class="space-y-1.5">
            <Label>任务需求</Label>
            <textarea
              v-model="taskForm.prompt"
              class="min-h-[140px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              placeholder="描述这次需要跨仓完成的修改"
            />
          </div>
          <div class="space-y-2">
            <Label>参与仓库</Label>
            <div class="grid gap-2 md:grid-cols-2">
              <label v-for="repo in taskProject?.repos || []" :key="repo.site_id" class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  class="h-4 w-4 accent-primary"
                  :checked="taskForm.repo_ids.includes(repo.site_id)"
                  @change="toggleInList(taskForm.repo_ids, repo.site_id)"
                />
                <span>{{ repo.name }}</span>
              </label>
            </div>
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label>六阶段要求</Label>
              <div class="flex flex-wrap gap-2">
                <label v-for="stage in WORKFLOW_STAGES" :key="stage.key" class="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
                  <input
                    type="checkbox"
                    class="h-4 w-4 accent-primary"
                    :checked="taskForm.workflow_stages.includes(stage.key)"
                    @change="toggleInList(taskForm.workflow_stages, stage.key)"
                  />
                  {{ stage.label }}
                </label>
              </div>
            </div>
            <div class="space-y-2">
              <Label>优先级</Label>
              <select v-model="taskForm.priority" class="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm">
                <option value="urgent">紧急</option>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label>MCP</Label>
              <div class="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                <label v-for="service in mcpServices" :key="`${service.service_id}-${service.scope_type}-${service.site_id}`" class="flex items-center gap-2 text-sm">
                  <input type="checkbox" class="h-4 w-4 accent-primary" :checked="taskForm.enabled_mcp_services.includes(service.service_id)" @change="toggleInList(taskForm.enabled_mcp_services, service.service_id)" />
                  <span>{{ service.name }}</span>
                  <Badge variant="outline">{{ service.scope_type }}</Badge>
                </label>
                <div v-if="!mcpServices.length" class="text-xs text-muted-foreground">暂无已启用 MCP</div>
              </div>
            </div>
            <div class="space-y-2">
              <Label>Skill</Label>
              <div class="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                <label v-for="skill in skills" :key="skill.id" class="flex items-center gap-2 text-sm">
                  <input type="checkbox" class="h-4 w-4 accent-primary" :checked="taskForm.enabled_skill_ids.includes(skill.id)" @change="toggleInList(taskForm.enabled_skill_ids, skill.id)" />
                  <span>{{ skill.name }}</span>
                  <Badge variant="outline">{{ skill.scope_type }}</Badge>
                </label>
                <div v-if="!skills.length" class="text-xs text-muted-foreground">暂无已启用 Skill</div>
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showTaskDialog = false">取消</Button>
          <Button :disabled="submittingTask || !taskForm.prompt.trim() || !taskForm.repo_ids.length" @click="submitProjectTask">
            {{ submittingTask ? '提交中...' : '提交任务' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
