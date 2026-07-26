<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import { formatDate } from '@/utils/format'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import BuildLogModal from '@/components/BuildLogModal.vue'
import { PROGRAMMING_TOOL_IDS, programmingToolLabel } from '@/api/programmingTools'
import {
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  FolderGit2,
  Gauge,
  Globe,
  ListTodo,
  MessagesSquare,
} from 'lucide-vue-next'

type OverviewStats = {
  projects: { total: number }
  sites: {
    total: number
    running: number
    stopped: number
    building: number
    error: number
    git_linked: number
  }
  tasks: {
    total: number
    queued: number
    running: number
    success: number
    failed: number
    canceled: number
    success_rate: number
  }
  providers: Record<string, number>
  tokens: { tracked: boolean; tracked_tasks: number; input: number; output: number; total: number }
  recent_tasks: Array<{
    id: string
    site_id: string
    project_id?: string
    provider: string
    task_type: string
    status: string
    created_at: string | null
    finished_at: string | null
  }>
  recent_sites: Array<{
    site_id: string
    name: string
    status: string
    created_at: string | null
    source: string
  }>
  templates: { linked_sites: number }
}

const router = useRouter()

const stats = ref<OverviewStats>({
  projects: { total: 0 },
  sites: { total: 0, running: 0, stopped: 0, building: 0, error: 0, git_linked: 0 },
  tasks: { total: 0, queued: 0, running: 0, success: 0, failed: 0, canceled: 0, success_rate: 0 },
  providers: {},
  tokens: { tracked: false, tracked_tasks: 0, input: 0, output: 0, total: 0 },
  recent_tasks: [],
  recent_sites: [],
  templates: { linked_sites: 0 },
})

const health = ref<{ components: Record<string, { status: string }> }>({ components: {} })
const loading = ref(true)

const buildLogOpen = ref(false)
const buildLogSiteId = ref('')
const buildLogSiteName = ref('')

function openBuildLog(siteId: string, name: string) {
  buildLogSiteId.value = siteId
  buildLogSiteName.value = name
  buildLogOpen.value = true
}

// The thesis number: what an operator cares about most right now.
const primaryMetric = computed(() => ({
  running: stats.value.tasks.running,
  queued: stats.value.tasks.queued,
}))

const providerBars = computed(() => {
  const items = PROGRAMMING_TOOL_IDS.map(id => ({
    id,
    label: programmingToolLabel(id),
    value: Number(stats.value.providers[id] || 0),
  }))
  const max = Math.max(...items.map((item) => item.value), 1)
  return items.map(item => ({ ...item, pct: Math.round((item.value / max) * 100) }))
})

const visibleProviderCalls = computed(() => providerBars.value.reduce((total, item) => total + item.value, 0))
const visibleProviderSummary = computed(() => {
  const used = providerBars.value.filter(item => item.value > 0)
  return used.length
    ? used.map(item => `${item.label} ${item.value}`).join(' · ')
    : '暂无可见工具调用'
})

const overviewCards = computed(() => [
  {
    title: '项目总数',
    value: stats.value.projects.total,
    helper: `${stats.value.sites.total} 个站点 · ${stats.value.sites.running} 运行中`,
    icon: Globe,
    tone: 'primary' as const,
  },
  {
    title: '任务总量',
    value: stats.value.tasks.total,
    helper: `${stats.value.tasks.running} 运行中 · ${stats.value.tasks.queued} 排队`,
    icon: ListTodo,
    tone: 'warning' as const,
  },
  {
    title: 'AI 调用次数',
    value: visibleProviderCalls.value,
    helper: visibleProviderSummary.value,
    icon: Bot,
    tone: 'success' as const,
  },
  {
    title: '任务成功率',
    value: `${stats.value.tasks.success_rate}%`,
    helper: `${stats.value.tasks.success} 成功 / ${stats.value.tasks.failed} 失败`,
    icon: Gauge,
    tone: 'primary' as const,
  },
])

const taskStatusItems = computed(() => [
  { label: '排队', value: stats.value.tasks.queued, tone: 'muted' as const },
  { label: '运行', value: stats.value.tasks.running, tone: 'warning' as const },
  { label: '成功', value: stats.value.tasks.success, tone: 'success' as const },
  { label: '失败', value: stats.value.tasks.failed, tone: 'danger' as const },
  { label: '取消', value: stats.value.tasks.canceled, tone: 'muted' as const },
])

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function providerLabel(provider: string) {
  return programmingToolLabel(provider)
}

function taskStatusTone(status: string): 'muted' | 'warning' | 'success' | 'danger' {
  return ({ queued: 'muted', running: 'warning', success: 'success', failed: 'danger', canceled: 'muted' } as const)[status as 'queued'] ?? 'muted'
}

function taskStatusLabel(status: string) {
  return ({ queued: '排队中', running: '运行中', success: '成功', failed: '失败', canceled: '已取消' } as const)[status as 'queued'] || status
}

function siteStatusLabel(status: string) {
  return ({ running: '运行中', stopped: '已停止', building: '构建中', error: '异常' } as const)[status as 'running'] || status
}

function siteStatusTone(status: string): 'success' | 'muted' | 'warning' | 'danger' {
  return ({ running: 'success', stopped: 'muted', building: 'warning', error: 'danger' } as const)[status as 'running'] ?? 'muted'
}

function healthTone(status: string): 'success' | 'danger' {
  return status === 'ok' ? 'success' : 'danger'
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await client.get('/stats/overview') as unknown as OverviewStats
    if (data) stats.value = data
  } catch {}
  try {
    const res = await fetch('/api/health')
    if (res.ok) health.value = await res.json()
  } catch {}
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <!-- Thesis hero: the one number that matters -->
    <section class="overflow-hidden rounded-xl border bg-card">
      <div class="grid gap-px bg-border sm:grid-cols-3">
        <!-- Primary metric -->
        <div class="bg-card p-6 sm:col-span-1">
          <div class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <CircleDot class="size-3.5 text-primary" />
            实时任务
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="stat-num text-5xl text-foreground">{{ formatNumber(primaryMetric.running) }}</span>
            <span class="text-sm text-muted-foreground">运行中</span>
          </div>
          <div class="mt-1 font-mono-data text-xs text-muted-foreground">
            + {{ formatNumber(primaryMetric.queued) }} 排队
          </div>
        </div>

        <!-- Context + actions -->
        <div class="bg-card p-6 sm:col-span-2">
          <div class="flex h-full flex-col justify-between gap-5">
            <div>
              <h1 class="text-xl font-semibold tracking-tight">系统概览</h1>
              <p class="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
                从站点、任务、AI 调用和服务健康四个维度，掌握当前系统状态，并直接驱动下一步操作。
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <Button @click="router.push('/projects')">
                <Globe class="size-4" />
                管理项目
              </Button>
              <Button variant="outline" @click="router.push('/tasks')">
                <MessagesSquare class="size-4" />
                开发会话
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Stat cards -->
    <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card v-for="card in overviewCards" :key="card.title" class="shadow-none">
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium text-muted-foreground">{{ card.title }}</CardTitle>
          <div
            class="flex size-8 items-center justify-center rounded-lg"
            :class="{
              'bg-primary/10 text-primary': card.tone === 'primary',
              'bg-warning/10 text-warning': card.tone === 'warning',
              'bg-success/10 text-success': card.tone === 'success',
            }"
          >
            <component :is="card.icon" class="size-4" />
          </div>
        </CardHeader>
        <CardContent>
          <div class="stat-num text-3xl text-foreground">
            {{ typeof card.value === 'number' ? formatNumber(card.value) : card.value }}
          </div>
          <p class="mt-1.5 font-mono-data text-xs text-muted-foreground">{{ card.helper }}</p>
        </CardContent>
      </Card>
    </section>

    <!-- AI usage + run status -->
    <section class="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
      <!-- AI usage -->
      <Card class="shadow-none">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>AI 调用</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">各代理使用频率与 Token 消耗</p>
          </div>
        </CardHeader>
        <CardContent class="space-y-5">
          <div class="space-y-3">
            <div v-for="item in providerBars" :key="item.label">
              <div class="mb-1.5 flex items-center justify-between text-sm">
                <span class="font-medium">{{ item.label }}</span>
                <span class="stat-num text-base text-muted-foreground">{{ formatNumber(item.value) }}</span>
              </div>
              <div class="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary transition-all"
                  :style="{ width: `${item.pct}%` }"
                />
              </div>
            </div>
          </div>

          <div class="rounded-lg border bg-muted/30 p-4">
            <div class="flex items-center justify-between">
              <span class="text-sm font-medium">Token 消耗</span>
              <span
                class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium"
                :class="stats.tokens.tracked
                  ? 'border-success/30 bg-success/10 text-success'
                  : 'border-border bg-muted text-muted-foreground'"
              >
                <span
                  class="status-dot"
                  :data-tone="stats.tokens.tracked ? 'success' : 'muted'"
                />
                {{ stats.tokens.tracked ? '已统计' : '未接入' }}
              </span>
            </div>
            <p class="mt-1.5 text-xs text-muted-foreground">
              {{ stats.tokens.tracked
                ? `当前已统计 ${stats.tokens.tracked_tasks} 条带 usage 的任务结果`
                : '任务结果尚未记录 usage 字段，Token 统计暂未接入' }}
            </p>
            <div class="mt-3 grid grid-cols-3 gap-3">
              <div>
                <div class="font-mono-data text-[11px] uppercase tracking-wide text-muted-foreground">输入</div>
                <div class="stat-num mt-1 text-lg text-foreground">{{ formatNumber(stats.tokens.input) }}</div>
              </div>
              <div>
                <div class="font-mono-data text-[11px] uppercase tracking-wide text-muted-foreground">输出</div>
                <div class="stat-num mt-1 text-lg text-foreground">{{ formatNumber(stats.tokens.output) }}</div>
              </div>
              <div>
                <div class="font-mono-data text-[11px] uppercase tracking-wide text-muted-foreground">合计</div>
                <div class="stat-num mt-1 text-lg text-foreground">{{ formatNumber(stats.tokens.total) }}</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Run status -->
      <Card class="shadow-none">
        <CardHeader>
          <CardTitle>运行态势</CardTitle>
          <p class="mt-1 text-sm text-muted-foreground">任务状态分布与服务健康</p>
        </CardHeader>
        <CardContent class="space-y-5">
          <div class="grid grid-cols-2 gap-3">
            <div class="rounded-lg border bg-muted/30 p-3.5">
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                <FolderGit2 class="size-3.5" />
                Git 站点
              </div>
              <div class="stat-num mt-1.5 text-2xl text-foreground">{{ formatNumber(stats.sites.git_linked) }}</div>
            </div>
            <div class="rounded-lg border bg-muted/30 p-3.5">
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                <Globe class="size-3.5" />
                运行站点
              </div>
              <div class="stat-num mt-1.5 text-2xl text-foreground">{{ formatNumber(stats.sites.running) }}</div>
            </div>
          </div>

          <div>
            <div class="mb-2 text-sm font-medium">任务状态分布</div>
            <div class="space-y-1.5">
              <div
                v-for="item in taskStatusItems"
                :key="item.label"
                class="flex items-center justify-between rounded-md border bg-card px-3 py-1.5 text-sm"
              >
                <span class="flex items-center gap-2">
                  <span class="status-dot" :data-tone="item.tone" :data-pulse="item.label === '运行'" />
                  {{ item.label }}
                </span>
                <span class="stat-num text-sm text-muted-foreground">{{ formatNumber(item.value) }}</span>
              </div>
            </div>
          </div>

          <div>
            <div class="mb-2 text-sm font-medium">服务健康</div>
            <div v-if="Object.keys(health.components).length" class="space-y-1.5">
              <div
                v-for="(info, name) in health.components"
                :key="name"
                class="flex items-center justify-between rounded-md border bg-card px-3 py-1.5 text-sm"
              >
                <span class="text-muted-foreground">{{ name }}</span>
                <span class="flex items-center gap-1.5">
                  <span class="status-dot" :data-tone="healthTone(info.status)" />
                  <span class="font-mono-data text-xs">{{ info.status }}</span>
                </span>
              </div>
            </div>
            <div v-else class="rounded-md border border-dashed px-3 py-5 text-center text-sm text-muted-foreground">
              暂无健康数据
            </div>
          </div>
        </CardContent>
      </Card>
    </section>

    <!-- Recent activity -->
    <section class="grid gap-4 xl:grid-cols-2">
      <!-- Recent tasks -->
      <Card class="shadow-none">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>最近任务</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">最近的编码、部署与测试活动</p>
          </div>
          <Button variant="ghost" size="sm" class="gap-1 text-muted-foreground" @click="router.push('/tasks')">
            全部
            <ChevronRight class="size-4" />
          </Button>
        </CardHeader>
        <CardContent>
          <div v-if="stats.recent_tasks.length" class="divide-y divide-border">
            <button
              v-for="task in stats.recent_tasks"
              :key="task.id"
              type="button"
              class="flex w-full items-center gap-3 py-2.5 text-left transition-colors hover:bg-muted/40"
              @click="router.push(task.project_id ? { path: '/tasks', query: { project_id: task.project_id } } : '/tasks')"
            >
              <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Bot class="size-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium">{{ providerLabel(task.provider) }}</span>
                  <span class="flex items-center gap-1 text-xs text-muted-foreground">
                    <span class="status-dot" :data-tone="taskStatusTone(task.status)" />
                    {{ taskStatusLabel(task.status) }}
                  </span>
                </div>
                <div class="mt-0.5 truncate font-mono-data text-xs text-muted-foreground">
                  {{ task.site_id }} · {{ task.task_type }} · {{ formatDate(task.finished_at || task.created_at || '') }}
                </div>
              </div>
            </button>
          </div>
          <div v-else class="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">
            还没有任务活动
          </div>
        </CardContent>
      </Card>

      <!-- Recent sites -->
      <Card class="shadow-none">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>最近站点</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">最近创建或更新的站点</p>
          </div>
          <Button variant="ghost" size="sm" class="gap-1 text-muted-foreground" @click="router.push('/projects')">
            全部
            <ChevronRight class="size-4" />
          </Button>
        </CardHeader>
        <CardContent>
          <div v-if="stats.recent_sites.length" class="divide-y divide-border">
            <button
              v-for="site in stats.recent_sites"
              :key="site.site_id"
              type="button"
              class="flex w-full items-center gap-3 py-2.5 text-left transition-colors hover:bg-muted/40"
              @click="router.push({ name: 'SiteEditor', params: { id: site.site_id } })"
            >
              <div
                class="flex size-8 shrink-0 items-center justify-center rounded-lg"
                :class="site.source === 'git' ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground'"
              >
                <component :is="site.source === 'git' ? FolderGit2 : Globe" class="size-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="truncate text-sm font-medium">{{ site.name }}</span>
                  <button
                    v-if="site.status === 'building'"
                    type="button"
                    class="flex items-center gap-1 text-xs text-warning hover:underline"
                    @click.stop="openBuildLog(site.site_id, site.name)"
                  >
                    构建中 · 看日志
                  </button>
                  <span v-else class="flex items-center gap-1 text-xs text-muted-foreground">
                    <span class="status-dot" :data-tone="siteStatusTone(site.status)" />
                    {{ siteStatusLabel(site.status) }}
                  </span>
                </div>
                <div class="mt-0.5 truncate font-mono-data text-xs text-muted-foreground">
                  {{ site.site_id }} · {{ site.source === 'git' ? 'Git 导入' : '空白/模板' }} · {{ formatDate(site.created_at || '') }}
                </div>
              </div>
            </button>
          </div>
          <div v-else class="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">
            还没有站点数据
          </div>
        </CardContent>
      </Card>
    </section>

    <BuildLogModal
      v-model:open="buildLogOpen"
      :site-id="buildLogSiteId"
      :site-name="buildLogSiteName"
    />
  </div>
</template>
