<script setup lang="ts">
// @ts-nocheck
import { ref, onMounted } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { providersAPI, type LLMProvider } from '@/api/providers'
import { projectsAPI } from '@/api/projects'
import type { Project } from '@/types/models'
import { Plus, Check, CircleAlert, Globe, FolderKanban } from 'lucide-vue-next'

type ApiFormat = 'responses' | 'messages'

interface ProviderUI extends LLMProvider {
  availableModels: string[]
  manualModel: string
  saving: boolean
  fetching: boolean
  verifying: string
  msg: string
  msgOk: boolean
}

const pageLoading = ref(false)
const msg = ref('')
const projects = ref<Project[]>([])
const providers = ref<ProviderUI[]>([])

const formatOptions: Array<{ value: ApiFormat; label: string; hint: string }> = [
  { value: 'responses', label: 'Responses', hint: 'Codex / OpenAI Responses API' },
  { value: 'messages', label: 'Messages', hint: 'Claude Code / Anthropic Messages API' },
]

function normalizeFormats(provider: Partial<LLMProvider>): ApiFormat[] {
  const raw = provider.formats?.length ? provider.formats : [provider.format || 'responses']
  const formats = raw.filter((item: string) => item === 'responses' || item === 'messages')
  return [...new Set(formats.length ? formats : ['responses'])] as ApiFormat[]
}

function toProviderUI(provider: LLMProvider): ProviderUI {
  const formats = normalizeFormats(provider)
  return {
    ...provider,
    format: formats[0],
    formats,
    availableModels: [...(provider.models || [])],
    manualModel: '',
    saving: false,
    fetching: false,
    verifying: '',
    msg: '',
    msgOk: false,
  }
}

async function loadData() {
  pageLoading.value = true
  msg.value = ''
  try {
    const [projectRes, providerRes] = await Promise.all([
      projectsAPI.list(),
      providersAPI.list(),
    ])
    projects.value = projectRes.projects || []
    providers.value = (providerRes.providers || []).map(toProviderUI)
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || '加载模型配置失败'
  } finally {
    pageLoading.value = false
  }
}

onMounted(loadData)

async function addProvider(scopeType: 'global' | 'project') {
  msg.value = ''
  try {
    const projectId = scopeType === 'project' ? (projects.value[0]?.id || '') : ''
    const res = await providersAPI.create({
      name: scopeType === 'project' ? '项目模型 Provider' : '全局模型 Provider',
      base_url: 'https://api.openai.com/v1',
      formats: ['responses'],
      format: 'responses',
      scope_type: scopeType,
      project_id: projectId,
      models: [],
      is_default: scopeType === 'global',
    })
    providers.value.unshift(toProviderUI(res.provider))
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || '新增模型配置失败'
  }
}

function toggleFormat(provider: ProviderUI, format: ApiFormat, checked: boolean) {
  const current = normalizeFormats(provider)
  if (checked) {
    provider.formats = [...new Set([...current, format])] as ApiFormat[]
    provider.format = provider.formats[0]
    return
  }
  if (current.length === 1 && current[0] === format) {
    provider.msg = '至少保留一种 API 格式'
    provider.msgOk = false
    return
  }
  provider.formats = current.filter(item => item !== format)
  provider.format = provider.formats[0]
}

function eventChecked(event: Event) {
  return Boolean((event.target as HTMLInputElement | null)?.checked)
}

async function saveProvider(provider: ProviderUI) {
  provider.saving = true
  provider.msg = ''
  try {
    const formats = normalizeFormats(provider)
    const res = await providersAPI.update(provider.id, {
      name: provider.name,
      base_url: provider.base_url,
      api_key: provider.api_key,
      models: provider.models,
      format: formats[0],
      formats,
      scope_type: provider.scope_type,
      project_id: provider.scope_type === 'project' ? provider.project_id : '',
      is_default: provider.is_default,
    })
    Object.assign(provider, toProviderUI(res.provider))
    provider.msg = '已保存'
    provider.msgOk = true
  } catch (e: any) {
    provider.msg = e?.response?.data?.detail || '保存失败'
    provider.msgOk = false
  } finally {
    provider.saving = false
  }
}

async function removeProvider(provider: ProviderUI) {
  if (!window.confirm(`确认删除「${provider.name}」吗？`)) return
  try {
    await providersAPI.remove(provider.id)
    providers.value = providers.value.filter(item => item.id !== provider.id)
  } catch (e: any) {
    provider.msg = e?.response?.data?.detail || '删除失败'
    provider.msgOk = false
  }
}

async function fetchModels(provider: ProviderUI) {
  if (!provider.base_url) return
  provider.fetching = true
  provider.msg = ''
  try {
    const params: any = { base_url: provider.base_url, provider_id: provider.id }
    if (provider.api_key && !provider.api_key.includes('****')) params.api_key = provider.api_key
    const res = await providersAPI.fetchModels(params)
    if (res.ok && res.models?.length) {
      provider.availableModels = res.models
      provider.msg = `获取到 ${res.models.length} 个模型`
      provider.msgOk = true
    } else {
      provider.msg = res.error || '未获取到模型，可手动输入'
      provider.msgOk = false
    }
  } catch (e: any) {
    provider.msg = e?.response?.data?.detail || '拉取失败'
    provider.msgOk = false
  } finally {
    provider.fetching = false
  }
}

function toggleModel(provider: ProviderUI, model: string) {
  const index = provider.models.indexOf(model)
  if (index >= 0) provider.models.splice(index, 1)
  else provider.models.push(model)
}

function addManualModel(provider: ProviderUI) {
  const model = provider.manualModel.trim()
  if (!model) return
  if (!provider.availableModels.includes(model)) provider.availableModels.push(model)
  if (!provider.models.includes(model)) provider.models.push(model)
  provider.manualModel = ''
}

async function verifyModel(provider: ProviderUI, model: string, format: ApiFormat) {
  provider.verifying = `${model}:${format}`
  provider.msg = ''
  try {
    const params: any = { provider_id: provider.id, model, format }
    if (provider.api_key && !provider.api_key.includes('****')) params.api_key = provider.api_key
    const res = await providersAPI.verifyModel(params)
    provider.msg = res.ok ? `${model} (${format}): 连通正常` : `${model} (${format}): ${res.error || '验证失败'}`
    provider.msgOk = res.ok
  } catch (e: any) {
    provider.msg = `${model} (${format}): ${e?.response?.data?.detail || '验证失败'}`
    provider.msgOk = false
  } finally {
    provider.verifying = ''
  }
}
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">系统设置</h1>
        <p class="mt-1 text-sm text-muted-foreground">维护全局和项目级模型 Provider，任务执行时项目级配置优先</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button variant="outline" @click="addProvider('global')">
          <Globe class="size-4" /> 新增全局配置
        </Button>
        <Button :disabled="!projects.length" @click="addProvider('project')">
          <FolderKanban class="size-4" /> 新增项目配置
        </Button>
      </div>
    </div>

    <div
      v-if="msg"
      class="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
    >
      {{ msg }}
    </div>

    <div v-if="pageLoading" class="rounded-xl border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
      正在加载模型配置…
    </div>
    <div v-else-if="!providers.length" class="rounded-xl border border-dashed py-16 text-center text-sm text-muted-foreground">
      暂无模型配置，点击上方按钮新增
    </div>

    <Card v-for="provider in providers" :key="provider.id" class="shadow-none">
      <CardHeader class="pb-3">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle class="text-base font-semibold">{{ provider.name || '未命名 Provider' }}</CardTitle>
            <CardDescription>{{ provider.scope_type === 'project' ? '项目级配置' : '全局配置' }}</CardDescription>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Badge :variant="provider.scope_type === 'project' ? 'outline' : 'default'">
              {{ provider.scope_type === 'project' ? 'Project' : 'Global' }}
            </Badge>
            <Badge v-for="format in normalizeFormats(provider)" :key="format" variant="secondary">
              {{ format === 'responses' ? 'Responses' : 'Messages' }}
            </Badge>
            <Button size="sm" variant="destructive" class="h-7 px-2 text-xs" @click="removeProvider(provider)">删除</Button>
          </div>
        </div>
      </CardHeader>

      <CardContent class="grid gap-4 lg:grid-cols-2">
        <div class="space-y-1.5">
          <Label>名称</Label>
          <Input v-model="provider.name" placeholder="如：OpenAI 官方、Anthropic、OpenRouter" />
        </div>
        <div class="space-y-1.5">
          <Label>作用域</Label>
          <select v-model="provider.scope_type" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring">
            <option value="global">全局</option>
            <option value="project">项目级</option>
          </select>
        </div>
        <div v-if="provider.scope_type === 'project'" class="space-y-1.5">
          <Label>项目</Label>
          <select v-model="provider.project_id" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-ring">
            <option value="">选择项目</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <Label>API Base URL</Label>
          <Input v-model="provider.base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <Label>API Key</Label>
            <Button size="sm" variant="outline" class="h-6 px-2 text-[11px]" :disabled="provider.fetching || !provider.base_url" @click="fetchModels(provider)">
              {{ provider.fetching ? '拉取中…' : '拉取模型列表' }}
            </Button>
          </div>
          <Input v-model="provider.api_key" :type="provider.api_key?.includes('*') ? 'text' : 'password'" placeholder="输入新 Key 可覆盖，留空保持不变" />
        </div>

        <div class="space-y-2 lg:col-span-2">
          <Label>API 格式</Label>
          <div class="grid gap-2 md:grid-cols-2">
            <label
              v-for="option in formatOptions"
              :key="option.value"
              class="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-sm transition-colors"
              :class="normalizeFormats(provider).includes(option.value) ? 'border-primary bg-primary/5' : 'border-border'"
            >
              <input
                type="checkbox"
                class="mt-0.5 size-4 accent-[hsl(var(--primary))]"
                :checked="normalizeFormats(provider).includes(option.value)"
                @change="toggleFormat(provider, option.value, eventChecked($event))"
              />
              <span>
                <span class="block font-medium">{{ option.label }}</span>
                <span class="block text-xs text-muted-foreground">{{ option.hint }}</span>
              </span>
            </label>
          </div>
        </div>

        <div class="space-y-2 lg:col-span-2">
          <Label>模型</Label>
          <div v-if="provider.availableModels.length" class="flex flex-wrap gap-2">
            <label
              v-for="model in provider.availableModels"
              :key="model"
              class="flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 font-mono-data text-xs transition-colors"
              :class="provider.models.includes(model) ? 'border-primary bg-primary/10 text-primary' : 'border-border'"
            >
              <input type="checkbox" :checked="provider.models.includes(model)" class="sr-only" @change="toggleModel(provider, model)" />
              <span>{{ provider.models.includes(model) ? '✓' : '+' }}</span>
              {{ model }}
              <span v-if="provider.models.includes(model)" class="ml-1 flex gap-1">
                <button
                  v-for="format in normalizeFormats(provider)"
                  :key="format"
                  type="button"
                  class="text-[10px] underline"
                  :disabled="provider.verifying === `${model}:${format}`"
                  @click.stop="verifyModel(provider, model, format)"
                >{{ provider.verifying === `${model}:${format}` ? '…' : `验证${format === 'responses' ? 'R' : 'M'}` }}</button>
              </span>
            </label>
          </div>
          <div v-else class="text-xs text-muted-foreground">输入 URL 和 Key 后点击「拉取模型列表」，或手动添加模型。</div>
          <div class="flex gap-2">
            <Input v-model="provider.manualModel" class="h-8 font-mono-data text-xs" placeholder="手动输入模型名称，如 gpt-5-codex" @keydown.enter="addManualModel(provider)" />
            <Button size="sm" variant="outline" class="h-8 px-3 text-xs" @click="addManualModel(provider)">添加</Button>
          </div>
        </div>
      </CardContent>

      <CardFooter class="flex flex-wrap items-center gap-3">
        <Button :disabled="provider.saving || (provider.scope_type === 'project' && !provider.project_id)" @click="saveProvider(provider)">
          {{ provider.saving ? '保存中…' : '保存模型配置' }}
        </Button>
        <span
          v-if="provider.msg"
          class="flex items-center gap-1 text-sm"
          :class="provider.msgOk ? 'text-success' : 'text-destructive'"
        >
          <component :is="provider.msgOk ? Check : CircleAlert" class="size-3.5" />
          {{ provider.msg }}
        </span>
      </CardFooter>
    </Card>
  </div>
</template>
