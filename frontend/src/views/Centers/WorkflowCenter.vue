<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { sitesAPI } from '@/api/sites'
import { workflowsAPI } from '@/api/workflows'
import type { Site, WorkflowRun } from '@/types/models'

const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const runs = ref<WorkflowRun[]>([])
const sites = ref<Site[]>([])
const message = ref('')

const createForm = reactive({
  site_id: '',
  name: '',
})

async function loadData() {
  loading.value = true
  try {
    const [runsRes, sitesRes] = await Promise.all([workflowsAPI.list(), sitesAPI.list()])
    runs.value = runsRes.runs || []
    sites.value = sitesRes.sites || []
    if (!createForm.site_id && sites.value.length) {
      createForm.site_id = sites.value[0].site_id
    }
  } finally {
    loading.value = false
  }
}

async function createRun() {
  if (!createForm.site_id) return
  creating.value = true
  message.value = ''
  try {
    const res = await workflowsAPI.create(createForm.site_id, { name: createForm.name.trim() || undefined })
    runs.value.unshift(res.run)
    message.value = `已为站点 ${res.run.site_name || res.run.site_id} 创建工作流`
    createForm.name = ''
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '创建工作流失败'
  } finally {
    creating.value = false
  }
}

const STAGE_LABELS: Record<string, string> = {
  research: '研究',
  ideate: '构思',
  plan: '计划',
  execute: '执行',
  optimize: '优化',
  review: '评审',
}

onMounted(loadData)
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-3xl font-bold tracking-tight">工作流中心</h1>
    </div>

    <div v-if="message" class="rounded-lg border bg-background px-4 py-3 text-sm">
      {{ message }}
    </div>

    <Card>
      <CardHeader>
        <CardTitle>新建工作流</CardTitle>
        <CardDescription>为某个站点启动一条新的六阶段流程。</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4 md:grid-cols-[1.2fr,1fr,auto] md:items-end">
        <div class="space-y-2">
          <Label for="workflow-site">站点</Label>
          <select id="workflow-site" v-model="createForm.site_id" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm">
            <option value="">请选择站点</option>
            <option v-for="site in sites" :key="site.site_id" :value="site.site_id">
              {{ site.name }} ({{ site.site_id }})
            </option>
          </select>
        </div>
        <div class="space-y-2">
          <Label for="workflow-name">名称</Label>
          <Input id="workflow-name" v-model="createForm.name" placeholder="例如：首页重构与发布" />
        </div>
        <Button :disabled="creating || !createForm.site_id" @click="createRun">
          {{ creating ? '创建中...' : '创建工作流' }}
        </Button>
      </CardContent>
    </Card>

    <div v-if="loading" class="rounded-lg border bg-background px-4 py-6 text-sm text-muted-foreground">
      正在加载工作流...
    </div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <Card v-for="run in runs" :key="run.id" class="border-border/70">
        <CardHeader>
          <div class="flex items-start justify-between gap-3">
            <div>
              <CardTitle class="text-lg">{{ run.name }}</CardTitle>
              <CardDescription class="mt-1">{{ run.site_name || run.site_id }}</CardDescription>
            </div>
            <Badge :variant="run.status === 'completed' ? 'secondary' : 'default'">
              {{ run.status === 'completed' ? '已完成' : '进行中' }}
            </Badge>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="flex flex-wrap gap-2">
            <Badge v-for="stage in Object.keys(STAGE_LABELS)" :key="stage" :variant="run.current_stage === stage ? 'default' : 'outline'">
              {{ STAGE_LABELS[stage] }} · {{ run.stage_status?.[stage] || 'pending' }}
            </Badge>
          </div>
          <div class="rounded-md bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
            当前阶段：{{ run.current_stage_label }}
          </div>
          <div class="flex gap-2">
            <Button class="flex-1" @click="router.push({ name: 'SiteEditor', params: { id: run.site_id } })">
              进入站点编辑
            </Button>
            <Button variant="outline" @click="router.push({ name: 'SiteEditor', params: { id: run.site_id }, query: { workflow: run.id } })">
              打开工作流
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
