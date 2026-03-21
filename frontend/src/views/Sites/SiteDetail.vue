<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSiteStore } from '@/stores/site'
import { formatDate } from '@/utils/format'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Globe, ArrowLeft, Power, PowerOff, MonitorPlay, Settings } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const siteStore = useSiteStore()
const previewIframe = ref<HTMLIFrameElement>()

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
  <div class="space-y-6 max-w-6xl mx-auto" v-if="site">
    <!-- 顶部操作栏 -->
    <div class="flex items-center justify-between">
      <Button variant="ghost" @click="router.push({ name: 'Sites' })" class="gap-2">
        <ArrowLeft class="w-4 h-4" />
        返回列表
      </Button>
      <div class="flex items-center gap-2">
        <Button
          :variant="site.status === 'running' ? 'destructive' : 'default'"
          @click="toggleStatus"
          class="gap-2"
        >
          <PowerOff v-if="site.status === 'running'" class="w-4 h-4" />
          <Power v-else class="w-4 h-4" />
          {{ site.status === 'running' ? '停止' : '启动' }}
        </Button>
        <Button variant="outline" @click="openPreview" :disabled="site.status !== 'running'" class="gap-2">
          <MonitorPlay class="w-4 h-4" />
          在新窗口预览
        </Button>
        <Button @click="router.push({ name: 'SiteEditor', params: { id: site.site_id } })" class="gap-2">
          <Settings class="w-4 h-4" />
          编辑
        </Button>
      </div>
    </div>

    <!-- 信息卡片 -->
    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle class="text-2xl font-bold flex items-center gap-2">
          <Globe class="w-6 h-6 text-muted-foreground" />
          {{ site.name }}
        </CardTitle>
        <span :class="site.status === 'running' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'" class="px-3 py-1 text-sm rounded font-medium">
          {{ statusLabel }}
        </span>
      </CardHeader>
      <CardContent>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="flex flex-col space-y-1">
            <span class="text-sm font-medium text-muted-foreground">站点 ID</span>
            <span>{{ site.site_id }}</span>
          </div>
          <div class="flex flex-col space-y-1">
            <span class="text-sm font-medium text-muted-foreground">端口</span>
            <span>{{ site.port || '-' }}</span>
          </div>
          <div class="flex flex-col space-y-1">
            <span class="text-sm font-medium text-muted-foreground">创建时间</span>
            <span>{{ formatDate(site.created_at) }}</span>
          </div>
          <div class="flex flex-col space-y-1">
            <span class="text-sm font-medium text-muted-foreground">预览地址</span>
            <a v-if="site.preview_url" :href="site.preview_url" target="_blank" class="text-primary hover:underline truncate">{{ site.preview_url }}</a>
            <span v-else>-</span>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 内嵌预览 -->
    <Card v-if="site.status === 'running' && site.preview_url" class="overflow-hidden">
      <CardHeader class="flex flex-row items-center justify-between bg-muted/50 py-3 border-b">
        <CardTitle class="text-sm font-medium">站点实时预览</CardTitle>
        <Button size="sm" variant="outline" @click="refreshIframe">刷新容器</Button>
      </CardHeader>
      <iframe
        ref="previewIframe"
        :src="site.preview_url"
        class="w-full h-[600px] border-0"
        frameborder="0"
      />
    </Card>
    
    <Card v-else-if="site.status !== 'running'">
      <CardContent class="flex flex-col items-center justify-center h-48 text-muted-foreground">
        <MonitorPlay class="w-8 h-8 mb-2 opacity-20" />
        <p>站点未运行，启动后可预览</p>
      </CardContent>
    </Card>
  </div>
</template>
