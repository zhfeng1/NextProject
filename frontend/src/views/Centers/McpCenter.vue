<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { mcpAPI } from '@/api/mcp'
import type { MCPService } from '@/types/models'

const loading = ref(false)
const savingId = ref('')
const testingId = ref('')
const message = ref('')
const services = ref<MCPService[]>([])
const configDrafts = reactive<Record<string, Record<string, string>>>({})

async function loadServices() {
  loading.value = true
  try {
    const res = await mcpAPI.list()
    services.value = res.services || []
    for (const service of services.value) {
      configDrafts[service.service_id] = { ...(service.config || {}) }
    }
  } finally {
    loading.value = false
  }
}

async function saveService(service: MCPService) {
  savingId.value = service.service_id
  message.value = ''
  try {
    const res = await mcpAPI.update(service.service_id, {
      enabled: service.enabled,
      config: configDrafts[service.service_id] || {},
    })
    services.value = services.value.map(item => item.service_id === service.service_id ? res.service : item)
    message.value = `${service.name} 配置已保存`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '保存失败'
  } finally {
    savingId.value = ''
  }
}

async function testService(service: MCPService) {
  testingId.value = service.service_id
  message.value = ''
  try {
    const res = await mcpAPI.test(service.service_id)
    services.value = services.value.map(item => item.service_id === service.service_id ? res.service : item)
    message.value = `${service.name}: ${res.message}`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '测试失败'
  } finally {
    testingId.value = ''
  }
}

onMounted(loadServices)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">MCP 中心</h1>
        <p class="mt-2 text-sm text-muted-foreground">
          管理任务运行期可挂载的 MCP 能力。配置只作用于当前平台任务，不会改写宿主机全局配置。
        </p>
      </div>
      <Button variant="outline" :disabled="loading" @click="loadServices">{{ loading ? '刷新中...' : '刷新列表' }}</Button>
    </div>

    <div v-if="message" class="rounded-lg border bg-background px-4 py-3 text-sm">
      {{ message }}
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <Card v-for="service in services" :key="service.service_id" class="border-border/70">
        <CardHeader class="space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div>
              <CardTitle class="text-lg">{{ service.name }}</CardTitle>
              <CardDescription class="mt-1">{{ service.description }}</CardDescription>
            </div>
            <Badge :variant="service.enabled ? 'default' : 'secondary'">
              {{ service.enabled ? '已启用' : '未启用' }}
            </Badge>
          </div>
          <label class="inline-flex items-center gap-2 text-sm text-foreground">
            <input v-model="service.enabled" type="checkbox" class="h-4 w-4 rounded border-border accent-primary" />
            启用该 MCP 服务
          </label>
        </CardHeader>
        <CardContent class="space-y-4">
          <div v-if="service.required_fields.length" class="space-y-3">
            <div v-for="field in service.required_fields" :key="field" class="space-y-1.5">
              <Label :for="`${service.service_id}-${field}`">{{ field }}</Label>
              <Input
                :id="`${service.service_id}-${field}`"
                v-model="configDrafts[service.service_id][field]"
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
            <Button class="flex-1" :disabled="savingId === service.service_id" @click="saveService(service)">
              {{ savingId === service.service_id ? '保存中...' : '保存配置' }}
            </Button>
            <Button variant="outline" :disabled="testingId === service.service_id" @click="testService(service)">
              {{ testingId === service.service_id ? '测试中...' : '测试' }}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
