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
import { Plus, FolderKanban, Trash2, Send, Search, FolderGit2 } from 'lucide-vue-next'
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

function repoCount(p: Project) {
  return p.repo_count ?? (p.repos?.length ?? 0)
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">项目管理</h1>
        <p class="mt-1 text-sm text-muted-foreground">组织仓库并跨仓下发编码任务</p>
      </div>
      <div class="flex items-center gap-3">
        <div class="relative">
          <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input v-model="filter.search" placeholder="搜索项目…" class="w-56 pl-8" />
        </div>
        <Button @click="showCreateDialog = true">
          <Plus class="size-4" />
          新建项目
        </Button>
      </div>
    </div>

    <div v-if="filteredProjects.length" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="project in filteredProjects"
        :key="project.id"
        class="group flex cursor-pointer flex-col shadow-none transition-all hover:border-primary/40 hover:shadow-sm"
        @click="router.push(`/projects/${project.id}`)"
      >
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-base font-semibold">
            <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <FolderKanban class="size-4" />
            </div>
            <span class="truncate">{{ project.name }}</span>
          </CardTitle>
        </CardHeader>
        <CardContent class="flex-1 space-y-2 text-sm text-muted-foreground">
          <p v-if="project.description" class="line-clamp-2 leading-relaxed">{{ project.description }}</p>
          <p v-else class="italic">暂无描述</p>
          <div class="flex items-center gap-3 pt-1 font-mono-data text-xs">
            <span class="flex items-center gap-1"><FolderGit2 class="size-3" />{{ repoCount(project) }} 仓库</span>
            <span>{{ formatDate(project.created_at) }}</span>
          </div>
        </CardContent>
        <CardFooter class="justify-end gap-1 border-t pt-3">
          <Button variant="ghost" size="sm" class="gap-1.5" @click.stop="openTaskDialog(project)">
            <Send class="size-3.5" />
            提交任务
          </Button>
          <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-destructive" @click.stop="handleDelete(project.id)">
            <Trash2 class="size-3.5" />
          </Button>
        </CardFooter>
      </Card>
    </div>

    <div v-else class="rounded-xl border border-dashed py-20 text-center">
      <FolderKanban class="mx-auto size-8 text-muted-foreground/40" />
      <p class="mt-3 text-sm text-muted-foreground">还没有项目，点击「新建项目」开始</p>
    </div>

    <Dialog v-model:open="showCreateDialog">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div class="space-y-2">
            <Label>项目名称</Label>
            <Input v-model="createForm.name" placeholder="输入项目名称" />
          </div>
          <div class="space-y-2">
            <Label>项目描述</Label>
            <Input v-model="createForm.description" placeholder="可选描述" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">取消</Button>
          <Button @click="handleCreate" :disabled="creating || !createForm.name.trim()">
            {{ creating ? '创建中…' : '创建' }}
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
            <FolderKanban class="size-4" />
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
              <select v-model="taskForm.provider" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring">
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
              class="min-h-[140px] w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
              placeholder="描述这次需要跨仓完成的修改"
            />
          </div>
          <div class="space-y-2">
            <Label>参与仓库</Label>
            <div class="grid gap-2 md:grid-cols-2">
              <label
                v-for="repo in taskProject?.repos || []"
                :key="repo.site_id"
                class="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors"
                :class="taskForm.repo_ids.includes(repo.site_id) ? 'border-primary bg-primary/5' : 'border-border'"
              >
                <input
                  type="checkbox"
                  class="size-4 accent-[hsl(var(--primary))]"
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
                <label
                  v-for="stage in WORKFLOW_STAGES"
                  :key="stage.key"
                  class="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors"
                  :class="taskForm.workflow_stages.includes(stage.key) ? 'border-primary bg-primary/5' : 'border-border'"
                >
                  <input
                    type="checkbox"
                    class="size-4 accent-[hsl(var(--primary))]"
                    :checked="taskForm.workflow_stages.includes(stage.key)"
                    @change="toggleInList(taskForm.workflow_stages, stage.key)"
                  />
                  {{ stage.label }}
                </label>
              </div>
            </div>
            <div class="space-y-1.5">
              <Label>优先级</Label>
              <select v-model="taskForm.priority" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring">
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
                  <input type="checkbox" class="size-4 accent-[hsl(var(--primary))]" :checked="taskForm.enabled_mcp_services.includes(service.service_id)" @change="toggleInList(taskForm.enabled_mcp_services, service.service_id)" />
                  <span>{{ service.name }}</span>
                  <Badge variant="outline">{{ service.scope_type }}</Badge>
                </label>
                <div v-if="!mcpServices.length" class="py-2 text-center text-xs text-muted-foreground">暂无已启用 MCP</div>
              </div>
            </div>
            <div class="space-y-2">
              <Label>Skill</Label>
              <div class="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                <label v-for="skill in skills" :key="skill.id" class="flex items-center gap-2 text-sm">
                  <input type="checkbox" class="size-4 accent-[hsl(var(--primary))]" :checked="taskForm.enabled_skill_ids.includes(skill.id)" @change="toggleInList(taskForm.enabled_skill_ids, skill.id)" />
                  <span>{{ skill.name }}</span>
                  <Badge variant="outline">{{ skill.scope_type }}</Badge>
                </label>
                <div v-if="!skills.length" class="py-2 text-center text-xs text-muted-foreground">暂无已启用 Skill</div>
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showTaskDialog = false">取消</Button>
          <Button :disabled="submittingTask || !taskForm.prompt.trim() || !taskForm.repo_ids.length" @click="submitProjectTask">
            {{ submittingTask ? '提交中…' : '提交任务' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
