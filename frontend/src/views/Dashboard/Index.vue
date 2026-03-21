<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import { formatDate } from '@/utils/format'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Activity,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  FolderGit2,
  Gauge,
  Globe,
  HeartPulse,
  ListTodo,
  Sparkles,
  Wrench,
} from 'lucide-vue-next'

type OverviewStats = {
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
  providers: {
    codex: number
    claude_code: number
    gemini_cli: number
  }
  tokens: {
    tracked: boolean
    tracked_tasks: number
    input: number
    output: number
    total: number
  }
  recent_tasks: Array<{
    id: string
    site_id: string
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
  templates: {
    linked_sites: number
  }
}

const router = useRouter()

const stats = ref<OverviewStats>({
  sites: { total: 0, running: 0, stopped: 0, building: 0, error: 0, git_linked: 0 },
  tasks: { total: 0, queued: 0, running: 0, success: 0, failed: 0, canceled: 0, success_rate: 0 },
  providers: { codex: 0, claude_code: 0, gemini_cli: 0 },
  tokens: { tracked: false, tracked_tasks: 0, input: 0, output: 0, total: 0 },
  recent_tasks: [],
  recent_sites: [],
  templates: { linked_sites: 0 },
})

const health = ref<{ components: Record<string, { status: string }> }>({
  components: {},
})

const loading = ref(true)

const topProvider = computed(() => {
  const items = [
    { key: 'codex', label: 'Codex', value: stats.value.providers.codex },
    { key: 'claude_code', label: 'Claude Code', value: stats.value.providers.claude_code },
    { key: 'gemini_cli', label: 'Gemini', value: stats.value.providers.gemini_cli },
  ]
  return items.sort((a, b) => b.value - a.value)[0]
})

const overviewCards = computed(() => [
  {
    title: '站点总数',
    value: stats.value.sites.total,
    helper: `${stats.value.sites.git_linked} 个来自 Git 仓库`,
    icon: Globe,
    iconClass: 'text-sky-600',
    panelClass: 'from-sky-500/15 via-sky-400/5 to-transparent',
  },
  {
    title: '任务总量',
    value: stats.value.tasks.total,
    helper: `${stats.value.tasks.running} 个正在执行`,
    icon: ListTodo,
    iconClass: 'text-amber-600',
    panelClass: 'from-amber-500/15 via-amber-400/5 to-transparent',
  },
  {
    title: 'Codex 使用次数',
    value: stats.value.providers.codex,
    helper: `Claude Code ${stats.value.providers.claude_code} 次`,
    icon: Bot,
    iconClass: 'text-emerald-600',
    panelClass: 'from-emerald-500/15 via-emerald-400/5 to-transparent',
  },
  {
    title: '任务成功率',
    value: `${stats.value.tasks.success_rate}%`,
    helper: `${stats.value.tasks.success} 成功 / ${stats.value.tasks.failed} 失败`,
    icon: Gauge,
    iconClass: 'text-violet-600',
    panelClass: 'from-violet-500/15 via-violet-400/5 to-transparent',
  },
])

const tokenCards = computed(() => [
  { label: '输入 Token', value: stats.value.tokens.input },
  { label: '输出 Token', value: stats.value.tokens.output },
  { label: '总 Token', value: stats.value.tokens.total },
])

const taskStatusItems = computed(() => [
  { label: '排队中', value: stats.value.tasks.queued, class: 'bg-zinc-100 text-zinc-700 border-zinc-200' },
  { label: '运行中', value: stats.value.tasks.running, class: 'bg-sky-100 text-sky-700 border-sky-200' },
  { label: '成功', value: stats.value.tasks.success, class: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  { label: '失败', value: stats.value.tasks.failed, class: 'bg-red-100 text-red-700 border-red-200' },
  { label: '取消', value: stats.value.tasks.canceled, class: 'bg-zinc-100 text-zinc-600 border-zinc-200' },
])

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function providerLabel(provider: string) {
  if (provider === 'claude_code') return 'Claude Code'
  if (provider === 'gemini_cli') return 'Gemini'
  if (provider === 'codex') return 'Codex'
  return provider || 'System'
}

function taskStatusLabel(status: string) {
  return {
    queued: '排队中',
    running: '运行中',
    success: '成功',
    failed: '失败',
    canceled: '已取消',
  }[status] || status
}

function siteStatusLabel(status: string) {
  return {
    running: '运行中',
    stopped: '已停止',
    building: '构建中',
    error: '异常',
  }[status] || status
}

function healthTone(status: string) {
  return status === 'ok'
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : 'bg-red-100 text-red-700 border-red-200'
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await client.get('/stats/overview') as unknown as OverviewStats
    if (data) stats.value = data
  } catch {}

  try {
    const res = await fetch('/api/health')
    if (res.ok) {
      health.value = await res.json()
    }
  } catch {}
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <section class="relative overflow-hidden rounded-3xl border bg-gradient-to-br from-[#f4f8ff] via-[#fffaf2] to-[#f6fff7] p-6 shadow-sm">
      <div class="absolute -right-12 top-0 h-40 w-40 rounded-full bg-sky-200/30 blur-3xl" />
      <div class="absolute bottom-0 left-0 h-32 w-32 rounded-full bg-emerald-200/30 blur-3xl" />
      <div class="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div class="space-y-3">
          <div class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-3 py-1 text-xs text-slate-600 backdrop-blur">
            <Sparkles class="h-3.5 w-3.5 text-amber-500" />
            NextProject 控制台
          </div>
          <div>
            <h1 class="text-3xl font-bold tracking-tight text-slate-900">系统概览</h1>
            <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              从站点、任务、AI 使用和服务健康四个维度看当前系统状态。首页重点展示可直接驱动决策的数据，而不是只放几个静态数字。
            </p>
          </div>
        </div>
        <div class="grid gap-3 sm:grid-cols-3">
          <Button @click="router.push('/sites')" class="gap-2">
            <Globe class="h-4 w-4" />
            管理站点
          </Button>
          <Button variant="secondary" @click="router.push('/tasks')" class="gap-2">
            <ListTodo class="h-4 w-4" />
            查看任务
          </Button>
          <Button variant="outline" @click="router.push('/templates')" class="gap-2 bg-white/70">
            <Wrench class="h-4 w-4" />
            模板市场
          </Button>
        </div>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card
        v-for="card in overviewCards"
        :key="card.title"
        class="relative overflow-hidden border-0 bg-white shadow-sm"
      >
        <div class="absolute inset-0 bg-gradient-to-br" :class="card.panelClass" />
        <CardHeader class="relative flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium text-slate-600">{{ card.title }}</CardTitle>
          <component :is="card.icon" class="h-4 w-4" :class="card.iconClass" />
        </CardHeader>
        <CardContent class="relative">
          <div class="text-3xl font-bold tracking-tight text-slate-900">
            {{ typeof card.value === 'number' ? formatNumber(card.value) : card.value }}
          </div>
          <p class="mt-1 text-xs text-slate-500">{{ card.helper }}</p>
        </CardContent>
      </Card>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
      <Card class="border-0 shadow-sm">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>AI 使用面板</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">关注各代理使用频率和当前 token 记录情况</p>
          </div>
          <div class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
            最活跃：{{ topProvider.label }}
          </div>
        </CardHeader>
        <CardContent class="space-y-5">
          <div class="grid gap-3 md:grid-cols-3">
            <div class="rounded-2xl border bg-slate-50 p-4">
              <div class="text-xs text-slate-500">Codex</div>
              <div class="mt-2 text-2xl font-semibold text-slate-900">{{ formatNumber(stats.providers.codex) }}</div>
            </div>
            <div class="rounded-2xl border bg-slate-50 p-4">
              <div class="text-xs text-slate-500">Claude Code</div>
              <div class="mt-2 text-2xl font-semibold text-slate-900">{{ formatNumber(stats.providers.claude_code) }}</div>
            </div>
            <div class="rounded-2xl border bg-slate-50 p-4">
              <div class="text-xs text-slate-500">Gemini</div>
              <div class="mt-2 text-2xl font-semibold text-slate-900">{{ formatNumber(stats.providers.gemini_cli) }}</div>
            </div>
          </div>

          <div class="rounded-2xl border bg-gradient-to-r from-slate-950 to-slate-800 p-4 text-slate-50">
            <div class="flex items-start justify-between gap-4">
              <div>
                <div class="text-sm font-medium">Token 消耗</div>
                <p class="mt-1 text-xs text-slate-300">
                  {{ stats.tokens.tracked ? `当前已统计 ${stats.tokens.tracked_tasks} 条带 usage 的任务结果` : '当前任务结果里还没有记录 usage 字段，Token 统计暂未接入' }}
                </p>
              </div>
              <div class="rounded-full border border-white/15 px-3 py-1 text-xs text-slate-200">
                {{ stats.tokens.tracked ? '已接入' : '未接入' }}
              </div>
            </div>
            <div class="mt-4 grid gap-3 sm:grid-cols-3">
              <div v-for="item in tokenCards" :key="item.label" class="rounded-xl bg-white/5 p-3">
                <div class="text-[11px] uppercase tracking-wide text-slate-400">{{ item.label }}</div>
                <div class="mt-2 text-2xl font-semibold">{{ formatNumber(item.value) }}</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card class="border-0 shadow-sm">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>运行态势</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">站点来源、模板覆盖和任务状态分布</p>
          </div>
          <Activity class="h-4 w-4 text-slate-400" />
        </CardHeader>
        <CardContent class="space-y-5">
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="rounded-2xl border bg-slate-50 p-4">
              <div class="flex items-center gap-2 text-sm text-slate-600">
                <FolderGit2 class="h-4 w-4 text-slate-500" />
                Git 站点
              </div>
              <div class="mt-2 text-2xl font-semibold text-slate-900">{{ formatNumber(stats.sites.git_linked) }}</div>
            </div>
            <div class="rounded-2xl border bg-slate-50 p-4">
              <div class="flex items-center gap-2 text-sm text-slate-600">
                <Sparkles class="h-4 w-4 text-slate-500" />
                模板创建站点
              </div>
              <div class="mt-2 text-2xl font-semibold text-slate-900">{{ formatNumber(stats.templates.linked_sites) }}</div>
            </div>
          </div>

          <div>
            <div class="mb-2 text-sm font-medium text-slate-800">任务状态分布</div>
            <div class="flex flex-wrap gap-2">
              <div
                v-for="item in taskStatusItems"
                :key="item.label"
                class="rounded-full border px-3 py-1 text-xs font-medium"
                :class="item.class"
              >
                {{ item.label }} {{ formatNumber(item.value) }}
              </div>
            </div>
          </div>

          <div>
            <div class="mb-2 text-sm font-medium text-slate-800">服务健康</div>
            <div class="space-y-2" v-if="Object.keys(health.components).length">
              <div
                v-for="(info, name) in health.components"
                :key="name"
                class="flex items-center justify-between rounded-xl border px-3 py-2"
              >
                <span class="text-sm text-slate-700">{{ name }}</span>
                <span class="rounded-full border px-2.5 py-1 text-xs font-medium" :class="healthTone(info.status)">
                  {{ info.status }}
                </span>
              </div>
            </div>
            <div v-else class="rounded-xl border border-dashed px-3 py-6 text-sm text-muted-foreground">
              暂无健康数据
            </div>
          </div>
        </CardContent>
      </Card>
    </section>

    <section class="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <Card class="border-0 shadow-sm">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>最近任务</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">快速回看最近的 AI 开发、部署和测试活动</p>
          </div>
          <Button variant="ghost" size="sm" class="gap-1" @click="router.push('/tasks')">
            全部任务
            <ChevronRight class="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent>
          <div v-if="stats.recent_tasks.length" class="space-y-2">
            <button
              v-for="task in stats.recent_tasks"
              :key="task.id"
              type="button"
              class="flex w-full items-center gap-3 rounded-2xl border bg-white px-3 py-3 text-left transition-colors hover:bg-slate-50"
              @click="router.push('/tasks')"
            >
              <div class="rounded-xl bg-slate-100 p-2">
                <Bot class="h-4 w-4 text-slate-600" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium text-slate-900">{{ providerLabel(task.provider) }}</span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{{ taskStatusLabel(task.status) }}</span>
                </div>
                <div class="mt-1 text-xs text-slate-500">
                  站点 {{ task.site_id }} · {{ task.task_type }} · {{ formatDate(task.finished_at || task.created_at || '') }}
                </div>
              </div>
            </button>
          </div>
          <div v-else class="rounded-2xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            还没有任务活动
          </div>
        </CardContent>
      </Card>

      <Card class="border-0 shadow-sm">
        <CardHeader class="flex flex-row items-center justify-between">
          <div>
            <CardTitle>最近站点</CardTitle>
            <p class="mt-1 text-sm text-muted-foreground">查看最近创建或更新的站点，以及它们的来源</p>
          </div>
          <HeartPulse class="h-4 w-4 text-slate-400" />
        </CardHeader>
        <CardContent>
          <div v-if="stats.recent_sites.length" class="space-y-2">
            <button
              v-for="site in stats.recent_sites"
              :key="site.site_id"
              type="button"
              class="flex w-full items-center gap-3 rounded-2xl border bg-white px-3 py-3 text-left transition-colors hover:bg-slate-50"
              @click="router.push({ name: 'SiteEditor', params: { id: site.site_id } })"
            >
              <div class="rounded-xl p-2" :class="site.source === 'git' ? 'bg-emerald-100' : 'bg-slate-100'">
                <component :is="site.source === 'git' ? FolderGit2 : Globe" class="h-4 w-4" :class="site.source === 'git' ? 'text-emerald-700' : 'text-slate-600'" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="truncate text-sm font-medium text-slate-900">{{ site.name }}</span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{{ siteStatusLabel(site.status) }}</span>
                </div>
                <div class="mt-1 text-xs text-slate-500">
                  {{ site.site_id }} · {{ site.source === 'git' ? 'Git 导入' : '空白/模板' }} · {{ formatDate(site.created_at || '') }}
                </div>
              </div>
            </button>
          </div>
          <div v-else class="rounded-2xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            还没有站点数据
          </div>
        </CardContent>
      </Card>
    </section>
  </div>
</template>
