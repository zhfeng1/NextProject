<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authAPI } from '@/api/auth'
import type { UserConfig } from '@/api/auth'

const cfg = reactive({
  codex_client_id: '',
  codex_client_secret: '',
  codex_redirect_uri: '',
  codex_access_token: '',
  codex_mcp_url: '',
})

const loading = ref(false)
const msg = ref('')

onMounted(async () => {
  try {
    const res = await authAPI.getUserConfig()
    if (res.config) {
      cfg.codex_client_id = res.config.codex_client_id
      cfg.codex_client_secret = res.config.codex_client_secret
      cfg.codex_redirect_uri = res.config.codex_redirect_uri
      cfg.codex_access_token = res.config.codex_access_token
      cfg.codex_mcp_url = res.config.codex_mcp_url
    }
  } catch {}
})

async function save() {
  loading.value = true
  msg.value = ''
  try {
    await authAPI.updateUserConfig({ ...cfg })
    msg.value = '配置已保存'
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || '保存失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="space-y-6 max-w-2xl">
    <h1 class="text-3xl font-bold tracking-tight">系统设置</h1>
    <p class="text-muted-foreground text-sm">Codex OAuth 凭证与 MCP 配置。AI 模型的 API Key 请在「账户设置」的模型配置中管理。</p>

    <Card>
      <CardHeader>
        <CardTitle>Codex OAuth</CardTitle>
        <CardDescription>Codex CLI 的 OAuth 凭证与 MCP 服务地址</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1">
            <Label for="codex-id">Client ID</Label>
            <Input id="codex-id" v-model="cfg.codex_client_id" placeholder="Codex Client ID" />
          </div>
          <div class="space-y-1">
            <Label for="codex-secret">Client Secret</Label>
            <Input id="codex-secret" v-model="cfg.codex_client_secret" type="password" placeholder="Codex Client Secret" />
          </div>
        </div>
        <div class="space-y-1">
          <Label for="codex-redirect">Redirect URI</Label>
          <Input id="codex-redirect" v-model="cfg.codex_redirect_uri" placeholder="https://..." />
        </div>
        <div class="space-y-1">
          <Label for="codex-token">Access Token</Label>
          <Input id="codex-token" v-model="cfg.codex_access_token" type="password" placeholder="OAuth Access Token" />
        </div>
        <div class="space-y-1">
          <Label for="codex-mcp">MCP URL</Label>
          <Input id="codex-mcp" v-model="cfg.codex_mcp_url" placeholder="MCP 服务地址" />
        </div>
      </CardContent>
      <CardFooter class="flex items-center gap-3">
        <Button @click="save" :disabled="loading">{{ loading ? '保存中...' : '保存' }}</Button>
        <span v-if="msg" class="text-sm" :class="msg.includes('已保存') ? 'text-green-600' : 'text-destructive'">{{ msg }}</span>
      </CardFooter>
    </Card>
  </div>
</template>
