<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

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
  <div class="flex items-center justify-center min-h-screen bg-muted/20">
    <Card class="w-[400px]">
      <CardHeader>
        <CardTitle class="text-2xl text-center">系统登录</CardTitle>
        <CardDescription class="text-center">欢迎回来，请输入您的登录凭证</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4">
        <div v-if="errorMsg" class="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
          {{ errorMsg }}
        </div>
        <div class="grid gap-2">
          <Label for="email">邮箱</Label>
          <Input id="email" type="email" placeholder="m@example.com" v-model="email" @keyup.enter="login" />
        </div>
        <div class="grid gap-2">
          <Label for="password">密码</Label>
          <Input id="password" type="password" placeholder="请输入密码" v-model="password" @keyup.enter="login" />
        </div>
      </CardContent>
      <CardFooter class="flex flex-col gap-4">
        <Button class="w-full" @click="login" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </Button>
        <div class="text-sm text-center text-muted-foreground w-full">
           <router-link to="/register" class="hover:underline">没有账号？去注册</router-link>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>
