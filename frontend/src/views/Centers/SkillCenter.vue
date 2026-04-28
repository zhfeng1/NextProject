<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { skillsAPI } from '@/api/skills'
import { sitesAPI } from '@/api/sites'
import type { Site, Skill } from '@/types/models'

const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const skills = ref<Skill[]>([])
const sites = ref<Site[]>([])
const message = ref('')

const editorOpen = ref(false)
const importOpen = ref(false)
const editingSkillId = ref('')

const form = reactive({
  name: '',
  description: '',
  scope: 'global' as 'global' | 'site',
  content: '',
  triggers: '',
  enabled: true,
})

const importMode = ref<'markdown' | 'skills_sh'>('skills_sh')
const importForm = reactive({
  markdown: '',
  url: '',
})
const bindSiteId = reactive<Record<string, string>>({})

const editingSkill = computed(() => skills.value.find(skill => skill.id === editingSkillId.value) || null)

function resetForm() {
  editingSkillId.value = ''
  form.name = ''
  form.description = ''
  form.scope = 'global'
  form.content = ''
  form.triggers = ''
  form.enabled = true
}

function openCreate() {
  resetForm()
  editorOpen.value = true
}

function openEdit(skill: Skill) {
  editingSkillId.value = skill.id
  form.name = skill.name
  form.description = skill.description
  form.scope = skill.scope
  form.content = skill.content
  form.triggers = (skill.triggers || []).join(', ')
  form.enabled = skill.enabled
  editorOpen.value = true
}

async function loadData() {
  loading.value = true
  try {
    const [skillsRes, sitesRes] = await Promise.all([skillsAPI.list(), sitesAPI.list()])
    skills.value = skillsRes.skills || []
    sites.value = sitesRes.sites || []
  } finally {
    loading.value = false
  }
}

async function saveSkill() {
  saving.value = true
  message.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      scope: form.scope,
      content: form.content,
      enabled: form.enabled,
      triggers: form.triggers.split(',').map(item => item.trim()).filter(Boolean),
    }
    if (editingSkillId.value) {
      const res = await skillsAPI.update(editingSkillId.value, payload)
      skills.value = skills.value.map(item => item.id === editingSkillId.value ? res.skill : item)
      message.value = 'Skill 已更新'
    } else {
      const res = await skillsAPI.create(payload)
      skills.value.unshift(res.skill)
      message.value = 'Skill 已创建'
    }
    editorOpen.value = false
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}

async function removeSkill(skill: Skill) {
  if (!window.confirm(`确认删除 Skill「${skill.name}」吗？`)) return
  try {
    await skillsAPI.remove(skill.id)
    skills.value = skills.value.filter(item => item.id !== skill.id)
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '删除失败'
  }
}

async function copySkill(skill: Skill) {
  try {
    await navigator.clipboard.writeText(skill.content)
    message.value = `已复制 ${skill.name} Markdown 内容`
  } catch {
    message.value = '复制失败，请手动选择内容'
  }
}

async function importSkill() {
  importing.value = true
  message.value = ''
  try {
    const res = importMode.value === 'skills_sh'
      ? await skillsAPI.importSkillsSh(importForm.url.trim())
      : await skillsAPI.importMarkdown({ markdown: importForm.markdown })
    skills.value.unshift(res.skill)
    importOpen.value = false
    importForm.markdown = ''
    importForm.url = ''
    message.value = `已导入 ${res.skill.name}`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '导入失败'
  } finally {
    importing.value = false
  }
}

async function toggleBinding(skill: Skill, bind: boolean) {
  const siteId = bindSiteId[skill.id]
  if (!siteId) return
  try {
    const res = await skillsAPI.bindSite(skill.id, siteId, bind)
    skills.value = skills.value.map(item => item.id === skill.id ? res.skill : item)
    message.value = bind ? '站点绑定已更新' : '站点解绑已更新'
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '绑定失败'
  }
}

onMounted(loadData)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">Skill 中心</h1>
        <p class="mt-2 text-sm text-muted-foreground">
          管理项目内统一 Skill 包，支持手工维护、Markdown 导入，以及从 skills.sh 链接直接归一化导入。
        </p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" @click="importOpen = true">导入 Skill</Button>
        <Button @click="openCreate">新建 Skill</Button>
      </div>
    </div>

    <div v-if="message" class="rounded-lg border bg-background px-4 py-3 text-sm">
      {{ message }}
    </div>

    <div v-if="loading" class="rounded-lg border bg-background px-4 py-6 text-sm text-muted-foreground">
      正在加载 Skill 列表...
    </div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <Card v-for="skill in skills" :key="skill.id" class="border-border/70">
        <CardHeader class="space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div>
              <CardTitle class="text-lg">{{ skill.name }}</CardTitle>
              <CardDescription class="mt-1">{{ skill.description || '暂无描述' }}</CardDescription>
            </div>
            <Badge :variant="skill.enabled ? 'default' : 'secondary'">
              {{ skill.enabled ? '启用中' : '已停用' }}
            </Badge>
          </div>
          <div class="flex flex-wrap gap-2 text-xs">
            <Badge variant="outline">{{ skill.scope === 'site' ? '站点级' : '全局' }}</Badge>
            <Badge variant="outline">{{ skill.source_type }}</Badge>
            <Badge v-for="trigger in skill.triggers" :key="trigger" variant="secondary">{{ trigger }}</Badge>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <pre class="max-h-44 overflow-y-auto rounded-md bg-muted/30 p-3 text-xs leading-relaxed whitespace-pre-wrap">{{ skill.content }}</pre>
          <div v-if="skill.source_url" class="text-xs text-muted-foreground break-all">
            来源: {{ skill.source_url }}
          </div>
          <div class="space-y-2 rounded-md border border-dashed border-border/70 p-3">
            <div class="text-sm font-medium">绑定站点</div>
            <div class="flex flex-wrap gap-2">
              <Badge v-for="siteId in skill.bound_site_ids" :key="siteId" variant="secondary">{{ siteId }}</Badge>
              <span v-if="!skill.bound_site_ids.length" class="text-xs text-muted-foreground">尚未绑定站点</span>
            </div>
            <div class="flex gap-2">
              <select v-model="bindSiteId[skill.id]" class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm">
                <option value="">选择站点</option>
                <option v-for="site in sites" :key="site.site_id" :value="site.site_id">{{ site.name }} ({{ site.site_id }})</option>
              </select>
              <Button variant="outline" @click="toggleBinding(skill, true)">绑定</Button>
              <Button variant="outline" @click="toggleBinding(skill, false)">解绑</Button>
            </div>
          </div>
          <div class="flex gap-2">
            <Button class="flex-1" variant="outline" @click="openEdit(skill)">编辑</Button>
            <Button class="flex-1" variant="outline" @click="copySkill(skill)">导出 Markdown</Button>
            <Button variant="destructive" @click="removeSkill(skill)">删除</Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <Dialog :open="editorOpen" @update:open="editorOpen = $event">
      <DialogContent class="sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>{{ editingSkill ? '编辑 Skill' : '新建 Skill' }}</DialogTitle>
        </DialogHeader>
        <div class="grid gap-4 py-2">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="skill-name" class="text-right">名称</Label>
            <Input id="skill-name" v-model="form.name" class="col-span-3" placeholder="例如：Vue Best Practices" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="skill-desc" class="text-right">描述</Label>
            <Input id="skill-desc" v-model="form.description" class="col-span-3" placeholder="一句话描述这个 Skill 的用途" />
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="skill-scope" class="text-right">范围</Label>
            <select id="skill-scope" v-model="form.scope" class="col-span-3 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm">
              <option value="global">全局</option>
              <option value="site">站点级</option>
            </select>
          </div>
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="skill-triggers" class="text-right">触发词</Label>
            <Input id="skill-triggers" v-model="form.triggers" class="col-span-3" placeholder="逗号分隔，如：vue, composition-api" />
          </div>
          <div class="grid grid-cols-4 items-start gap-4">
            <Label for="skill-content" class="pt-2 text-right">内容</Label>
            <textarea
              id="skill-content"
              v-model="form.content"
              class="col-span-3 min-h-[260px] rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              placeholder="# Skill 标题"
            />
          </div>
          <label class="inline-flex items-center gap-2 text-sm">
            <input v-model="form.enabled" type="checkbox" class="h-4 w-4 accent-primary" />
            保存后立即启用
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="editorOpen = false">取消</Button>
          <Button :disabled="saving || !form.content.trim()" @click="saveSkill">
            {{ saving ? '保存中...' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog :open="importOpen" @update:open="importOpen = $event">
      <DialogContent class="sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>导入 Skill</DialogTitle>
        </DialogHeader>
        <div class="space-y-4 py-2">
          <div class="flex gap-2">
            <Button :variant="importMode === 'skills_sh' ? 'default' : 'outline'" @click="importMode = 'skills_sh'">从 skills.sh 导入</Button>
            <Button :variant="importMode === 'markdown' ? 'default' : 'outline'" @click="importMode = 'markdown'">从 Markdown 导入</Button>
          </div>
          <div v-if="importMode === 'skills_sh'" class="space-y-2">
            <Label for="skills-url">skills.sh 详情页 URL</Label>
            <Input id="skills-url" v-model="importForm.url" placeholder="https://skills.sh/hyf0/vue-skills/vue-best-practices" />
          </div>
          <div v-else class="space-y-2">
            <Label for="skills-markdown">Markdown 内容</Label>
            <textarea
              id="skills-markdown"
              v-model="importForm.markdown"
              class="min-h-[260px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              placeholder="# Skill 标题"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="importOpen = false">取消</Button>
          <Button :disabled="importing || (importMode === 'skills_sh' ? !importForm.url.trim() : !importForm.markdown.trim())" @click="importSkill">
            {{ importing ? '导入中...' : '导入' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
