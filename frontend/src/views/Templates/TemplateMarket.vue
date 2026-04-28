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
import { Users, Star } from 'lucide-vue-next'
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
    router.push({ name: 'SiteEditor', params: { id: response.site.site_id } })
  } catch (error) {
    toast.error('创建失败，请稍后重试')
  }
}
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold tracking-tight">模板市场</h1>

    <!-- 类别 Tab -->
    <div class="flex gap-2 border-b pb-2 overflow-x-auto">
      <button 
        v-for="cat in categories" 
        :key="cat.id"
        @click="activeCategory = cat.id; fetchTemplates()"
        class="px-4 py-2 text-sm font-medium transition-colors hover:text-primary whitespace-nowrap"
        :class="activeCategory === cat.id ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground border-b-2 border-transparent'"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- 模板卡片网格 -->
    <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <Card v-for="template in templates" :key="template.id" class="flex flex-col overflow-hidden hover:shadow-md transition-shadow">
        <div class="aspect-video w-full overflow-hidden bg-muted">
          <img v-if="template.thumbnail_url" :src="template.thumbnail_url" :alt="template.name" class="w-full h-full object-cover" />
          <div v-else class="w-full h-full flex items-center justify-center text-muted-foreground">暂无预览</div>
        </div>
        <CardHeader class="flex flex-col gap-1 p-4">
          <CardTitle class="text-base">{{ template.name }}</CardTitle>
          <CardDescription class="line-clamp-2 h-10">{{ template.description }}</CardDescription>
        </CardHeader>
        <CardContent class="p-4 pt-0 flex-1 flex flex-col justify-end">
          <div class="flex items-center justify-between mt-auto">
            <div class="flex items-center text-sm text-yellow-500 font-medium space-x-1">
              <Star class="w-4 h-4 fill-current" />
              <span>{{ template.rating }}</span>
            </div>
            <div class="flex items-center text-sm text-muted-foreground space-x-1">
              <Users class="w-4 h-4" />
              <span>{{ template.usage_count }}</span>
            </div>
          </div>
        </CardContent>
        <CardFooter class="p-4 pt-0">
          <Button class="w-full" @click="useTemplate(template)">使用此模板</Button>
        </CardFooter>
      </Card>
    </div>

    <!-- 创建弹层 -->
    <Dialog :open="showUseDialog" @update:open="showUseDialog = $event">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>从模板创建站点</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="siteName" class="text-right">站点名称</Label>
            <Input id="siteName" v-model="siteName" class="col-span-3" placeholder="例如: 我的博客" />
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
