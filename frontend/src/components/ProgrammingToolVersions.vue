<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import {
  ArrowUpCircle,
  CircleAlert,
  CircleCheckBig,
  Container,
  Loader2,
  PackageOpen,
  RefreshCw,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import {
  programmingToolsAPI,
  type ProgrammingToolVersion,
  type ProgrammingToolUpdateStatus,
} from '@/api/programmingTools'
import { useAuthStore } from '@/stores/auth'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const authStore = useAuthStore()
const tools = ref<ProgrammingToolVersion[]>([])
const loading = ref(false)
const refreshing = ref(false)
const pendingTool = ref<ProgrammingToolVersion | null>(null)
const updatingToolIds = reactive(new Set<string>())
let pollTimer: ReturnType<typeof setTimeout> | null = null

const isSuperuser = computed(() => Boolean(authStore.user?.is_superuser))
const hasActiveUpdate = computed(() => tools.value.some(isToolUpdating))

function isToolUpdating(tool: ProgrammingToolVersion) {
  return updatingToolIds.has(tool.id) || tool.updating || updateStatusIsActive(tool.status)
}

function clearPollTimer() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePoll() {
  clearPollTimer()
  if (!isSuperuser.value) return
  pollTimer = setTimeout(async () => {
    await loadVersions(false, true)
    schedulePoll()
  }, hasActiveUpdate.value ? 2000 : 30000)
}

async function loadVersions(refresh = false, quiet = false) {
  if (!isSuperuser.value) return
  if (!quiet) {
    if (refresh) refreshing.value = true
    else loading.value = true
  }
  try {
    const response = await programmingToolsAPI.versions(refresh)
    const loadedTools = response.tools || []
    for (const tool of loadedTools) {
      if (tool.updating || updateStatusIsActive(tool.status)) updatingToolIds.add(tool.id)
      else if (tool.status === 'success' || tool.status === 'failed') updatingToolIds.delete(tool.id)
    }
    tools.value = loadedTools
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function refreshVersions() {
  await loadVersions(true)
  schedulePoll()
}

function requestUpdate(tool: ProgrammingToolVersion) {
  if (isToolUpdating(tool)) return
  pendingTool.value = tool
}

async function confirmUpdate() {
  const tool = pendingTool.value
  pendingTool.value = null
  if (!tool || isToolUpdating(tool)) return
  updatingToolIds.add(tool.id)
  tool.updating = true
  tool.status = 'queued'
  tool.message = '等待构建最新镜像'
  try {
    const response = await programmingToolsAPI.update(tool.id)
    toast.success(`${tool.label} ${response.target_version} 已加入更新队列`)
  } catch {
    updatingToolIds.delete(tool.id)
    tool.updating = false
    tool.status = 'failed'
  } finally {
    await loadVersions(false, true)
    schedulePoll()
  }
}

function statusLabel(tool: ProgrammingToolVersion) {
  if (isToolUpdating(tool)) {
    if (tool.status === 'restarting') return '正在启动'
    if (tool.status === 'queued') return '等待更新'
    return '正在构建'
  }
  if (tool.status === 'failed') return '更新失败'
  if (!tool.healthy) return '服务异常'
  if (tool.latest_error) return '检测失败'
  if (tool.has_update) return '发现新版本'
  if (tool.current_version && tool.latest_version) return '已是最新'
  return '版本未知'
}

function statusClass(tool: ProgrammingToolVersion) {
  if (isToolUpdating(tool)) return 'border-warning/25 bg-warning/10 text-warning'
  if (tool.status === 'failed' || !tool.healthy) return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (tool.has_update) return 'border-primary/25 bg-primary/10 text-primary'
  if (tool.current_version && tool.latest_version) return 'border-success/25 bg-success/10 text-success'
  return 'border-border bg-muted text-muted-foreground'
}

function stateIcon(tool: ProgrammingToolVersion) {
  if (isToolUpdating(tool)) return Loader2
  if (tool.status === 'failed' || !tool.healthy || tool.latest_error) return CircleAlert
  if (tool.has_update) return ArrowUpCircle
  return CircleCheckBig
}

function versionText(version: string) {
  return version ? `v${version}` : '—'
}

function updateStatusIsActive(status: ProgrammingToolUpdateStatus) {
  return ['queued', 'building', 'restarting'].includes(status)
}

watch(
  isSuperuser,
  async (allowed) => {
    clearPollTimer()
    if (!allowed) return
    await loadVersions()
    schedulePoll()
  },
  { immediate: true },
)

onBeforeUnmount(clearPollTimer)
</script>

<template>
  <Card v-if="isSuperuser" class="overflow-hidden shadow-sm">
    <CardHeader class="gap-4 border-b bg-muted/20 sm:flex-row sm:items-start sm:justify-between">
      <div class="space-y-1.5">
        <div class="flex items-center gap-2">
          <Container class="size-5 text-primary" aria-hidden="true" />
          <CardTitle class="text-lg">编程工具版本</CardTitle>
        </div>
        <CardDescription>
          检查 npm 最新版本，并通过 Docker Socket 构建、替换对应的 Adapter 容器。
        </CardDescription>
      </div>
      <Button
        type="button"
        variant="outline"
        class="h-10 shrink-0"
        :disabled="loading || refreshing || hasActiveUpdate"
        aria-label="重新检查编程工具版本"
        @click="refreshVersions"
      >
        <RefreshCw class="size-4" :class="refreshing ? 'animate-spin motion-reduce:animate-none' : ''" aria-hidden="true" />
        检查更新
      </Button>
    </CardHeader>

    <CardContent class="p-0">
      <div v-if="loading" class="flex min-h-44 items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
        <Loader2 class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        正在读取版本信息
      </div>

      <div v-else class="divide-y">
        <div
          v-for="tool in tools"
          :key="tool.id"
          class="grid gap-4 px-5 py-5 transition-colors duration-200 hover:bg-muted/20 md:grid-cols-[minmax(0,1.35fr)_minmax(8rem,.7fr)_minmax(8rem,.7fr)_minmax(8.5rem,auto)] md:items-center"
        >
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2.5">
              <PackageOpen class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <p class="font-semibold">{{ tool.label }}</p>
              <Badge variant="outline" :class="statusClass(tool)">
                <component
                  :is="stateIcon(tool)"
                  class="mr-1 size-3.5"
                  :class="isToolUpdating(tool) ? 'animate-spin motion-reduce:animate-none' : ''"
                  aria-hidden="true"
                />
                {{ statusLabel(tool) }}
              </Badge>
            </div>
            <p class="mt-1.5 truncate pl-7 font-mono-data text-xs text-muted-foreground" :title="tool.package_name">
              {{ tool.package_name }}
            </p>
            <p
              v-if="tool.message && (updateStatusIsActive(tool.status) || tool.status === 'failed' || tool.status === 'success')"
              class="mt-2 pl-7 text-xs"
              :class="tool.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'"
              aria-live="polite"
            >
              {{ tool.message }}
            </p>
          </div>

          <div>
            <p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">当前版本</p>
            <p class="mt-1 font-mono-data text-sm font-semibold tabular">{{ versionText(tool.current_version) }}</p>
          </div>

          <div>
            <p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">最新版本</p>
            <p class="mt-1 font-mono-data text-sm font-semibold tabular">{{ versionText(tool.latest_version) }}</p>
            <p v-if="tool.latest_error" class="mt-1 text-xs text-destructive" :title="tool.latest_error">查询失败</p>
          </div>

          <Button
            v-if="isToolUpdating(tool)"
            type="button"
            variant="secondary"
            class="h-10 w-full border border-border bg-muted text-muted-foreground opacity-100 md:w-auto md:min-w-28"
            disabled
            aria-busy="true"
            :aria-label="`${tool.label} 更新中`"
          >
            <Loader2 class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            更新中
          </Button>

          <Button
            v-else
            type="button"
            class="h-10 w-full md:w-auto md:min-w-28"
            :variant="tool.has_update ? 'default' : 'outline'"
            :disabled="!tool.has_update || !tool.healthy"
            :aria-label="tool.has_update ? `更新 ${tool.label} 到 ${tool.latest_version}` : `${tool.label} 已是最新版本`"
            @click="requestUpdate(tool)"
          >
            <ArrowUpCircle v-if="tool.has_update" class="size-4" aria-hidden="true" />
            <CircleCheckBig v-else class="size-4" aria-hidden="true" />
            {{ tool.has_update ? '更新' : '无需更新' }}
          </Button>
        </div>

        <div v-if="!tools.length" class="flex min-h-44 flex-col items-center justify-center gap-2 px-6 text-center text-sm text-muted-foreground">
          <CircleAlert class="size-5" aria-hidden="true" />
          暂未读取到编程工具版本信息
        </div>
      </div>
    </CardContent>
  </Card>

  <AlertDialog :open="Boolean(pendingTool)" @update:open="open => { if (!open) pendingTool = null }">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>更新 {{ pendingTool?.label }}？</AlertDialogTitle>
        <AlertDialogDescription>
          main-service 将通过 Docker Socket 构建 {{ pendingTool?.latest_version }} 镜像并重启对应 Adapter。
          更新期间该工具会短暂不可用；如果新容器启动失败，系统会自动回滚。
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>取消</AlertDialogCancel>
        <AlertDialogAction @click="confirmUpdate">确认更新</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
