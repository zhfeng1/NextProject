<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, reactive, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { mcpAPI } from '@/api/mcp'
import { projectsAPI } from '@/api/projects'
import type { MCPService, Project } from '@/types/models'

const loading = ref(false)
const savingKey = ref('')
const testingKey = ref('')
const message = ref('')
const services = ref<MCPService[]>([])
const projects = ref<Project[]>([])
const filters = ref({ scope_type: '', project_id: '', site_id: '' })
const configDrafts = reactive<Record<string, Record<string, string>>>({})

const repos = computed(() => {
  const project = projects.value.find(item => item.id === filters.value.project_id)
  return project?.repos || projects.value.flatMap(item => item.repos || [])
})

function draftKey(service: MCPService) {
  if (!service._draftKey) {
    service._draftKey = `${service.service_id}:${service.scope_type}:${service.project_id || ''}:${service.site_id || ''}:${Math.random().toString(36).slice(2)}`
  }
  return service._draftKey
}

async function loadServices() {
  loading.value = true
  try {
    const [serviceRes, projectRes] = await Promise.all([
      mcpAPI.list({
        scope_type: filters.value.scope_type || undefined,
        project_id: filters.value.project_id || undefined,
        site_id: filters.value.site_id || undefined,
      }),
      projectsAPI.list(),
    ])
    projects.value = projectRes.projects || []
    services.value = (serviceRes.services || []).map(service => ({
      ...service,
      scope_type: service.scope_type || 'global',
      project_id: service.project_id || filters.value.project_id || '',
      site_id: service.site_id || filters.value.site_id || '',
    }))
    for (const service of services.value) {
      configDrafts[draftKey(service)] = { ...(service.config || {}) }
    }
  } finally {
    loading.value = false
  }
}

async function saveService(service: MCPService) {
  const key = draftKey(service)
  savingKey.value = key
  message.value = ''
  try {
    const payload = {
      name: service.name,
      description: service.description,
      enabled: service.enabled,
      scope_type: service.scope_type,
      project_id: service.scope_type === 'project' ? service.project_id : '',
      site_id: service.scope_type === 'repo' ? service.site_id : '',
      config: configDrafts[key] || {},
      required_fields: service.required_fields || [],
      supports_config: service.supports_config,
    }
    const res = await mcpAPI.update(service.service_id, payload)
    res.service._draftKey = key
    services.value = services.value.map(item => draftKey(item) === key ? res.service : item)
    configDrafts[key] = { ...(res.service.config || {}) }
    message.value = `${service.name} 配置已保存`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '保存失败'
  } finally {
    savingKey.value = ''
  }
}

async function testService(service: MCPService) {
  const key = draftKey(service)
  testingKey.value = key
  message.value = ''
  try {
    const res = await mcpAPI.test(service.service_id, {
      scope_type: service.scope_type,
      project_id: service.project_id,
      site_id: service.site_id,
    })
    services.value = services.value.map(item => draftKey(item) === key ? res.service : item)
    message.value = `${service.name}: ${res.message}`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '测试失败'
  } finally {
    testingKey.value = ''
  }
}

onMounted(loadServices)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">MCP 中心</h1>
        <p class="mt-2 text-sm text-muted-foreground">按全局、项目、仓库维护任务可挂载的 MCP 服务。</p>
      </div>
      <Button variant="outline" :disabled="loading" @click="loadServices">{{ loading ? '刷新中...' : '刷新列表' }}</Button>
    </div>

    <div class="grid gap-3 rounded-lg border bg-background p-3 md:grid-cols-4">
      <select v-model="filters.scope_type" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadServices">
        <option value="">全部作用域</option>
        <option value="global">全局</option>
        <option value="project">项目级</option>
        <option value="repo">仓库级</option>
      </select>
      <select v-model="filters.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="filters.site_id = ''; loadServices()">
        <option value="">全部项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
      </select>
      <select v-model="filters.site_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadServices">
        <option value="">全部仓库</option>
        <option v-for="repo in repos" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
      </select>
      <Button variant="outline" @click="filters = { scope_type: '', project_id: '', site_id: '' }; loadServices()">清空筛选</Button>
    </div>

    <div v-if="message" class="rounded-lg border bg-background px-4 py-3 text-sm">{{ message }}</div>

    <div class="grid gap-4 lg:grid-cols-2">
      <Card v-for="service in services" :key="draftKey(service)" class="border-border/70">
        <CardHeader class="space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div>
              <CardTitle class="text-lg">{{ service.name }}</CardTitle>
              <CardDescription class="mt-1">{{ service.description }}</CardDescription>
            </div>
            <Badge :variant="service.enabled ? 'default' : 'secondary'">{{ service.enabled ? '已启用' : '未启用' }}</Badge>
          </div>
          <div class="grid gap-2 md:grid-cols-3">
            <select v-model="service.scope_type" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm">
              <option value="global">全局</option>
              <option value="project">项目级</option>
              <option value="repo">仓库级</option>
            </select>
            <select v-model="service.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" :disabled="service.scope_type !== 'project'">
              <option value="">选择项目</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
            <select v-model="service.site_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" :disabled="service.scope_type !== 'repo'">
              <option value="">选择仓库</option>
              <option v-for="repo in projects.flatMap(item => item.repos || [])" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
            </select>
          </div>
          <label class="inline-flex items-center gap-2 text-sm text-foreground">
            <input v-model="service.enabled" type="checkbox" class="h-4 w-4 rounded border-border accent-primary" />
            启用该 MCP 服务
          </label>
        </CardHeader>
        <CardContent class="space-y-4">
          <div v-if="service.required_fields.length" class="space-y-3">
            <div v-for="field in service.required_fields" :key="field" class="space-y-1.5">
              <Label :for="`${draftKey(service)}-${field}`">{{ field }}</Label>
              <Input
                :id="`${draftKey(service)}-${field}`"
                v-model="configDrafts[draftKey(service)][field]"
                :type="field.toLowerCase().includes('key') ? 'password' : 'text'"
                :placeholder="`请输入 ${field}`"
              />
            </div>
          </div>
          <div v-else class="rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
            该服务当前无需额外配置。
          </div>

          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <span>最近测试:</span>
            <span>{{ service.last_tested_at ? service.last_tested_at.replace('T', ' ').slice(0, 19) : '尚未测试' }}</span>
            <span v-if="service.last_test_ok === true" class="text-emerald-600">可用</span>
            <span v-else-if="service.last_test_ok === false" class="text-red-600">不可用</span>
          </div>
          <div v-if="service.last_error" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300">
            {{ service.last_error }}
          </div>

          <div class="flex gap-2">
            <Button class="flex-1" :disabled="savingKey === draftKey(service)" @click="saveService(service)">
              {{ savingKey === draftKey(service) ? '保存中...' : '保存配置' }}
            </Button>
            <Button variant="outline" :disabled="testingKey === draftKey(service) || !service.id" @click="testService(service)">
              {{ testingKey === draftKey(service) ? '测试中...' : '测试' }}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
