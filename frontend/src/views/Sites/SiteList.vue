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
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-3xl font-bold tracking-tight">我的站点</h1>
      <Button @click="showCreateDialog = true" class="flex gap-2">
        <Plus class="w-4 h-4" />
        创建站点
      </Button>
    </div>

    <!-- 筛选器 -->
    <Card class="p-4 shadow-none">
      <div class="flex flex-col md:flex-row gap-4 items-end">
        <div class="space-y-2 flex-col flex select-none w-full md:w-48">
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
        <div class="space-y-2 flex-col flex w-full md:w-64">
          <Label>搜索</Label>
          <Input v-model="filter.search" placeholder="站点名称或 ID..." />
        </div>
      </div>
    </Card>

    <!-- 站点卡片 -->
    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card v-for="site in filteredSites" :key="site.site_id" class="flex flex-col">
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <CardTitle class="text-lg font-bold flex items-center gap-2">
            <Globe class="w-5 h-5 text-muted-foreground" />
            {{ site.name }}
          </CardTitle>
          <span :class="site.status === 'running' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'" class="px-2 py-1 text-xs rounded font-medium">
            {{ site.status === 'running' ? '运行中' : '已停止' }}
          </span>
        </CardHeader>
        <CardContent class="flex-1 text-sm text-muted-foreground space-y-2">
          <div class="flex justify-between">
            <span class="font-medium text-foreground">ID:</span>
            <span>{{ site.site_id }}</span>
          </div>
          <div class="flex justify-between">
            <span class="font-medium text-foreground">端口:</span>
            <span>{{ site.port || '分配中' }}</span>
          </div>
          <div class="flex justify-between">
            <span class="font-medium text-foreground">创建时间:</span>
            <span>{{ formatDate(site.created_at) }}</span>
          </div>
        </CardContent>
        <CardFooter class="flex gap-2 justify-between">
          <div class="flex gap-2">
            <Button size="sm" :variant="site.status === 'running' ? 'destructive' : 'default'" @click="toggleSiteStatus(site)">
              <PowerOff v-if="site.status === 'running'" class="w-4 h-4 mr-1" />
              <Power v-else class="w-4 h-4 mr-1" />
              {{ site.status === 'running' ? '停止' : '启动' }}
            </Button>
            <Button size="sm" variant="secondary" @click="previewSite(site)" :disabled="site.status !== 'running'">
              <MonitorPlay class="w-4 h-4 mr-1" />
              预览
            </Button>
            <Button size="sm" variant="outline" @click="openFileBrowser(site)">
              <FolderTree class="w-4 h-4 mr-1" />
              文件
            </Button>
          </div>
          <div class="flex gap-2">
            <Button size="sm" variant="outline" @click="editSite(site)">
              <Settings class="w-4 h-4" />
            </Button>
            <Button size="sm" variant="outline" class="text-red-500 hover:text-red-600" @click="deleteSite(site)">
              <Trash2 class="w-4 h-4" />
            </Button>
          </div>
        </CardFooter>
      </Card>
    </div>

    <!-- 创建对话框 -->
    <Dialog :open="showCreateDialog" @update:open="showCreateDialog = $event">
      <DialogContent class="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>创建新站点</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="name" class="text-right">站点名称</Label>
            <Input id="name" v-model="createForm.name" class="col-span-3" placeholder="例如: 我的博客" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_url" class="text-right">Git 仓库</Label>
            <Input
              id="git_url"
              v-model="createForm.git_url"
              class="col-span-3"
              placeholder="https://github.com/you/repo.git"
            />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_username" class="text-right">Git 用户名</Label>
            <Input
              id="git_username"
              v-model="createForm.git_username"
              class="col-span-3"
              placeholder="选填，私有仓库可用"
            />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_branch" class="text-right">Git 分支</Label>
            <Input
              id="git_branch"
              v-model="createForm.git_branch"
              class="col-span-3"
              placeholder="选填，默认拉取仓库默认分支"
            />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="git_password" class="text-right">Git 密码</Label>
            <Input
              id="git_password"
              v-model="createForm.git_password"
              type="password"
              class="col-span-3"
              placeholder="选填，可填写 PAT / 访问令牌"
            />
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
                class="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!createForm.git_url"
                placeholder="例如：pnpm install && pnpm dev --host 0.0.0.0 --port $PORT"
              />
              <p class="text-xs text-muted-foreground">
                仅 Git 项目可选填。命令会在站点根目录执行，并自动注入 <code>PORT</code>、<code>HOST</code>、<code>SITE_ROOT</code> 等环境变量。
              </p>
            </div>
          </div>
          <p class="text-xs text-muted-foreground pl-[calc(25%+1rem)]">
            填写 Git 仓库地址后，会优先从仓库拉取代码；模板选项将被忽略。可选填分支名和启动命令，后续启动和重启都会按该配置执行。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showCreateDialog = false">取消</Button>
          <Button type="submit" @click="createSite" :disabled="creating">
            {{ creating ? '创建中...' : '确认创建' }}
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
