<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { mcpAPI } from '@/api/mcp'
import { skillsAPI } from '@/api/skills'
import { workflowsAPI } from '@/api/workflows'
import type { MCPService, Skill, WorkflowRun } from '@/types/models'

const props = defineProps<{
  siteId: string
  currentUrl?: string
  selectedXpath?: string
  consoleErrors?: string
}>()

const emit = defineEmits<{
  submitTask: [payload: Record<string, unknown>]
}>()

const loading = ref(false)
const creating = ref(false)
const savingStage = ref(false)
const confirming = ref(false)
const workflowRun = ref<WorkflowRun | null>(null)
const stageDraft = ref('')
const workflowName = ref('')
const mcpServices = ref<MCPService[]>([])
const boundSkills = ref<Skill[]>([])
const selectedMcpServices = ref<string[]>([])
const selectedSkillIds = ref<string[]>([])
const taskPrompt = ref('')
const provider = ref('codex')
const message = ref('')

const STAGE_ORDER = ['research', 'ideate', 'plan', 'execute', 'optimize', 'review']
const PROVIDERS = [
  { value: 'codex', label: 'Codex' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'gemini_cli', label: 'Gemini' },
]

const currentStage = computed(() => workflowRun.value?.current_stage || 'research')
const canSubmitAi = computed(() => ['execute', 'optimize'].includes(currentStage.value))

async function loadData() {
  if (!props.siteId) return
  loading.value = true
  try {
    const [runRes, mcpRes, skillsRes] = await Promise.all([
      workflowsAPI.getCurrent(props.siteId),
      mcpAPI.list(),
      skillsAPI.listBySite(props.siteId),
    ])
    workflowRun.value = runRes.run
    mcpServices.value = (mcpRes.services || []).filter(service => service.enabled)
    boundSkills.value = skillsRes.skills || []
    if (workflowRun.value) {
      selectedMcpServices.value = [...(workflowRun.value.enabled_mcp_services || [])]
      selectedSkillIds.value = [...(workflowRun.value.enabled_skill_ids || [])]
      await loadArtifacts(workflowRun.value.id, currentStage.value)
    } else {
      selectedMcpServices.value = mcpServices.value.map(service => service.service_id)
      selectedSkillIds.value = boundSkills.value.map(skill => skill.id)
      stageDraft.value = ''
    }
  } finally {
    loading.value = false
  }
}

async function loadArtifacts(runId: string, stage: string) {
  const res = await workflowsAPI.getArtifacts(runId)
  stageDraft.value = res.artifacts?.[stage]?.content || ''
}

async function createRun() {
  if (!props.siteId || creating.value) return
  creating.value = true
  message.value = ''
  try {
    const res = await workflowsAPI.create(props.siteId, {
      name: workflowName.value.trim() || undefined,
      enabled_mcp_services: selectedMcpServices.value,
      enabled_skill_ids: selectedSkillIds.value,
    })
    workflowRun.value = res.run
    await loadArtifacts(res.run.id, res.run.current_stage)
    message.value = '工作流已创建'
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '创建工作流失败'
  } finally {
    creating.value = false
  }
}

async function saveStage() {
  if (!workflowRun.value || savingStage.value) return
  savingStage.value = true
  message.value = ''
  try {
    const res = await workflowsAPI.generateStage(workflowRun.value.id, {
      stage: currentStage.value,
      content: stageDraft.value,
      notes: taskPrompt.value,
    })
    workflowRun.value = res.run
    stageDraft.value = res.content
    message.value = `${workflowRun.value.current_stage_label} 文档已保存`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '保存阶段失败'
  } finally {
    savingStage.value = false
  }
}

async function confirmStage() {
  if (!workflowRun.value || confirming.value) return
  confirming.value = true
  message.value = ''
  try {
    const res = await workflowsAPI.confirmStage(workflowRun.value.id)
    workflowRun.value = res.run
    await loadArtifacts(workflowRun.value.id, workflowRun.value.current_stage)
    message.value = `已推进到 ${workflowRun.value.current_stage_label}`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '阶段确认失败'
  } finally {
    confirming.value = false
  }
}

function toggleMcp(serviceId: string) {
  selectedMcpServices.value = selectedMcpServices.value.includes(serviceId)
    ? selectedMcpServices.value.filter(id => id !== serviceId)
    : [...selectedMcpServices.value, serviceId]
}

function toggleSkill(skillId: string) {
  selectedSkillIds.value = selectedSkillIds.value.includes(skillId)
    ? selectedSkillIds.value.filter(id => id !== skillId)
    : [...selectedSkillIds.value, skillId]
}

function submitAiTask() {
  if (!workflowRun.value || !taskPrompt.value.trim()) return
  emit('submitTask', {
    site_id: props.siteId,
    task_type: 'develop_code',
    provider: provider.value,
    prompt: taskPrompt.value.trim(),
    current_url: props.currentUrl || '',
    selected_xpath: props.selectedXpath || '',
    console_errors: props.consoleErrors || '',
    workflow_run_id: workflowRun.value.id,
    workflow_stage: workflowRun.value.current_stage,
    enabled_mcp_services: selectedMcpServices.value,
    enabled_skill_ids: selectedSkillIds.value,
  })
}

watch(() => props.siteId, loadData, { immediate: true })
onMounted(loadData)
</script>

<template>
  <Card>
    <CardHeader class="py-2 px-3 pb-1">
      <CardTitle class="text-sm">工作流模式</CardTitle>
    </CardHeader>
    <CardContent class="px-3 pb-3 space-y-3">
      <div v-if="message" class="rounded-md border bg-background px-3 py-2 text-xs">
        {{ message }}
      </div>

      <div v-if="loading" class="text-xs text-muted-foreground">
        加载工作流数据中...
      </div>

      <template v-else-if="!workflowRun">
        <div class="space-y-2">
          <Label for="workflow-name">工作流名称</Label>
          <Input id="workflow-name" v-model="workflowName" placeholder="例如：首页改版六阶段流程" />
        </div>

        <div class="space-y-2">
          <p class="text-xs font-medium text-foreground">默认启用 MCP</p>
          <div class="flex flex-wrap gap-2">
            <label v-for="service in mcpServices" :key="service.service_id" class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
              <input
                :checked="selectedMcpServices.includes(service.service_id)"
                type="checkbox"
                class="h-3.5 w-3.5 accent-primary"
                @change="toggleMcp(service.service_id)"
              />
              {{ service.name }}
            </label>
            <span v-if="!mcpServices.length" class="text-xs text-muted-foreground">暂无已启用 MCP，可去 MCP 中心开启。</span>
          </div>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-medium text-foreground">默认启用 Skill</p>
          <div class="flex flex-wrap gap-2">
            <label v-for="skill in boundSkills" :key="skill.id" class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
              <input
                :checked="selectedSkillIds.includes(skill.id)"
                type="checkbox"
                class="h-3.5 w-3.5 accent-primary"
                @change="toggleSkill(skill.id)"
              />
              {{ skill.name }}
            </label>
            <span v-if="!boundSkills.length" class="text-xs text-muted-foreground">当前站点还没有绑定 Skill。</span>
          </div>
        </div>

        <Button class="w-full" :disabled="creating" @click="createRun">
          {{ creating ? '创建中...' : '启动六阶段工作流' }}
        </Button>
      </template>

      <template v-else>
        <div class="space-y-2">
          <div class="text-sm font-medium">{{ workflowRun.name }}</div>
          <div class="flex flex-wrap gap-2">
            <Badge
              v-for="stage in STAGE_ORDER"
              :key="stage"
              :variant="workflowRun.current_stage === stage ? 'default' : 'outline'"
            >
              {{ workflowRun.current_stage === stage ? '当前' : '阶段' }} · {{ workflowRun.stage_status[stage] || 'pending' }}
            </Badge>
          </div>
          <div class="rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            当前阶段：{{ workflowRun.current_stage_label }}
          </div>
        </div>

        <div class="space-y-2">
          <Label for="stage-draft">阶段文档</Label>
          <textarea
            id="stage-draft"
            v-model="stageDraft"
            class="min-h-[180px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            :placeholder="`请整理${workflowRun.current_stage_label}阶段内容`"
          />
        </div>

        <div class="space-y-2">
          <p class="text-xs font-medium text-foreground">本次附带 MCP</p>
          <div class="flex flex-wrap gap-2">
            <label v-for="service in mcpServices" :key="service.service_id" class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
              <input
                :checked="selectedMcpServices.includes(service.service_id)"
                type="checkbox"
                class="h-3.5 w-3.5 accent-primary"
                @change="toggleMcp(service.service_id)"
              />
              {{ service.name }}
            </label>
          </div>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-medium text-foreground">本次附带 Skill</p>
          <div class="flex flex-wrap gap-2">
            <label v-for="skill in boundSkills" :key="skill.id" class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
              <input
                :checked="selectedSkillIds.includes(skill.id)"
                type="checkbox"
                class="h-3.5 w-3.5 accent-primary"
                @change="toggleSkill(skill.id)"
              />
              {{ skill.name }}
            </label>
          </div>
        </div>

        <div class="flex gap-2">
          <Button class="flex-1" variant="outline" :disabled="savingStage" @click="saveStage">
            {{ savingStage ? '保存中...' : '保存阶段文档' }}
          </Button>
          <Button class="flex-1" :disabled="confirming" @click="confirmStage">
            {{ confirming ? '推进中...' : '确认并进入下一阶段' }}
          </Button>
        </div>

        <div class="space-y-2 rounded-md border border-dashed border-border/70 p-3">
          <div class="text-sm font-medium">执行区</div>
          <p class="text-xs text-muted-foreground">
            只有在执行 / 优化阶段才允许直接创建 AI 编码任务。
          </p>
          <div class="flex gap-1">
            <button
              v-for="item in PROVIDERS"
              :key="item.value"
              type="button"
              class="flex-1 rounded border px-2 py-1 text-xs transition-colors"
              :class="provider === item.value ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background'"
              @click="provider = item.value"
            >
              {{ item.label }}
            </button>
          </div>
          <textarea
            v-model="taskPrompt"
            class="min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            placeholder="补充当前阶段要执行的具体改动、验证方式和交付要求..."
          />
          <Button class="w-full" :disabled="!canSubmitAi || !taskPrompt.trim()" @click="submitAiTask">
            {{ canSubmitAi ? '按工作流上下文提交给 AI 编码' : '当前阶段不可直接提交 AI 编码' }}
          </Button>
        </div>
      </template>
    </CardContent>
  </Card>
</template>
