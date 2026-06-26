<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { templatesAPI } from '@/api/templates'
import type { Template } from '@/types/models'
import { Card, CardHeader, CardTitle, CardContent, CardDescription, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Users, Star, LayoutTemplate } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const router = useRouter()

const activeCategory = ref('all')
const categories = [
  { id: 'all', label: '全部' },
  { id: 'blog', label: '博客' },
  { id: 'dashboard', label: '仪表盘' },
  { id: 'ecommerce', label: '电商' },
  { id: 'landing', label: '落地页' },
]

const templates = ref<Template[]>([])
const loading = ref(false)

const showUseDialog = ref(false)
const selectedTemplate = ref<Template | null>(null)
const siteName = ref('')

onMounted(() => {
  fetchTemplates()
})

const fetchTemplates = async () => {
  loading.value = true
  try {
    const response = await templatesAPI.list(
      activeCategory.value === 'all' ? undefined : { category: activeCategory.value }
    )
    if (response) {
      templates.value = response.templates || []
    }
  } finally {
    loading.value = false
  }
}

const useTemplate = (template: Template) => {
  selectedTemplate.value = template
  siteName.value = ''
  showUseDialog.value = true
}

const createFromTemplate = async () => {
  if (!siteName.value) {
    toast.warning('请输入站点名称')
    return
  }
  if (!selectedTemplate.value) return

  try {
    const response = await templatesAPI.createSiteFromTemplate({
      template_id: selectedTemplate.value.id,
      site_name: siteName.value,
    })
    showUseDialog.value = false
    toast.success('站点已创建')
    router.push({ name: 'SiteEditor', params: { id: response.site.site_id } })
  } catch (error) {
    toast.error('创建失败，请稍后重试')
  }
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">模板市场</h1>
      <p class="mt-1 text-sm text-muted-foreground">从模板一键创建站点，开箱即用</p>
    </div>

    <!-- Category tabs -->
    <div class="flex gap-1 overflow-x-auto border-b">
      <button
        v-for="cat in categories"
        :key="cat.id"
        @click="activeCategory = cat.id; fetchTemplates()"
        class="-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors"
        :class="activeCategory === cat.id
          ? 'border-primary text-primary'
          : 'border-transparent text-muted-foreground hover:text-foreground'"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- Template grid -->
    <div v-if="templates.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <Card
        v-for="template in templates"
        :key="template.id"
        class="flex flex-col overflow-hidden shadow-none transition-all hover:border-primary/40 hover:shadow-sm"
      >
        <div class="aspect-video w-full overflow-hidden bg-muted">
          <img v-if="template.thumbnail_url" :src="template.thumbnail_url" :alt="template.name" class="h-full w-full object-cover" />
          <div v-else class="flex h-full w-full items-center justify-center text-muted-foreground/40">
            <LayoutTemplate class="size-8" />
          </div>
        </div>
        <CardHeader class="gap-1 p-4">
          <CardTitle class="text-base">{{ template.name }}</CardTitle>
          <CardDescription class="line-clamp-2 h-10">{{ template.description }}</CardDescription>
        </CardHeader>
        <CardContent class="flex flex-1 items-end justify-between p-4 pt-0 text-sm">
          <div class="flex items-center gap-1 font-medium text-warning">
            <Star class="size-4 fill-current" />
            <span class="font-mono-data">{{ template.rating }}</span>
          </div>
          <div class="flex items-center gap-1 text-muted-foreground">
            <Users class="size-4" />
            <span class="font-mono-data">{{ template.usage_count }}</span>
          </div>
        </CardContent>
        <CardFooter class="p-4 pt-0">
          <Button class="w-full" variant="outline" @click="useTemplate(template)">使用此模板</Button>
        </CardFooter>
      </Card>
    </div>

    <div v-else class="rounded-xl border border-dashed py-20 text-center">
      <LayoutTemplate class="mx-auto size-8 text-muted-foreground/40" />
      <p class="mt-3 text-sm text-muted-foreground">该分类下暂无模板</p>
    </div>

    <!-- Create dialog -->
    <Dialog :open="showUseDialog" @update:open="showUseDialog = $event">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>从模板创建站点</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="siteName" class="text-right">站点名称</Label>
            <Input id="siteName" v-model="siteName" class="col-span-3" placeholder="例如：我的博客" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showUseDialog = false">取消</Button>
          <Button @click="createFromTemplate">创建站点</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
