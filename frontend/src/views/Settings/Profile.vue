<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useAuthStore } from '@/stores/auth'
import { authAPI } from '@/api/auth'
import type { UserConfig } from '@/types/models'

const authStore = useAuthStore()

// 基本信息
const profileForm = reactive({
  name: authStore.user?.name || '',
})
const profileLoading = ref(false)
const profileMsg = ref('')

// 修改邮箱
const emailForm = reactive({
  new_email: '',
  current_password: '',
})
const emailLoading = ref(false)
const emailMsg = ref('')

// 修改密码
const passwordForm = reactive({
  current_password: '',
  new_password: '',
  confirm_password: '',
})
const passwordLoading = ref(false)
const passwordMsg = ref('')

// 模型配置
const llmConfig = reactive<UserConfig>({
  llm_mode: 'responses',
  llm_base_url: 'https://api.openai.com/v1',
  llm_api_key: '',
  llm_model: 'gpt-4.1-mini',
  codex_client_id: '',
  codex_client_secret: '',
  codex_redirect_uri: '',
  codex_access_token: '',
  codex_mcp_url: '',
  claude_api_key: '',
  gemini_api_key: '',
})
const llmLoading = ref(false)
const llmMsg = ref('')

onMounted(async () => {
  profileForm.name = authStore.user?.name || ''
  try {
    const res = await authAPI.getUserConfig()
    if (res.config) Object.assign(llmConfig, res.config)
  } catch {}
})

async function saveProfile() {
  profileLoading.value = true
  profileMsg.value = ''
  try {
    const res = await authAPI.updateProfile({ name: profileForm.name })
    if ((res as any).user) authStore.user = (res as any).user
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
    const res = await authAPI.updateEmail({
      new_email: emailForm.new_email,
      current_password: emailForm.current_password,
    })
    if ((res as any).user) authStore.user = (res as any).user
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
    await authAPI.updatePassword({
      current_password: passwordForm.current_password,
      new_password: passwordForm.new_password,
    })
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

async function saveLlmConfig() {
  llmLoading.value = true
  llmMsg.value = ''
  try {
    const res = await authAPI.updateUserConfig({ ...llmConfig })
    if (res.config) Object.assign(llmConfig, res.config)
    llmMsg.value = '配置已保存'
  } catch (e: any) {
    llmMsg.value = e?.response?.data?.detail || '保存失败'
  } finally {
    llmLoading.value = false
  }
}
</script>

<template>
  <div class="space-y-6 max-w-2xl">
    <h1 class="text-3xl font-bold tracking-tight">账户设置</h1>

    <!-- 基本信息 -->
    <Card>
      <CardHeader>
        <CardTitle>基本信息</CardTitle>
        <CardDescription>更新您的显示名称</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
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
        <Button @click="saveProfile" :disabled="profileLoading">
          {{ profileLoading ? '保存中...' : '保存' }}
        </Button>
        <span v-if="profileMsg" class="text-sm" :class="profileMsg.includes('成功') ? 'text-green-600' : 'text-destructive'">
          {{ profileMsg }}
        </span>
      </CardFooter>
    </Card>

    <Separator />

    <!-- 修改邮箱 -->
    <Card>
      <CardHeader>
        <CardTitle>修改邮箱</CardTitle>
        <CardDescription>需要验证当前密码</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="space-y-1">
          <Label for="new-email">新邮箱</Label>
          <Input id="new-email" v-model="emailForm.new_email" type="email" placeholder="新邮箱地址" />
        </div>
        <div class="space-y-1">
          <Label for="email-password">当前密码</Label>
          <Input id="email-password" v-model="emailForm.current_password" type="password" placeholder="验证当前密码" />
        </div>
      </CardContent>
      <CardFooter class="flex items-center gap-3">
        <Button @click="saveEmail" :disabled="emailLoading">
          {{ emailLoading ? '更新中...' : '更新邮箱' }}
        </Button>
        <span v-if="emailMsg" class="text-sm" :class="emailMsg.includes('更新') ? 'text-green-600' : 'text-destructive'">
          {{ emailMsg }}
        </span>
      </CardFooter>
    </Card>

    <Separator />

    <!-- 修改密码 -->
    <Card>
      <CardHeader>
        <CardTitle>修改密码</CardTitle>
        <CardDescription>密码至少 6 位</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
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
        <Button @click="savePassword" :disabled="passwordLoading">
          {{ passwordLoading ? '更新中...' : '修改密码' }}
        </Button>
        <span v-if="passwordMsg" class="text-sm" :class="passwordMsg.includes('已更新') ? 'text-green-600' : 'text-destructive'">
          {{ passwordMsg }}
        </span>
      </CardFooter>
    </Card>

    <Separator />

    <!-- 模型配置 -->
    <Card>
      <CardHeader>
        <CardTitle>模型配置</CardTitle>
        <CardDescription>配置您的 AI 模型参数，仅对当前账户生效</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1">
            <Label for="llm-mode">模式</Label>
            <Input id="llm-mode" v-model="llmConfig.llm_mode" placeholder="responses" />
          </div>
          <div class="space-y-1">
            <Label for="llm-model">模型名称</Label>
            <Input id="llm-model" v-model="llmConfig.llm_model" placeholder="gpt-4.1-mini" />
          </div>
        </div>
        <div class="space-y-1">
          <Label for="llm-base-url">API Base URL</Label>
          <Input id="llm-base-url" v-model="llmConfig.llm_base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1">
          <Label for="llm-api-key">API Key</Label>
          <Input id="llm-api-key" v-model="llmConfig.llm_api_key" type="password" placeholder="sk-..." />
        </div>

        <Separator class="my-2" />
        <p class="text-sm font-medium text-muted-foreground">Codex 配置（可选）</p>

        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1">
            <Label for="codex-client-id">Client ID</Label>
            <Input id="codex-client-id" v-model="llmConfig.codex_client_id" placeholder="Codex Client ID" />
          </div>
          <div class="space-y-1">
            <Label for="codex-client-secret">Client Secret</Label>
            <Input id="codex-client-secret" v-model="llmConfig.codex_client_secret" type="password" placeholder="Codex Client Secret" />
          </div>
        </div>
        <div class="space-y-1">
          <Label for="codex-redirect-uri">Redirect URI</Label>
          <Input id="codex-redirect-uri" v-model="llmConfig.codex_redirect_uri" placeholder="https://..." />
        </div>
        <div class="space-y-1">
          <Label for="codex-mcp-url">MCP URL</Label>
          <Input id="codex-mcp-url" v-model="llmConfig.codex_mcp_url" placeholder="MCP 服务地址" />
        </div>
        <div class="space-y-1">
          <Label for="codex-access-token">Access Token</Label>
          <Input id="codex-access-token" v-model="llmConfig.codex_access_token" type="password" placeholder="Codex Access Token" />
        </div>
      </CardContent>
      <CardFooter class="flex items-center gap-3">
        <Button @click="saveLlmConfig" :disabled="llmLoading">
          {{ llmLoading ? '保存中...' : '保存配置' }}
        </Button>
        <span v-if="llmMsg" class="text-sm" :class="llmMsg.includes('已保存') ? 'text-green-600' : 'text-destructive'">
          {{ llmMsg }}
        </span>
      </CardFooter>
    </Card>
  </div>
</template>
