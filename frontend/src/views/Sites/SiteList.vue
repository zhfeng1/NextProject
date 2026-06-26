<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSiteStore } from '@/stores/site'
import { formatDate } from '@/utils/format'
import type { Site } from '@/types/models'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { MonitorPlay, Settings, Power, PowerOff, Trash2, Plus, Globe, FolderTree } from 'lucide-vue-next'
import SiteFileBrowserDialog from '@/components/SiteFileBrowserDialog.vue'
import { toast } from 'vue-sonner'

const router = useRouter()
const siteStore = useSiteStore()

const filter = ref({ status: '', search: '' })
const showCreateDialog = ref(false)
const creating = ref(false)
const fileBrowserOpen = ref(false)
const fileBrowserSite = ref<Site | null>(null)

const createForm = ref({
  name: '',
  template_id: '',
  git_url: '',
  git_branch: '',
  git_username: '',
  git_password: '',
  start_command: '',
})

const filteredSites = computed(() => {
  let sites = siteStore.sites
  if (filter.value.status && filter.value.status !== 'all') {
    sites = sites.filter((s) => s.status === filter.value.status)
  }
  if (filter.value.search) {
    const query = filter.value.search.toLowerCase()
    sites = sites.filter(s => s.name.toLowerCase().includes(query) || s.site_id.toLowerCase().includes(query))
  }
  return sites
})

onMounted(() => {
  siteStore.fetchSites()
})

const toggleSiteStatus = async (site: Site) => {
  try {
    if (site.status === 'running') {
      await siteStore.stopSite(site.site_id)
    } else {
      await siteStore.startSite(site.site_id)
    }
  } catch (error) {}
}

const previewSite = (site: Site) => {
  if (site.preview_url) window.open(site.preview_url, '_blank')
}

const editSite = (site: Site) => {
  router.push({ name: 'SiteEditor', params: { id: site.site_id } })
}

const openFileBrowser = (site: Site) => {
  fileBrowserSite.value = site
  fileBrowserOpen.value = true
}

const deleteSite = async (site: Site) => {
  if (window.confirm('确定删除这个站点吗？')) {
    try {
      await siteStore.deleteSite(site.site_id)
    } catch {}
  }
}

const createSite = async () => {
  if (!createForm.value.name) return toast.warning('请输入站点名称')
  if (createForm.value.git_password && !createForm.value.git_username) {
    return toast.warning('填写 Git 密码时请同时填写用户名')
  }
  creating.value = true
  try {
    await siteStore.createSite({
      name: createForm.value.name,
      template_id: createForm.value.git_url ? undefined : (createForm.value.template_id || undefined),
      git_url: createForm.value.git_url || undefined,
      git_branch: createForm.value.git_branch || undefined,
      git_username: createForm.value.git_username || undefined,
      git_password: createForm.value.git_password || undefined,
      start_command: createForm.value.git_url ? (createForm.value.start_command || undefined) : undefined,
    })
    showCreateDialog.value = false
    createForm.value = { name: '', template_id: '', git_url: '', git_branch: '', git_username: '', git_password: '', start_command: '' }
  } catch {}
  finally { creating.value = false }
}

function statusTone(status: string): 'success' | 'muted' | 'warning' | 'danger' {
  return ({ running: 'success', stopped: 'muted', building: 'warning', error: 'danger' } as const)[status as 'running'] ?? 'muted'
}
function statusLabel(status: string) {
  return ({ running: '运行中', stopped: '已停止', building: '构建中', error: '异常' } as const)[status as 'running'] ?? status
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">我的站点</h1>
        <p class="mt-1 text-sm text-muted-foreground">创建、启停与预览托管站点</p>
      </div>
      <Button @click="showCreateDialog = true">
        <Plus class="size-4" />
        创建站点
      </Button>
    </div>

    <div class="flex flex-col gap-3 rounded-xl border bg-card p-3 md:flex-row md:items-end">
      <div class="flex w-full flex-col gap-1.5 md:w-48">
        <Label>状态</Label>
        <Select v-model="filter.status">
          <SelectTrigger>
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="running">运行中</SelectItem>
              <SelectItem value="stopped">已停止</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div class="flex w-full flex-1 flex-col gap-1.5 md:max-w-xs">
        <Label>搜索</Label>
        <Input v-model="filter.search" placeholder="站点名称或 ID…" />
      </div>
    </div>

    <div v-if="filteredSites.length" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card v-for="site in filteredSites" :key="site.site_id" class="flex flex-col shadow-none">
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <CardTitle class="flex items-center gap-2 text-base font-semibold">
            <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Globe class="size-4" />
            </div>
            <span class="truncate">{{ site.name }}</span>
          </CardTitle>
          <span class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <span class="status-dot" :data-tone="statusTone(site.status)" :data-pulse="site.status === 'building'" />
            {{ statusLabel(site.status) }}
          </span>
        </CardHeader>
        <CardContent class="flex-1 space-y-1.5 font-mono-data text-xs">
          <div class="flex justify-between gap-2">
            <span class="text-muted-foreground">ID</span>
            <span class="truncate">{{ site.site_id }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-muted-foreground">端口</span>
            <span>{{ site.port || '分配中' }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-muted-foreground">创建</span>
            <span>{{ formatDate(site.created_at) }}</span>
          </div>
        </CardContent>
        <CardFooter class="justify-between gap-1 border-t pt-3">
          <div class="flex gap-1">
            <Button size="sm" :variant="site.status === 'running' ? 'destructive' : 'default'" @click="toggleSiteStatus(site)">
              <component :is="site.status === 'running' ? PowerOff : Power" class="size-3.5" />
              {{ site.status === 'running' ? '停止' : '启动' }}
            </Button>
            <Button size="sm" variant="outline" @click="previewSite(site)" :disabled="site.status !== 'running'">
              <MonitorPlay class="size-3.5" />
              预览
            </Button>
            <Button size="sm" variant="outline" @click="openFileBrowser(site)">
              <FolderTree class="size-3.5" />
              文件
            </Button>
          </div>
          <div class="flex gap-1">
            <Button size="sm" variant="outline" @click="editSite(site)">
              <Settings class="size-3.5" />
            </Button>
            <Button size="sm" variant="outline" class="text-muted-foreground hover:text-destructive" @click="deleteSite(site)">
              <Trash2 class="size-3.5" />
            </Button>
          </div>
        </CardFooter>
      </Card>
    </div>

    <div v-else class="rounded-xl border border-dashed py-20 text-center">
      <Globe class="mx-auto size-8 text-muted-foreground/40" />
      <p class="mt-3 text-sm text-muted-foreground">还没有站点，点击「创建站点」开始</p>
    </div>

    <Dialog :open="showCreateDialog" @update:open="showCreateDialog = $event">
      <DialogContent class="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>创建新站点</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="name" class="text-right">站点名称</Label>
            <Input id="name" v-model="createForm.name" class="col-span-3" placeholder="例如：我的博客" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_url" class="text-right">Git 仓库</Label>
            <Input id="git_url" v-model="createForm.git_url" class="col-span-3" placeholder="https://github.com/you/repo.git" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_username" class="text-right">Git 用户名</Label>
            <Input id="git_username" v-model="createForm.git_username" class="col-span-3" placeholder="选填，私有仓库可用" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_branch" class="text-right">Git 分支</Label>
            <Input id="git_branch" v-model="createForm.git_branch" class="col-span-3" placeholder="选填，默认拉取仓库默认分支" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_password" class="text-right">Git 密码</Label>
            <Input id="git_password" v-model="createForm.git_password" type="password" class="col-span-3" placeholder="选填，可填写 PAT / 访问令牌" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="template" class="text-right">初始模板</Label>
            <Select v-model="createForm.template_id">
              <SelectTrigger class="col-span-3" :disabled="!!createForm.git_url">
                <SelectValue placeholder="空白模板" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="blank">空白模板</SelectItem>
                  <SelectItem value="blog">博客模板</SelectItem>
                  <SelectItem value="dashboard">仪表盘模板</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div class="grid grid-cols-4 items-start gap-4">
            <Label for="start_command" class="pt-2 text-right">启动命令</Label>
            <div class="col-span-3 space-y-2">
              <textarea
                id="start_command"
                v-model="createForm.start_command"
                rows="3"
                class="flex min-h-[88px] w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
                :disabled="!createForm.git_url"
                placeholder="例如：pnpm install && pnpm dev --host 0.0.0.0 --port $PORT"
              />
              <p class="text-xs text-muted-foreground">
                仅 Git 项目可选填。命令会在站点根目录执行，并自动注入 <code class="rounded bg-muted px-1 py-0.5 font-mono-data text-[11px]">PORT</code>、<code class="rounded bg-muted px-1 py-0.5 font-mono-data text-[11px]">HOST</code>、<code class="rounded bg-muted px-1 py-0.5 font-mono-data text-[11px]">SITE_ROOT</code> 等环境变量。
              </p>
            </div>
          </div>
          <p class="pl-[calc(25%+1rem)] text-xs text-muted-foreground">
            填写 Git 仓库地址后会优先从仓库拉取代码，模板选项将被忽略。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">取消</Button>
          <Button type="submit" @click="createSite" :disabled="creating">
            {{ creating ? '创建中…' : '确认创建' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <SiteFileBrowserDialog
      v-model:open="fileBrowserOpen"
      :site-id="fileBrowserSite?.site_id || ''"
      :site-name="fileBrowserSite?.name || ''"
    />
  </div>
</template>
