<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { providersAPI, type ApiFormat, type LLMProvider } from '@/api/providers'
import { Plus, Check, CircleAlert, Loader2 } from 'lucide-vue-next'

interface ProviderUI extends LLMProvider {
  availableModels: string[]
  manualModel: string
  saving: boolean
  fetching: boolean
  verifying: string
  msg: string
  msgOk: boolean
}

const props = withDefaults(defineProps<{
  scopeType: 'global' | 'project'
  projectId?: string
  title?: string
  description?: string
}>(), {
  projectId: '',
  title: '模型配置',
  description: '',
})

const pageLoading = ref(false)
const addingProvider = ref(false)
const msg = ref('')
const providers = ref<ProviderUI[]>([])

const formatOptions: Array<{ value: ApiFormat; label: string; hint: string }> = [
  { value: 'responses', label: 'Responses', hint: '用于 OpenAI Responses API' },
  { value: 'messages', label: 'Claude Messages', hint: '用于 Claude Messages API' },
  { value: 'chat_completions', label: 'Chat Completions', hint: '用于 OpenAI 兼容的 Chat Completions API' },
]

function normalizeFormats(provider: Partial<LLMProvider>): ApiFormat[] {
  const raw = provider.formats?.length ? provider.formats : [provider.format || 'responses']
  const formats = raw.filter((item: string) => ['responses', 'messages', 'chat_completions'].includes(item))
  return [...new Set(formats.length ? formats : ['responses'])] as ApiFormat[]
}

function normalizeEnabledFormats(provider: Partial<LLMProvider>): ApiFormat[] {
  const formats = normalizeFormats(provider)
  const raw = Array.isArray(provider.enabled_formats) ? provider.enabled_formats : formats
  return [...new Set(raw.filter(format => formats.includes(format)))] as ApiFormat[]
}

function formatLabel(format: ApiFormat) {
  return formatOptions.find(option => option.value === format)?.label || format
}

function formatShortLabel(format: ApiFormat) {
  return ({ responses: 'R', messages: 'M', chat_completions: 'C' } as Record<ApiFormat, string>)[format]
}

function toProviderUI(provider: LLMProvider): ProviderUI {
  const formats = normalizeFormats(provider)
  return {
    ...provider,
    format: formats[0],
    formats,
    enabled_formats: normalizeEnabledFormats({ ...provider, formats }),
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
  if (props.scopeType === 'project' && !props.projectId) return
  pageLoading.value = true
  msg.value = ''
  try {
    const params = props.scopeType === 'project'
      ? { scope_type: 'project', project_id: props.projectId }
      : { scope_type: 'global' }
    const res = await providersAPI.list(params)
    providers.value = (res.providers || []).map(toProviderUI)
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || '加载模型配置失败'
  } finally {
    pageLoading.value = false
  }
}

onMounted(loadData)
watch(() => props.projectId, () => loadData())

async function addProvider() {
  if (addingProvider.value) return
  addingProvider.value = true
  msg.value = ''
  try {
    const res = await providersAPI.create({
      name: props.scopeType === 'project' ? '项目模型 Provider' : '全局模型服务',
      base_url: 'https://api.openai.com/v1',
      formats: ['responses'],
      enabled_formats: [],
      format: 'responses',
      scope_type: props.scopeType,
      project_id: props.scopeType === 'project' ? props.projectId : '',
      models: [],
      is_default: props.scopeType === 'global',
    })
    providers.value.unshift(toProviderUI(res.provider))
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || '新增模型配置失败'
  } finally {
    addingProvider.value = false
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
  provider.enabled_formats = normalizeEnabledFormats(provider).filter(item => item !== format)
  provider.format = provider.formats[0]
}

function toggleEnabledFormat(provider: ProviderUI, format: ApiFormat, checked: boolean) {
  const formats = normalizeFormats(provider)
  if (!formats.includes(format)) return
  const enabled = normalizeEnabledFormats(provider)
  provider.enabled_formats = checked
    ? [...new Set([...enabled, format])] as ApiFormat[]
    : enabled.filter(item => item !== format)
}

function eventChecked(event: Event) {
  return Boolean((event.target as HTMLInputElement | null)?.checked)
}

async function saveProvider(provider: ProviderUI) {
  provider.saving = true
  provider.msg = ''
  try {
    const formats = normalizeFormats(provider)
    const enabledFormats = normalizeEnabledFormats(provider)
    const res = await providersAPI.update(provider.id, {
      name: provider.name,
      base_url: provider.base_url,
      api_key: provider.api_key,
      models: provider.models,
      format: formats[0],
      formats,
      enabled_formats: enabledFormats,
      scope_type: props.scopeType,
      project_id: props.scopeType === 'project' ? props.projectId : '',
      is_default: provider.is_default,
    })
    Object.assign(provider, toProviderUI(res.provider))
    if (enabledFormats.length) {
      providers.value.forEach((item) => {
        if (item.id !== provider.id) {
          item.enabled_formats = normalizeEnabledFormats(item).filter(format => !enabledFormats.includes(format))
        }
      })
    }
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
  if (!window.confirm(`确认删除「${provider.name}」吗？删除后使用该配置的任务将无法发起。`)) return
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
  <section class="space-y-4">
    <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h2 class="text-base font-semibold">{{ title }}</h2>
        <p v-if="description" class="mt-1 text-sm text-muted-foreground">{{ description }}</p>
      </div>
      <Button :disabled="addingProvider || (scopeType === 'project' && !projectId)" @click="addProvider">
        <Loader2 v-if="addingProvider" class="size-4 animate-spin" />
        <Plus v-else class="size-4" />
        {{ addingProvider ? '新增中…' : '新增 Provider' }}
      </Button>
    </div>

    <div
      v-if="msg"
      role="alert"
      class="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
    >
      {{ msg }}
      <Button size="sm" variant="outline" class="ml-3 h-7 px-2 text-xs" @click="loadData">重新加载</Button>
    </div>

    <div v-if="pageLoading" class="rounded-xl border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
      正在加载模型配置…
    </div>
    <div v-else-if="!providers.length" class="rounded-xl border border-dashed py-12 text-center">
      <p class="text-sm font-medium">尚未配置{{ scopeType === 'project' ? '项目' : '全局' }}模型 Provider</p>
      <p class="mt-1 text-xs text-muted-foreground">编程任务需要至少启用一种兼容格式，并填写有效 API Key 与模型。</p>
      <Button class="mt-4" size="sm" variant="outline" @click="addProvider">
        <Plus class="size-4" />
        立即配置
      </Button>
    </div>

    <Card v-for="provider in providers" :key="provider.id" class="shadow-none">
      <CardHeader class="pb-3">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle class="text-base font-semibold">{{ provider.name || '未命名模型服务' }}</CardTitle>
            <CardDescription>{{ scopeType === 'project' ? '仅当前项目使用' : '所有项目均可使用' }}</CardDescription>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Badge :variant="scopeType === 'project' ? 'outline' : 'default'">
              {{ scopeType === 'project' ? 'Project' : 'Global' }}
            </Badge>
            <Badge v-for="format in normalizeEnabledFormats(provider)" :key="format" variant="default">
              已启用 {{ formatLabel(format) }}
            </Badge>
            <Badge v-if="!normalizeEnabledFormats(provider).length" variant="outline">未启用</Badge>
            <Button size="sm" variant="destructive" class="h-7 px-2 text-xs" @click="removeProvider(provider)">删除</Button>
          </div>
        </div>
      </CardHeader>

      <CardContent class="grid gap-4 lg:grid-cols-2">
        <div class="space-y-1.5">
          <Label :for="`provider-name-${provider.id}`">名称</Label>
          <Input :id="`provider-name-${provider.id}`" v-model="provider.name" placeholder="如：OpenAI 官方、OpenRouter" />
        </div>
        <div class="space-y-1.5">
          <Label :for="`provider-base-url-${provider.id}`">API Base URL</Label>
          <Input :id="`provider-base-url-${provider.id}`" v-model="provider.base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1.5 lg:col-span-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <Label :for="`provider-api-key-${provider.id}`">API Key <span class="text-destructive">*</span></Label>
              <p class="mt-0.5 text-xs text-muted-foreground">Key 会加密保存，任务日志不会显示明文。</p>
            </div>
            <Button size="sm" variant="outline" class="h-8 px-3 text-xs" :disabled="provider.fetching || !provider.base_url" @click="fetchModels(provider)">
              {{ provider.fetching ? '拉取中…' : '拉取模型列表' }}
            </Button>
          </div>
          <Input :id="`provider-api-key-${provider.id}`" v-model="provider.api_key" :type="provider.api_key?.includes('*') ? 'text' : 'password'" autocomplete="off" placeholder="输入 API Key" />
        </div>

        <div class="space-y-2 lg:col-span-2">
          <Label>API 格式</Label>
          <p class="text-xs leading-relaxed text-muted-foreground">“支持”描述服务能力；“启用”决定该配置是否可被选用。同一作用域的每种格式只会启用一个 Provider。</p>
          <div class="grid gap-2 md:grid-cols-3">
            <div
              v-for="option in formatOptions"
              :key="option.value"
              class="min-h-28 rounded-md border px-3 py-2.5 text-sm transition-colors"
              :class="normalizeFormats(provider).includes(option.value) ? 'border-primary bg-primary/5' : 'border-border'"
            >
              <label class="flex cursor-pointer items-start gap-2.5">
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
              <label class="mt-3 flex cursor-pointer items-center gap-2 border-t pt-2 text-xs font-medium">
                <input
                  type="checkbox"
                  class="size-4 accent-[hsl(var(--primary))]"
                  :checked="normalizeEnabledFormats(provider).includes(option.value)"
                  :disabled="!normalizeFormats(provider).includes(option.value)"
                  @change="toggleEnabledFormat(provider, option.value, eventChecked($event))"
                />
                <span :class="normalizeFormats(provider).includes(option.value) ? 'text-foreground' : 'text-muted-foreground'">
                  {{ normalizeEnabledFormats(provider).includes(option.value) ? '已启用' : '未启用' }}
                </span>
              </label>
            </div>
          </div>
        </div>

        <div class="space-y-2 lg:col-span-2">
          <Label>模型</Label>
          <div v-if="provider.availableModels.length" class="flex flex-wrap gap-2">
            <div
              v-for="model in provider.availableModels"
              :key="model"
              class="flex min-h-9 items-center gap-1.5 rounded-md border px-2 py-1 font-mono-data text-xs transition-colors"
              :class="provider.models.includes(model) ? 'border-primary bg-primary/10 text-primary' : 'border-border'"
            >
              <label class="flex min-h-8 min-w-0 flex-1 cursor-pointer items-center gap-1.5 rounded focus-within:ring-2 focus-within:ring-ring">
                <input type="checkbox" :checked="provider.models.includes(model)" class="sr-only" @change="toggleModel(provider, model)" />
                <span aria-hidden="true">{{ provider.models.includes(model) ? '✓' : '+' }}</span>
                <span class="truncate">{{ model }}</span>
              </label>
              <span v-if="provider.models.includes(model)" class="ml-1 flex gap-1">
                <button
                  v-for="format in normalizeFormats(provider)"
                  :key="format"
                  type="button"
                  class="rounded px-1 py-1 text-[10px] underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  :disabled="provider.verifying === `${model}:${format}`"
                  :aria-label="`使用 ${formatLabel(format)} 验证模型 ${model}`"
                  @click="verifyModel(provider, model, format)"
                >{{ provider.verifying === `${model}:${format}` ? '…' : `验证${formatShortLabel(format)}` }}</button>
              </span>
            </div>
          </div>
          <div v-else class="text-xs text-muted-foreground">拉取模型列表，或手动输入模型名称。</div>
          <div class="flex gap-2">
            <Input :id="`provider-manual-model-${provider.id}`" v-model="provider.manualModel" class="h-9 font-mono-data text-xs" aria-label="手动输入模型名称" placeholder="如 gpt-5-codex" @keydown.enter.prevent="addManualModel(provider)" />
            <Button size="sm" variant="outline" class="h-9 px-3 text-xs" @click="addManualModel(provider)">添加</Button>
          </div>
        </div>
      </CardContent>

      <CardFooter class="flex flex-wrap items-center gap-3">
        <Button :disabled="provider.saving || !provider.api_key" @click="saveProvider(provider)">
          {{ provider.saving ? '保存中…' : '保存模型配置' }}
        </Button>
        <span
          v-if="provider.msg"
          :role="provider.msgOk ? 'status' : 'alert'"
          aria-live="polite"
          class="flex items-center gap-1 text-sm"
          :class="provider.msgOk ? 'text-success' : 'text-destructive'"
        >
          <component :is="provider.msgOk ? Check : CircleAlert" class="size-3.5" />
          {{ provider.msg }}
        </span>
      </CardFooter>
    </Card>
  </section>
</template>
