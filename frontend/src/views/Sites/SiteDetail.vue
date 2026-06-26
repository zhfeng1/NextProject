<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSiteStore } from '@/stores/site'
import { formatDate } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Globe, ArrowLeft, Power, PowerOff, MonitorPlay, Settings } from 'lucide-vue-next'
import BuildLogModal from '@/components/BuildLogModal.vue'

const route = useRoute()
const router = useRouter()
const siteStore = useSiteStore()
const previewIframe = ref<HTMLIFrameElement>()

const buildLogOpen = ref(false)

const siteId = route.params.id as string
const site = computed(() => siteStore.currentSite)

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    running: '运行中',
    stopped: '已停止',
    failed: '失败',
    building: '构建中',
  }
  return map[site.value?.status || ''] || site.value?.status
})

function statusTone(status: string | undefined): 'success' | 'muted' | 'warning' | 'danger' {
  if (!status) return 'muted'
  return ({ running: 'success', stopped: 'muted', failed: 'danger', building: 'warning', error: 'danger' } as const)[status as 'running'] ?? 'muted'
}

onMounted(() => {
  siteStore.fetchSite(siteId)
})

const toggleStatus = async () => {
  if (!site.value) return
  try {
    if (site.value.status === 'running') {
      await siteStore.stopSite(siteId)
    } else {
      await siteStore.startSite(siteId)
    }
    await siteStore.fetchSite(siteId)
  } catch (error) {}
}

const openPreview = () => {
  if (site.value?.preview_url) {
    window.open(site.value.preview_url, '_blank')
  }
}

const refreshIframe = () => {
  if (previewIframe.value) {
    previewIframe.value.src = previewIframe.value.src
  }
}
</script>

<template>
  <div class="mx-auto max-w-6xl space-y-6" v-if="site">
    <div class="flex items-center justify-between">
      <Button variant="ghost" size="sm" class="-ml-2 text-muted-foreground" @click="router.push({ name: 'ProjectList' })">
        <ArrowLeft class="size-4" />
        站点
      </Button>
      <div class="flex items-center gap-2">
        <Button
          :variant="site.status === 'running' ? 'destructive' : 'default'"
          @click="toggleStatus"
        >
          <component :is="site.status === 'running' ? PowerOff : Power" class="size-4" />
          {{ site.status === 'running' ? '停止' : '启动' }}
        </Button>
        <Button variant="outline" @click="openPreview" :disabled="site.status !== 'running'">
          <MonitorPlay class="size-4" />
          新窗口预览
        </Button>
        <Button @click="router.push({ name: 'SiteEditor', params: { id: site.site_id } })">
          <Settings class="size-4" />
          编辑
        </Button>
      </div>
    </div>

    <Card class="shadow-none">
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle class="flex items-center gap-2 text-xl font-semibold">
          <div class="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Globe class="size-5" />
          </div>
          {{ site.name }}
        </CardTitle>
        <button
          v-if="site.status === 'building'"
          type="button"
          class="flex items-center gap-1.5 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1 text-xs font-medium text-warning hover:bg-warning/15"
          @click="buildLogOpen = true"
        >
          <span class="status-dot" data-tone="warning" data-pulse="true" />
          {{ statusLabel }} · 看日志
        </button>
        <span
          v-else
          class="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium"
          :class="site.status === 'running'
            ? 'border-success/30 bg-success/10 text-success'
            : 'border-border bg-muted text-muted-foreground'"
        >
          <span class="status-dot" :data-tone="statusTone(site.status)" />
          {{ statusLabel }}
        </span>
      </CardHeader>
      <CardContent>
        <dl class="grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-2">
          <div class="space-y-1">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">站点 ID</dt>
            <dd class="font-mono-data text-sm">{{ site.site_id }}</dd>
          </div>
          <div class="space-y-1">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">端口</dt>
            <dd class="font-mono-data text-sm">{{ site.port || '—' }}</dd>
          </div>
          <div class="space-y-1">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">创建时间</dt>
            <dd class="font-mono-data text-sm">{{ formatDate(site.created_at) }}</dd>
          </div>
          <div class="space-y-1">
            <dt class="text-xs uppercase tracking-wide text-muted-foreground">预览地址</dt>
            <dd class="truncate text-sm">
              <a v-if="site.preview_url" :href="site.preview_url" target="_blank" class="text-primary hover:underline">{{ site.preview_url }}</a>
              <span v-else class="text-muted-foreground">—</span>
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>

    <Card v-if="site.status === 'running' && site.preview_url" class="overflow-hidden shadow-none">
      <CardHeader class="flex flex-row items-center justify-between border-b bg-muted/40 py-3">
        <CardTitle class="text-sm font-medium">站点实时预览</CardTitle>
        <Button size="sm" variant="outline" @click="refreshIframe">刷新容器</Button>
      </CardHeader>
      <iframe
        ref="previewIframe"
        :src="site.preview_url"
        class="h-[600px] w-full border-0"
        frameborder="0"
      />
    </Card>

    <Card v-else-if="site.status !== 'running'" class="shadow-none">
      <CardContent class="flex h-48 flex-col items-center justify-center text-muted-foreground">
        <MonitorPlay class="mb-2 size-8 opacity-20" />
        <p class="text-sm">站点未运行，启动后可预览</p>
      </CardContent>
    </Card>

    <BuildLogModal
      v-model:open="buildLogOpen"
      :site-id="site.site_id"
      :site-name="site.name"
    />
  </div>
</template>
