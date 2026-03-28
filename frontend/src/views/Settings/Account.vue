<script setup lang="ts">
// @ts-nocheck
import { ref, reactive, onMounted } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useAuthStore } from '@/stores/auth'
import { authAPI } from '@/api/auth'
import { providersAPI } from '@/api/providers'
import type { LLMProvider } from '@/api/providers'

const authStore = useAuthStore()

// ── 基本信息 ──
const profileForm = reactive({ name: '' })
const profileLoading = ref(false)
const profileMsg = ref('')

// ── 修改邮箱 ──
const emailForm = reactive({ new_email: '', current_password: '' })
const emailLoading = ref(false)
const emailMsg = ref('')

// ── 修改密码 ──
const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' })
const passwordLoading = ref(false)
const passwordMsg = ref('')

// ── Provider 配置 ──
interface ProviderUI extends LLMProvider {
  availableModels: string[]
  fetching: boolean
  saving: boolean
  msg: string
  manualModel: string
  verifying: string
}

const providers = ref<ProviderUI[]>([])

function toUI(p: LLMProvider): ProviderUI {
  return { ...p, availableModels: [...(p.models || [])], fetching: false, saving: false, msg: '', manualModel: '', verifying: '' }
}

async function loadProviders() {
  try {
    const res = await providersAPI.list()
    providers.value = (res.providers || []).map(toUI)
  } catch {}
}

async function addProvider() {
  try {
    const res = await providersAPI.create({ name: '新 Provider', base_url: 'https://api.openai.com/v1', format: 'responses' })
    providers.value.push(toUI(res.provider))
  } catch {}
}

async function saveProvider(p: ProviderUI) {
  p.saving = true
  p.msg = ''
  try {
    const res = await providersAPI.update(p.id, {
      name: p.name, base_url: p.base_url, api_key: p.api_key,
      models: p.models, format: p.format, is_default: p.is_default,
    })
    Object.assign(p, toUI(res.provider))
    p.msg = '已保存'
  } catch (e: any) {
    p.msg = e?.response?.data?.detail || '保存失败'
  } finally {
    p.saving = false
  }
}

async function removeProvider(p: ProviderUI) {
  try {
    await providersAPI.remove(p.id)
    providers.value = providers.value.filter(x => x.id !== p.id)
  } catch {}
}

async function fetchModels(p: ProviderUI) {
  if (!p.base_url) return
  p.fetching = true
  p.msg = ''
  try {
    const res = await providersAPI.fetchModels({ base_url: p.base_url, api_key: p.api_key })
    if (res.ok && res.models?.length) {
      p.availableModels = res.models
      p.msg = `获取到 ${res.models.length} 个模型`
    } else {
      p.msg = res.error || '未获取到模型，可手动输入'
    }
  } catch (e: any) {
    p.msg = '拉取失败，可手动输入'
  } finally {
    p.fetching = false
  }
}

function toggleModel(p: ProviderUI, model: string) {
  const idx = p.models.indexOf(model)
  if (idx >= 0) p.models.splice(idx, 1)
  else p.models.push(model)
}

function addManualModel(p: ProviderUI) {
  const m = p.manualModel.trim()
  if (!m) return
  if (!p.availableModels.includes(m)) p.availableModels.push(m)
  if (!p.models.includes(m)) p.models.push(m)
  p.manualModel = ''
}

async function verifyModel(p: ProviderUI, model: string) {
  p.verifying = model
  p.msg = ''
  try {
    const res = await providersAPI.verifyModel({ provider_id: p.id, model })
    p.msg = res.ok ? `${model}: 连通正常` : `${model}: ${res.error || '验证失败'}`
  } catch (e: any) {
    p.msg = `${model}: ${e?.response?.data?.detail || '验证失败'}`
  } finally {
    p.verifying = ''
  }
}

// ── 初始化 ──
onMounted(async () => {
  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {}
  }
  profileForm.name = authStore.user?.name || ''
  await loadProviders()
})

async function saveProfile() {
  profileLoading.value = true
  profileMsg.value = ''
  try {
    const res = await authAPI.updateProfile({ name: profileForm.name }) as any
    if (res.user) authStore.user = res.user
    profileMsg.value = '保存成功'
  } catch (e: any) {
    profileMsg.value = e?.response?.data?.detail || '保存失败'
  } finally {
    profileLoading.value = false
  }
}

async function saveEmail() {
  emailLoading.value = true
  emailMsg.value = ''
  try {
    const res = await authAPI.updateEmail({ new_email: emailForm.new_email, current_password: emailForm.current_password }) as any
    if (res.user) authStore.user = res.user
    emailMsg.value = '邮箱已更新'
    emailForm.new_email = ''
    emailForm.current_password = ''
  } catch (e: any) {
    emailMsg.value = e?.response?.data?.detail || '更新失败'
  } finally {
    emailLoading.value = false
  }
}

async function savePassword() {
  passwordMsg.value = ''
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    passwordMsg.value = '两次密码不一致'
    return
  }
  passwordLoading.value = true
  try {
    await authAPI.updatePassword({ current_password: passwordForm.current_password, new_password: passwordForm.new_password })
    passwordMsg.value = '密码已更新'
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
  } catch (e: any) {
    passwordMsg.value = e?.response?.data?.detail || '更新失败'
  } finally {
    passwordLoading.value = false
  }
}
</script>

<template>
  <div class="space-y-8 max-w-7xl">
    <h1 class="text-3xl font-bold tracking-tight">账户设置</h1>

    <div class="grid gap-6 xl:grid-cols-2">
      <!-- 基本信息 -->
      <Card class="h-full">
        <CardHeader>
          <CardTitle>基本信息</CardTitle>
          <CardDescription>更新您的显示名称</CardDescription>
        </CardHeader>
        <CardContent class="grid gap-4 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div class="space-y-1">
            <Label>邮箱</Label>
            <Input :value="authStore.user?.email" disabled class="bg-muted" />
          </div>
          <div class="space-y-1">
            <Label for="name">显示名称</Label>
            <Input id="name" v-model="profileForm.name" placeholder="请输入名称" />
          </div>
        </CardContent>
        <CardFooter class="flex items-center gap-3">
          <Button @click="saveProfile" :disabled="profileLoading">{{ profileLoading ? '保存中...' : '保存' }}</Button>
          <span v-if="profileMsg" class="text-sm" :class="profileMsg.includes('成功') ? 'text-green-600' : 'text-destructive'">{{ profileMsg }}</span>
        </CardFooter>
      </Card>

      <!-- 修改邮箱 -->
      <Card class="h-full">
        <CardHeader>
          <CardTitle>修改邮箱</CardTitle>
          <CardDescription>需要验证当前密码</CardDescription>
        </CardHeader>
        <CardContent class="grid gap-4 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div class="space-y-1">
            <Label for="new-email">新邮箱</Label>
            <Input id="new-email" v-model="emailForm.new_email" type="email" placeholder="新邮箱地址" />
          </div>
          <div class="space-y-1">
            <Label for="email-pass">当前密码</Label>
            <Input id="email-pass" v-model="emailForm.current_password" type="password" placeholder="验证当前密码" />
          </div>
        </CardContent>
        <CardFooter class="flex items-center gap-3">
          <Button @click="saveEmail" :disabled="emailLoading">{{ emailLoading ? '更新中...' : '更新邮箱' }}</Button>
          <span v-if="emailMsg" class="text-sm" :class="emailMsg.includes('已更新') ? 'text-green-600' : 'text-destructive'">{{ emailMsg }}</span>
        </CardFooter>
      </Card>

      <!-- 修改密码 -->
      <Card class="xl:col-span-2">
        <CardHeader>
          <CardTitle>修改密码</CardTitle>
          <CardDescription>密码至少 6 位</CardDescription>
        </CardHeader>
        <CardContent class="grid gap-4 md:grid-cols-3">
          <div class="space-y-1">
            <Label for="cur-pass">当前密码</Label>
            <Input id="cur-pass" v-model="passwordForm.current_password" type="password" placeholder="当前密码" />
          </div>
          <div class="space-y-1">
            <Label for="new-pass">新密码</Label>
            <Input id="new-pass" v-model="passwordForm.new_password" type="password" placeholder="新密码（至少6位）" />
          </div>
          <div class="space-y-1">
            <Label for="confirm-pass">确认新密码</Label>
            <Input id="confirm-pass" v-model="passwordForm.confirm_password" type="password" placeholder="再次输入新密码" />
          </div>
        </CardContent>
        <CardFooter class="flex items-center gap-3">
          <Button @click="savePassword" :disabled="passwordLoading">{{ passwordLoading ? '更新中...' : '修改密码' }}</Button>
          <span v-if="passwordMsg" class="text-sm" :class="passwordMsg.includes('已更新') ? 'text-green-600' : 'text-destructive'">{{ passwordMsg }}</span>
        </CardFooter>
      </Card>
    </div>

    <Separator />

    <!-- 模型配置 -->
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h2 class="text-xl font-semibold">模型配置</h2>
        <p class="text-sm text-muted-foreground mt-0.5">
          配置 AI Provider，Responses 格式给 Codex，Messages 格式给 Claude Code
        </p>
      </div>
      <Button size="sm" @click="addProvider">+ 新增 Provider</Button>
    </div>

    <div v-if="!providers.length" class="text-muted-foreground text-sm py-4 text-center border rounded-lg">
      暂未配置 Provider，点击上方按钮新增
    </div>

    <Card v-for="p in providers" :key="p.id">
      <CardHeader class="pb-2">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <CardTitle class="text-base">{{ p.name || '未命名' }}</CardTitle>
          <div class="flex items-center gap-2">
            <Badge :variant="p.format === 'responses' ? 'default' : 'outline'" class="text-[10px]">
              {{ p.format === 'responses' ? 'Codex (Responses)' : 'Claude (Messages)' }}
            </Badge>
            <Button size="sm" variant="ghost" class="h-7 px-2 text-xs text-destructive" @click="removeProvider(p)">删除</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent class="grid gap-5 xl:grid-cols-2">
        <!-- 名称 -->
        <div class="space-y-1">
          <Label>名称</Label>
          <Input v-model="p.name" placeholder="如：OpenAI 官方、Azure、Ollama" />
        </div>
        <!-- URL + Key -->
        <div class="space-y-1">
          <Label>API Base URL</Label>
          <Input v-model="p.base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1">
          <div class="flex items-center justify-between">
            <Label>API Key</Label>
            <Button
              size="sm" variant="outline" class="h-6 px-2 text-[11px]"
              :disabled="p.fetching || !p.base_url"
              @click="fetchModels(p)"
            >{{ p.fetching ? '拉取中...' : '拉取模型列表' }}</Button>
          </div>
          <Input v-model="p.api_key" type="password" placeholder="输入新 Key 可覆盖，留空保持不变" />
        </div>
        <!-- 格式 -->
        <div class="space-y-1.5 xl:col-span-2">
          <Label>API 格式</Label>
          <div class="flex gap-3">
            <label class="flex items-center gap-1.5 cursor-pointer text-sm">
              <input type="radio" :value="'responses'" v-model="p.format" class="accent-primary" />
              Responses（Codex）
            </label>
            <label class="flex items-center gap-1.5 cursor-pointer text-sm">
              <input type="radio" :value="'messages'" v-model="p.format" class="accent-primary" />
              Messages（Claude Code）
            </label>
          </div>
        </div>
        <!-- 模型选择 -->
        <div class="space-y-1.5 xl:col-span-2">
          <Label>选择模型</Label>
          <div v-if="p.availableModels.length" class="flex flex-wrap gap-2">
            <label
              v-for="m in p.availableModels" :key="m"
              class="flex items-center gap-1 text-xs px-2 py-1 rounded border cursor-pointer transition-colors"
              :class="p.models.includes(m)
                ? 'bg-primary/10 border-primary text-primary'
                : 'bg-background hover:bg-muted border-border'"
            >
              <input type="checkbox" :checked="p.models.includes(m)" @change="toggleModel(p, m)" class="sr-only" />
              <span class="inline-block h-3 w-3 rounded border flex items-center justify-center text-[9px] shrink-0"
                :class="p.models.includes(m) ? 'bg-primary border-primary text-white' : 'border-muted-foreground/40'"
              >{{ p.models.includes(m) ? '✓' : '' }}</span>
              {{ m }}
              <button
                v-if="p.models.includes(m)"
                type="button"
                class="ml-1 text-[9px] text-muted-foreground hover:text-primary underline"
                :disabled="p.verifying === m"
                @click.stop="verifyModel(p, m)"
              >{{ p.verifying === m ? '...' : '验证' }}</button>
            </label>
          </div>
          <div v-else class="text-xs text-muted-foreground">输入 URL 和 Key 后点击「拉取模型列表」，或在下方手动添加</div>
          <!-- 手动输入 -->
          <div class="flex gap-2">
            <Input
              v-model="p.manualModel" placeholder="手动输入模型名称" class="h-8 text-xs"
              @keydown.enter="addManualModel(p)"
            />
            <Button size="sm" variant="outline" class="h-8 px-3 text-xs shrink-0" @click="addManualModel(p)">添加</Button>
          </div>
        </div>
      </CardContent>
      <CardFooter class="flex items-center gap-3">
        <Button @click="saveProvider(p)" :disabled="p.saving">{{ p.saving ? '保存中...' : '保存' }}</Button>
        <span v-if="p.msg" class="text-sm" :class="p.msg.includes('已保存') || p.msg.includes('获取到') || p.msg.includes('连通正常') ? 'text-green-600' : 'text-muted-foreground'">{{ p.msg }}</span>
      </CardFooter>
    </Card>
  </div>
</template>
