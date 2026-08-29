<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  AlertTriangle,
  Box,
  CheckCircle2,
  CircleOff,
  Code2,
  Eye,
  FileCode2,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  Trash2,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { techPlatformAPI, type RenderedYamlResource, type TechPlatformDeploymentModule, type TechPlatformModuleInput } from '@/api/techPlatform'
import type { Site } from '@/types/models'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import TaskLogs from '@/components/TaskLogs.vue'

const props = defineProps<{
  projectId: string
  repos: Site[]
}>()

type TemplateKey = 'config_map_template' | 'deployment_template' | 'service_template'

const modules = ref<TechPlatformDeploymentModule[]>([])
const loading = ref(false)
const scanning = ref(false)
const operationId = ref('')
const formOpen = ref(false)
const editingId = ref('')
const saving = ref(false)
const activeTemplate = ref<TemplateKey>('config_map_template')
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewImage = ref('')
const previewResources = ref<RenderedYamlResource[]>([])
const activePreviewKind = ref<RenderedYamlResource['kind']>('ConfigMap')
const logOpen = ref(false)
const logTaskId = ref('')
const logModuleName = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const emptyDraft = (): TechPlatformModuleInput => ({
  site_id: props.repos[0]?.site_id || '',
  dockerfile_path: 'Dockerfile',
  build_context: '.',
  app_name: '',
  namespace: 'ocean-km',
  harbor_project: 'ocean-km',
  repository_name: '',
  app_type: '2',
  container_port: 8080,
  service_port: 80,
  config_map_template: '',
  deployment_template: '',
  service_template: '',
})

const draft = ref<TechPlatformModuleInput>(emptyDraft())
const isEditing = computed(() => Boolean(editingId.value))
const runningCount = computed(() => modules.value.filter(item => ['queued', 'running'].includes(item.status)).length)
const successCount = computed(() => modules.value.filter(item => item.status === 'success').length)
const invalidCount = computed(() => modules.value.filter(item => !item.is_available || item.status === 'failed').length)
const currentPreview = computed(() => previewResources.value.find(item => item.kind === activePreviewKind.value))

function errorMessage(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

function statusLabel(module: TechPlatformDeploymentModule) {
  if (!module.is_available) return '文件失效'
  return ({
    idle: '未部署',
    queued: '排队中',
    running: '部署中',
    success: '部署成功',
    failed: '部署失败',
  } as Record<string, string>)[module.status] || module.status
}

function statusTone(module: TechPlatformDeploymentModule) {
  if (!module.is_available || module.status === 'failed') return 'danger'
  if (module.status === 'success') return 'success'
  if (['queued', 'running'].includes(module.status)) return 'warning'
  return 'muted'
}

function shortSha(value: string) {
  return value ? value.slice(0, 12) : '-'
}

function displayTime(value: string | null) {
  if (!value) return '尚未部署'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function loadModules({ autoScan = false } = {}) {
  loading.value = true
  try {
    const response = await techPlatformAPI.list(props.projectId)
    modules.value = response.modules || []
    if (autoScan && modules.value.length === 0 && props.repos.length) await scanModules(false)
  } catch (error: any) {
    toast.error(errorMessage(error, '加载技术中台部署模块失败'))
  } finally {
    loading.value = false
  }
}

async function scanModules(showSuccess = true) {
  scanning.value = true
  try {
    const response = await techPlatformAPI.scan(props.projectId)
    modules.value = response.modules || []
    if (showSuccess) toast.success(`扫描完成，发现 ${modules.value.length} 个部署模块`)
  } catch (error: any) {
    toast.error(errorMessage(error, '扫描 Dockerfile 失败'))
  } finally {
    scanning.value = false
  }
}

function openCreate() {
  editingId.value = ''
  draft.value = emptyDraft()
  activeTemplate.value = 'config_map_template'
  formOpen.value = true
}

function openEdit(module: TechPlatformDeploymentModule) {
  editingId.value = module.id
  draft.value = {
    site_id: module.site_id,
    dockerfile_path: module.dockerfile_path,
    build_context: module.build_context,
    app_name: module.app_name,
    namespace: module.namespace,
    harbor_project: module.harbor_project,
    repository_name: module.repository_name,
    app_type: module.app_type,
    container_port: module.container_port,
    service_port: module.service_port,
    config_map_template: module.config_map_template,
    deployment_template: module.deployment_template,
    service_template: module.service_template,
  }
  activeTemplate.value = 'config_map_template'
  formOpen.value = true
}

async function saveModule() {
  if (!draft.value.site_id || !draft.value.dockerfile_path.trim()) {
    toast.warning('请选择仓库并填写 Dockerfile 路径')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      const { site_id: _siteId, ...payload } = draft.value
      const response = await techPlatformAPI.update(props.projectId, editingId.value, payload)
      const index = modules.value.findIndex(item => item.id === editingId.value)
      if (index !== -1) modules.value[index] = response.module
      toast.success('部署模块已保存')
    } else {
      const response = await techPlatformAPI.create(props.projectId, draft.value)
      modules.value.push(response.module)
      toast.success('部署模块已创建')
    }
    formOpen.value = false
  } catch (error: any) {
    toast.error(errorMessage(error, '保存部署模块失败'))
  } finally {
    saving.value = false
  }
}

async function removeModule(module: TechPlatformDeploymentModule) {
  if (!confirm(`确认删除部署模块「${module.app_name}」？中台应用不会被自动删除。`)) return
  operationId.value = module.id
  try {
    await techPlatformAPI.remove(props.projectId, module.id)
    modules.value = modules.value.filter(item => item.id !== module.id)
    toast.success('部署模块已删除')
  } catch (error: any) {
    toast.error(errorMessage(error, '删除部署模块失败'))
  } finally {
    operationId.value = ''
  }
}

async function openPreview(module: TechPlatformDeploymentModule) {
  previewOpen.value = true
  previewLoading.value = true
  previewResources.value = []
  previewImage.value = ''
  activePreviewKind.value = 'ConfigMap'
  try {
    const response = await techPlatformAPI.preview(props.projectId, module.id)
    previewImage.value = response.image
    previewResources.value = response.resources
  } catch (error: any) {
    previewOpen.value = false
    toast.error(errorMessage(error, '渲染 YAML 预览失败'))
  } finally {
    previewLoading.value = false
  }
}

async function validateModule(module: TechPlatformDeploymentModule) {
  operationId.value = `${module.id}:validate`
  try {
    await techPlatformAPI.validate(props.projectId, module.id)
    toast.success('ConfigMap、Deployment、Service 均校验通过')
  } catch (error: any) {
    toast.error(errorMessage(error, 'YAML 校验失败'))
  } finally {
    operationId.value = ''
  }
}

async function deployModule(module: TechPlatformDeploymentModule) {
  if (!confirm(`确认构建并部署「${module.app_name}」到技术中台？`)) return
  operationId.value = `${module.id}:deploy`
  try {
    const response = await techPlatformAPI.deploy(props.projectId, module.id)
    module.status = 'queued'
    module.last_task_id = response.task_id
    toast.success('部署任务已提交')
    openLogs(module, response.task_id)
  } catch (error: any) {
    toast.error(errorMessage(error, '提交部署任务失败'))
  } finally {
    operationId.value = ''
  }
}

function openLogs(module: TechPlatformDeploymentModule, taskId = module.last_task_id) {
  if (!taskId) return
  logTaskId.value = taskId
  logModuleName.value = module.app_name
  logOpen.value = true
}

function handleLogStatus(status: string) {
  if (['success', 'failed', 'canceled'].includes(status)) loadModules()
}

onMounted(() => {
  loadModules({ autoScan: true })
  pollTimer = setInterval(() => {
    if (runningCount.value > 0) loadModules()
  }, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <section class="overflow-hidden rounded-xl border bg-card">
    <div class="flex flex-col gap-4 border-b p-4 sm:flex-row sm:items-center sm:justify-between md:p-5">
      <div>
        <h2 class="flex items-center gap-2 text-base font-semibold">
          <Box class="size-5 text-muted-foreground" />
          技术中台部署
        </h2>
        <p class="mt-1 text-sm text-muted-foreground">按 Dockerfile 管理模块，构建镜像后校验并部署三类 Kubernetes 资源。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button variant="outline" :disabled="scanning || loading" @click="scanModules()">
          <RefreshCw class="size-4" :class="scanning ? 'animate-spin' : ''" />
          重新扫描
        </Button>
        <Button :disabled="!repos.length" @click="openCreate">
          <Plus class="size-4" />
          手动添加
        </Button>
      </div>
    </div>

    <div class="grid grid-cols-3 border-b bg-muted/15">
      <div class="flex items-center gap-3 border-r p-4">
        <Loader2 class="size-5 text-warning" :class="runningCount ? 'animate-spin' : ''" />
        <div><div class="font-semibold tabular-nums">{{ runningCount }}</div><div class="text-xs text-muted-foreground">执行中</div></div>
      </div>
      <div class="flex items-center gap-3 border-r p-4">
        <CheckCircle2 class="size-5 text-success" />
        <div><div class="font-semibold tabular-nums">{{ successCount }}</div><div class="text-xs text-muted-foreground">已成功</div></div>
      </div>
      <div class="flex items-center gap-3 p-4">
        <AlertTriangle class="size-5" :class="invalidCount ? 'text-destructive' : 'text-muted-foreground'" />
        <div><div class="font-semibold tabular-nums">{{ invalidCount }}</div><div class="text-xs text-muted-foreground">需处理</div></div>
      </div>
    </div>

    <div v-if="loading && !modules.length" class="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 class="size-5 animate-spin" />
      加载部署模块…
    </div>

    <div v-else-if="modules.length" class="grid gap-4 p-4 md:grid-cols-2 md:p-5 xl:grid-cols-3">
      <article
        v-for="module in modules"
        :key="module.id"
        class="flex min-w-0 flex-col rounded-xl border bg-background transition-colors duration-200 hover:border-primary/35"
      >
        <div class="flex items-start gap-3 border-b p-4">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileCode2 class="size-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h3 class="min-w-0 flex-1 truncate font-semibold">{{ module.app_name }}</h3>
              <span class="flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium">
                <span class="status-dot" :data-tone="statusTone(module)" :data-pulse="module.status === 'running'" />
                {{ statusLabel(module) }}
              </span>
            </div>
            <p class="mt-1 truncate text-xs text-muted-foreground">{{ module.site_name }} · {{ module.dockerfile_path }}</p>
          </div>
        </div>

        <div class="flex-1 space-y-3 p-4 text-xs">
          <div class="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
            <span class="text-muted-foreground">镜像仓库</span>
            <span class="truncate text-right font-mono-data" :title="`${module.harbor_project}/${module.repository_name}`">
              {{ module.harbor_project }}/{{ module.repository_name }}
            </span>
            <span class="text-muted-foreground">命名空间</span>
            <span class="truncate text-right font-mono-data">{{ module.namespace }}</span>
            <span class="text-muted-foreground">端口映射</span>
            <span class="text-right font-mono-data">{{ module.service_port }} → {{ module.container_port }}</span>
            <span class="text-muted-foreground">中台 appId</span>
            <span class="truncate text-right font-mono-data">{{ module.platform_app_id || '首次部署创建' }}</span>
            <span class="text-muted-foreground">Commit</span>
            <span class="truncate text-right font-mono-data">{{ shortSha(module.last_commit_sha) }}</span>
          </div>
          <div class="rounded-lg border bg-muted/20 p-3">
            <div class="text-muted-foreground">最近部署</div>
            <div class="mt-1 font-mono-data">{{ displayTime(module.last_deployed_at) }}</div>
            <div v-if="module.last_image" class="mt-1 truncate text-muted-foreground" :title="module.last_image">{{ module.last_image }}</div>
          </div>
          <div v-if="!module.is_available" class="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-destructive">
            <CircleOff class="mt-0.5 size-4 shrink-0" />
            Dockerfile 已不存在，重新扫描或修改路径后才能部署。
          </div>
          <div v-else-if="module.last_error" class="line-clamp-3 rounded-lg border border-destructive/25 bg-destructive/5 p-3 text-destructive" :title="module.last_error">
            {{ module.last_error }}
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2 border-t p-3 sm:grid-cols-3">
          <Button variant="ghost" size="sm" @click="openEdit(module)"><Pencil class="size-3.5" />配置</Button>
          <Button variant="ghost" size="sm" @click="openPreview(module)"><Eye class="size-3.5" />预览</Button>
          <Button
            variant="ghost"
            size="sm"
            :disabled="!module.platform_app_id || operationId === `${module.id}:validate`"
            @click="validateModule(module)"
          >
            <Loader2 v-if="operationId === `${module.id}:validate`" class="size-3.5 animate-spin" />
            <ShieldCheck v-else class="size-3.5" />校验
          </Button>
          <Button v-if="module.last_task_id" variant="ghost" size="sm" @click="openLogs(module)"><ScrollText class="size-3.5" />日志</Button>
          <Button
            size="sm"
            :class="module.last_task_id ? '' : 'sm:col-span-2'"
            :disabled="!module.is_available || ['queued', 'running'].includes(module.status) || operationId === `${module.id}:deploy`"
            @click="deployModule(module)"
          >
            <Loader2 v-if="operationId === `${module.id}:deploy`" class="size-3.5 animate-spin" />
            <Play v-else class="size-3.5" />部署
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="text-muted-foreground hover:text-destructive"
            :disabled="operationId === module.id || ['queued', 'running'].includes(module.status)"
            @click="removeModule(module)"
          ><Trash2 class="size-3.5" />删除</Button>
        </div>
      </article>
    </div>

    <div v-else class="px-5 py-20 text-center">
      <div class="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground"><Code2 class="size-6" /></div>
      <h3 class="mt-4 text-sm font-semibold">没有发现 Dockerfile</h3>
      <p class="mt-1 text-sm text-muted-foreground">在仓库中添加 Dockerfile，或手动填写已有文件路径。</p>
      <div class="mt-4 flex justify-center gap-2">
        <Button variant="outline" @click="scanModules()"><RefreshCw class="size-4" />重新扫描</Button>
        <Button :disabled="!repos.length" @click="openCreate"><Plus class="size-4" />手动添加</Button>
      </div>
    </div>
  </section>

  <Dialog v-model:open="formOpen">
    <DialogContent class="max-h-[90vh] max-w-5xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{{ isEditing ? '编辑部署模块' : '新增部署模块' }}</DialogTitle>
        <DialogDescription>路径均相对于仓库根目录；模板变量采用双大括号语法并在保存时严格校验。</DialogDescription>
      </DialogHeader>

      <div class="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]">
        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="deploy-repo">代码仓库</Label>
            <select id="deploy-repo" v-model="draft.site_id" :disabled="isEditing" class="h-11 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50">
              <option value="" disabled>选择仓库</option>
              <option v-for="repo in repos" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
            </select>
          </div>
          <div class="space-y-2"><Label for="deploy-dockerfile">Dockerfile 路径</Label><Input id="deploy-dockerfile" v-model="draft.dockerfile_path" class="h-11 font-mono-data" /></div>
          <div class="space-y-2"><Label for="deploy-context">构建上下文</Label><Input id="deploy-context" v-model="draft.build_context" class="h-11 font-mono-data" /></div>
          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-2"><Label for="deploy-app">应用名</Label><Input id="deploy-app" v-model="draft.app_name" class="h-11" placeholder="扫描时自动生成" /></div>
            <div class="space-y-2"><Label for="deploy-namespace">命名空间</Label><Input id="deploy-namespace" v-model="draft.namespace" class="h-11" /></div>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-2"><Label for="deploy-harbor-project">Harbor 项目</Label><Input id="deploy-harbor-project" v-model="draft.harbor_project" class="h-11" /></div>
            <div class="space-y-2"><Label for="deploy-repository">镜像仓库</Label><Input id="deploy-repository" v-model="draft.repository_name" class="h-11" placeholder="扫描时自动生成" /></div>
          </div>
          <div class="grid grid-cols-3 gap-3">
            <div class="space-y-2"><Label for="deploy-app-type">应用类型</Label><Input id="deploy-app-type" v-model="draft.app_type" class="h-11" /></div>
            <div class="space-y-2"><Label for="deploy-container-port">容器端口</Label><Input id="deploy-container-port" v-model="draft.container_port" type="number" min="1" max="65535" class="h-11" /></div>
            <div class="space-y-2"><Label for="deploy-service-port">服务端口</Label><Input id="deploy-service-port" v-model="draft.service_port" type="number" min="1" max="65535" class="h-11" /></div>
          </div>
        </div>

        <div class="min-w-0 space-y-3">
          <div>
            <Label>YAML 模板</Label>
            <p class="mt-1 text-xs leading-relaxed text-muted-foreground">可用变量：app_name、namespace、image、container_port、service_port、harbor_project、repository_name。</p>
          </div>
          <div class="grid grid-cols-3 gap-2 rounded-lg border bg-muted/25 p-1.5" role="tablist" aria-label="选择 YAML 模板">
            <button
              v-for="item in ([['config_map_template', 'ConfigMap'], ['deployment_template', 'Deployment'], ['service_template', 'Service']] as const)"
              :key="item[0]"
              type="button"
              role="tab"
              :aria-selected="activeTemplate === item[0]"
              class="min-h-11 rounded-md px-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring"
              :class="activeTemplate === item[0] ? 'bg-background shadow-sm' : 'text-muted-foreground hover:bg-background/60'"
              @click="activeTemplate = item[0]"
            >{{ item[1] }}</button>
          </div>
          <textarea
            v-model="draft[activeTemplate]"
            :aria-label="`${activeTemplate} YAML 模板`"
            spellcheck="false"
            class="min-h-[420px] w-full resize-y rounded-lg border border-input bg-muted/20 p-4 font-mono-data text-xs leading-relaxed outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring"
            placeholder="留空时使用默认模板"
          />
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="saving" @click="formOpen = false">取消</Button>
        <Button :disabled="saving" @click="saveModule"><Loader2 v-if="saving" class="size-4 animate-spin" />保存配置</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="previewOpen">
    <DialogContent class="max-h-[90vh] max-w-4xl overflow-hidden p-0">
      <DialogHeader class="px-6 pt-6">
        <DialogTitle>渲染后的 YAML</DialogTitle>
        <DialogDescription class="truncate font-mono-data" :title="previewImage">镜像：{{ previewImage || '渲染中…' }}</DialogDescription>
      </DialogHeader>
      <div v-if="previewLoading" class="flex min-h-96 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 class="size-5 animate-spin" />渲染模板…</div>
      <div v-else class="min-h-0 px-6 pb-6">
        <div class="mb-3 grid grid-cols-3 gap-2" role="tablist" aria-label="选择 YAML 预览">
          <Button v-for="resource in previewResources" :key="resource.kind" size="sm" :variant="activePreviewKind === resource.kind ? 'default' : 'outline'" @click="activePreviewKind = resource.kind">{{ resource.kind }}</Button>
        </div>
        <pre class="max-h-[60vh] overflow-auto rounded-lg border bg-slate-950 p-4 text-xs leading-relaxed text-slate-100"><code>{{ currentPreview?.yaml }}</code></pre>
      </div>
    </DialogContent>
  </Dialog>

  <Dialog v-model:open="logOpen">
    <DialogContent class="max-w-4xl p-0">
      <DialogHeader class="px-6 pt-6 pb-2">
        <DialogTitle>部署日志 — {{ logModuleName }}</DialogTitle>
        <DialogDescription class="font-mono-data">任务 {{ logTaskId }}</DialogDescription>
      </DialogHeader>
      <div class="h-[65vh] px-6 pb-6"><TaskLogs v-if="logTaskId" :task-id="logTaskId" @status-change="handleLogStatus" /></div>
    </DialogContent>
  </Dialog>
</template>
