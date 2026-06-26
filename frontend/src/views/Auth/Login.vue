<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { CircleAlert } from 'lucide-vue-next'

const email = ref('')
const password = ref('')
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const errorMsg = ref('')

const validateForm = () => {
  if (!email.value.trim()) {
    errorMsg.value = '请输入邮箱地址'
    return false
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) {
    errorMsg.value = '请输入有效的邮箱地址'
    return false
  }
  if (!password.value) {
    errorMsg.value = '请输入密码'
    return false
  }
  if (password.value.length < 6) {
    errorMsg.value = '密码长度至少为 6 位'
    return false
  }
  errorMsg.value = ''
  return true
}

const login = async () => {
  if (!validateForm()) {
    toast.error(errorMsg.value)
    return
  }
  try {
    loading.value = true
    errorMsg.value = ''
    await authStore.login(email.value.trim(), password.value)
    toast.success('登录成功')
    router.push('/')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || ''
    if (detail.toLowerCase().includes('incorrect') || detail.includes('密码')) {
      errorMsg.value = '邮箱或密码错误'
    } else if (detail.toLowerCase().includes('not found') || detail.includes('不存在')) {
      errorMsg.value = '该账号不存在'
    } else if (e?.response?.status === 401) {
      errorMsg.value = '邮箱或密码错误'
    } else {
      errorMsg.value = detail || '登录失败，请稍后重试'
    }
    toast.error(errorMsg.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="grid min-h-screen lg:grid-cols-2">
    <!-- Brand panel -->
    <aside
      class="relative hidden flex-col justify-between overflow-hidden border-r bg-zinc-950 p-12 text-zinc-100 lg:flex"
    >
      <div
        class="pointer-events-none absolute inset-0 opacity-[0.07]"
        style="background-image: radial-gradient(circle at 1px 1px, white 1px, transparent 0); background-size: 28px 28px;"
      />
      <div class="relative flex items-center gap-3">
        <div class="flex size-9 items-center justify-center rounded-lg bg-primary font-mono-data text-base font-bold">
          N
        </div>
        <span class="text-lg font-semibold tracking-tight">NextProject</span>
      </div>

      <div class="relative max-w-md space-y-6">
        <p class="text-3xl font-semibold leading-tight tracking-tight">
          驱动 AI 写代码、<br />运行、部署与回滚。
        </p>
        <p class="text-sm leading-relaxed text-zinc-400">
          一个控制台管理站点、任务、Codex/Claude/Gemini 编码任务，以及 Git 检查点回滚。从需求到上线，全程可观测。
        </p>
        <div class="flex items-center gap-6 pt-2 font-mono-data text-xs text-zinc-500">
          <span><span class="text-zinc-200">Codex</span></span>
          <span><span class="text-zinc-200">Claude Code</span></span>
          <span><span class="text-zinc-200">Gemini</span></span>
        </div>
      </div>

      <p class="relative font-mono-data text-xs text-zinc-600">
        // 企业级隔离部署 · 杜绝误删本地文件
      </p>
    </aside>

    <!-- Form panel -->
    <div class="flex items-center justify-center bg-muted/30 p-6">
      <div class="w-full max-w-sm">
        <!-- Mobile brand -->
        <div class="mb-8 flex items-center gap-3 lg:hidden">
          <div class="flex size-9 items-center justify-center rounded-lg bg-primary font-mono-data text-base font-bold text-primary-foreground">
            N
          </div>
          <span class="text-lg font-semibold tracking-tight">NextProject</span>
        </div>

        <div class="space-y-2">
          <h1 class="text-2xl font-semibold tracking-tight">欢迎回来</h1>
          <p class="text-sm text-muted-foreground">输入账号信息登录控制台</p>
        </div>

        <div class="mt-8 space-y-4">
          <div
            v-if="errorMsg"
            class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-sm text-destructive"
          >
            <CircleAlert class="mt-0.5 size-4 shrink-0" />
            <span>{{ errorMsg }}</span>
          </div>

          <form class="space-y-4" @submit.prevent="login">
            <div class="space-y-2">
              <Label for="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                autocomplete="username"
                placeholder="you@example.com"
                v-model="email"
              />
            </div>
            <div class="space-y-2">
              <Label for="password">密码</Label>
              <Input
                id="password"
                type="password"
                autocomplete="current-password"
                placeholder="至少 6 位"
                v-model="password"
              />
            </div>
            <Button type="submit" class="w-full" :disabled="loading">
              {{ loading ? '登录中…' : '登录' }}
            </Button>
          </form>

          <p class="text-center text-sm text-muted-foreground">
            还没有账号？
            <router-link to="/register" class="font-medium text-primary hover:underline">立即注册</router-link>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
