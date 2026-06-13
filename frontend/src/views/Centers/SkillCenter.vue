<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, reactive, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { skillsAPI } from '@/api/skills'
import { projectsAPI } from '@/api/projects'
import type { Project, Skill } from '@/types/models'

const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const skills = ref<Skill[]>([])
const projects = ref<Project[]>([])
const message = ref('')
const filters = ref({ scope_type: '', project_id: '', site_id: '' })

const editorOpen = ref(false)
const importOpen = ref(false)
const editingSkillId = ref('')

const form = reactive({
  name: '',
  description: '',
  scope_type: 'global',
  project_id: '',
  site_id: '',
  content: '',
  triggers: '',
  enabled: true,
})

const importMode = ref<'markdown' | 'skills_sh'>('skills_sh')
const importForm = reactive({ markdown: '', url: '' })

const repos = computed(() => {
  const project = projects.value.find(item => item.id === filters.value.project_id || item.id === form.project_id)
  return project?.repos || projects.value.flatMap(item => item.repos || [])
})

const editingSkill = computed(() => skills.value.find(skill => skill.id === editingSkillId.value) || null)

function resetForm() {
  editingSkillId.value = ''
  form.name = ''
  form.description = ''
  form.scope_type = 'global'
  form.project_id = ''
  form.site_id = ''
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
  form.scope_type = skill.scope_type || 'global'
  form.project_id = skill.project_id || ''
  form.site_id = skill.site_id || ''
  form.content = skill.content
  form.triggers = (skill.triggers || []).join(', ')
  form.enabled = skill.enabled
  editorOpen.value = true
}

async function loadData() {
  loading.value = true
  try {
    const [skillsRes, projectRes] = await Promise.all([
      skillsAPI.list({
        scope_type: filters.value.scope_type || undefined,
        project_id: filters.value.project_id || undefined,
        site_id: filters.value.site_id || undefined,
      }),
      projectsAPI.list(),
    ])
    skills.value = skillsRes.skills || []
    projects.value = projectRes.projects || []
  } finally {
    loading.value = false
  }
}

function buildScopePayload() {
  return {
    scope_type: form.scope_type,
    project_id: form.scope_type === 'project' ? form.project_id : '',
    site_id: form.scope_type === 'repo' ? form.site_id : '',
  }
}

async function saveSkill() {
  saving.value = true
  message.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      ...buildScopePayload(),
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
    const scopePayload = buildScopePayload()
    const res = importMode.value === 'skills_sh'
      ? await skillsAPI.importSkillsSh(importForm.url.trim(), true)
      : await skillsAPI.importMarkdown({ markdown: importForm.markdown, ...scopePayload })
    if (importMode.value === 'skills_sh' && (scopePayload.scope_type !== 'global' || scopePayload.project_id || scopePayload.site_id)) {
      const updated = await skillsAPI.update(res.skill.id, scopePayload)
      skills.value.unshift(updated.skill)
    } else {
      skills.value.unshift(res.skill)
    }
    importOpen.value = false
    importForm.markdown = ''
    importForm.url = ''
    message.value = `已导入 Skill`
  } catch (error: any) {
    message.value = error?.response?.data?.detail || '导入失败'
  } finally {
    importing.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">Skill 中心</h1>
        <p class="mt-2 text-sm text-muted-foreground">按全局、项目、仓库维护任务可附带的 Skill。</p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" @click="importOpen = true">导入 Skill</Button>
        <Button @click="openCreate">新建 Skill</Button>
      </div>
    </div>

    <div class="grid gap-3 rounded-lg border bg-background p-3 md:grid-cols-4">
      <select v-model="filters.scope_type" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadData">
        <option value="">全部作用域</option>
        <option value="global">全局</option>
        <option value="project">项目级</option>
        <option value="repo">仓库级</option>
      </select>
      <select v-model="filters.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="filters.site_id = ''; loadData()">
        <option value="">全部项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
      </select>
      <select v-model="filters.site_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" @change="loadData">
        <option value="">全部仓库</option>
        <option v-for="repo in repos" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
      </select>
      <Button variant="outline" @click="filters = { scope_type: '', project_id: '', site_id: '' }; loadData()">清空筛选</Button>
    </div>

    <div v-if="message" class="rounded-lg border bg-background px-4 py-3 text-sm">{{ message }}</div>
    <div v-if="loading" class="rounded-lg border bg-background px-4 py-6 text-sm text-muted-foreground">正在加载 Skill 列表...</div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <Card v-for="skill in skills" :key="skill.id" class="border-border/70">
        <CardHeader class="space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div>
              <CardTitle class="text-lg">{{ skill.name }}</CardTitle>
              <CardDescription class="mt-1">{{ skill.description || '暂无描述' }}</CardDescription>
            </div>
            <Badge :variant="skill.enabled ? 'default' : 'secondary'">{{ skill.enabled ? '启用中' : '已停用' }}</Badge>
          </div>
          <div class="flex flex-wrap gap-2 text-xs">
            <Badge variant="outline">{{ skill.scope_type }}</Badge>
            <Badge variant="outline">{{ skill.source_type }}</Badge>
            <Badge v-for="trigger in skill.triggers" :key="trigger" variant="secondary">{{ trigger }}</Badge>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <pre class="max-h-44 overflow-y-auto rounded-md bg-muted/30 p-3 text-xs leading-relaxed whitespace-pre-wrap">{{ skill.content }}</pre>
          <div v-if="skill.source_url" class="text-xs text-muted-foreground break-all">来源: {{ skill.source_url }}</div>
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
          <div class="grid gap-3 md:grid-cols-2">
            <div class="space-y-1.5">
              <Label>名称</Label>
              <Input v-model="form.name" placeholder="例如：Vue Best Practices" />
            </div>
            <div class="space-y-1.5">
              <Label>描述</Label>
              <Input v-model="form.description" placeholder="一句话描述用途" />
            </div>
          </div>
          <div class="grid gap-3 md:grid-cols-3">
            <select v-model="form.scope_type" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm">
              <option value="global">全局</option>
              <option value="project">项目级</option>
              <option value="repo">仓库级</option>
            </select>
            <select v-model="form.project_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" :disabled="form.scope_type !== 'project'">
              <option value="">选择项目</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
            <select v-model="form.site_id" class="h-9 rounded-md border border-input bg-transparent px-3 text-sm" :disabled="form.scope_type !== 'repo'">
              <option value="">选择仓库</option>
              <option v-for="repo in projects.flatMap(item => item.repos || [])" :key="repo.site_id" :value="repo.site_id">{{ repo.name }}</option>
            </select>
          </div>
          <div class="space-y-1.5">
            <Label>触发词</Label>
            <Input v-model="form.triggers" placeholder="逗号分隔，如：vue, composition-api" />
          </div>
          <div class="space-y-1.5">
            <Label>内容</Label>
            <textarea
              v-model="form.content"
              class="min-h-[260px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
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
          <Button :disabled="saving || !form.content.trim()" @click="saveSkill">{{ saving ? '保存中...' : '保存' }}</Button>
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
            <Label>skills.sh 详情页 URL</Label>
            <Input v-model="importForm.url" placeholder="https://skills.sh/..." />
          </div>
          <div v-else class="space-y-2">
            <Label>Markdown 内容</Label>
            <textarea v-model="importForm.markdown" class="min-h-[260px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring" placeholder="# Skill 标题" />
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
