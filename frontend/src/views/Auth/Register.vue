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
const confirmPassword = ref('')
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
  if (password.value !== confirmPassword.value) {
    errorMsg.value = '两次输入的密码不一致'
    return false
  }
  errorMsg.value = ''
  return true
}

const register = async () => {
  if (!validateForm()) {
    toast.error(errorMsg.value)
    return
  }
  try {
    loading.value = true
    errorMsg.value = ''
    await authStore.register(email.value.trim(), password.value)
    toast.success('注册成功，正在跳转登录页…')
    router.push('/login')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || ''
    if (detail.toLowerCase().includes('already') || detail.includes('已注册') || detail.includes('已存在')) {
      errorMsg.value = '该邮箱已被注册'
    } else {
      errorMsg.value = detail || '注册失败，请稍后重试'
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
        <img src="/favicon.svg" alt="NextProject" class="size-9 rounded-lg" />
        <span class="text-lg font-semibold tracking-tight">NextProject</span>
      </div>

      <div class="relative max-w-md space-y-6">
        <p class="text-3xl font-semibold leading-tight tracking-tight">
          建一个账号，<br />开始驱动 AI 交付。
        </p>
        <p class="text-sm leading-relaxed text-zinc-400">
          注册后即可创建项目、挂载仓库、下发编码任务，并实时查看日志与检查点。任务全程隔离在容器内执行。
        </p>
      </div>

      <p class="relative font-mono-data text-xs text-zinc-600">
        // 企业级隔离部署 · 杜绝误删本地文件
      </p>
    </aside>

    <!-- Form panel -->
    <div class="flex items-center justify-center bg-muted/30 p-6">
      <div class="w-full max-w-sm">
        <div class="mb-8 flex items-center gap-3 lg:hidden">
          <img src="/favicon.svg" alt="NextProject" class="size-9 rounded-lg" />
          <span class="text-lg font-semibold tracking-tight">NextProject</span>
        </div>

        <div class="space-y-2">
          <h1 class="text-2xl font-semibold tracking-tight">创建账号</h1>
          <p class="text-sm text-muted-foreground">输入邮箱即可注册控制台账号</p>
        </div>

        <div class="mt-8 space-y-4">
          <div
            v-if="errorMsg"
            class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-sm text-destructive"
          >
            <CircleAlert class="mt-0.5 size-4 shrink-0" />
            <span>{{ errorMsg }}</span>
          </div>

          <form class="space-y-4" @submit.prevent="register">
            <div class="space-y-2">
              <Label for="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                autocomplete="email"
                placeholder="you@example.com"
                v-model="email"
              />
            </div>
            <div class="space-y-2">
              <Label for="password">密码</Label>
              <Input
                id="password"
                type="password"
                autocomplete="new-password"
                placeholder="至少 6 位"
                v-model="password"
              />
            </div>
            <div class="space-y-2">
              <Label for="confirmPassword">确认密码</Label>
              <Input
                id="confirmPassword"
                type="password"
                autocomplete="new-password"
                placeholder="再次输入密码"
                v-model="confirmPassword"
              />
            </div>
            <Button type="submit" class="w-full" :disabled="loading">
              {{ loading ? '注册中…' : '注册' }}
            </Button>
          </form>

          <p class="text-center text-sm text-muted-foreground">
            已有账号？
            <router-link to="/login" class="font-medium text-primary hover:underline">直接登录</router-link>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
