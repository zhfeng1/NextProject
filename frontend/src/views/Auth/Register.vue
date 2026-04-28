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
    toast.success('注册成功，正在跳转登录页...')
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
  <div class="flex items-center justify-center min-h-screen bg-muted/20">
    <Card class="w-[400px]">
      <CardHeader>
        <CardTitle class="text-2xl text-center">创建账号</CardTitle>
        <CardDescription class="text-center">输入您的邮箱以创建新账号</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4">
        <div v-if="errorMsg" class="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
          {{ errorMsg }}
        </div>
        <div class="grid gap-2">
          <Label for="email">邮箱</Label>
          <Input id="email" type="email" placeholder="m@example.com" v-model="email" @keyup.enter="register" />
        </div>
        <div class="grid gap-2">
          <Label for="password">密码</Label>
          <Input id="password" type="password" placeholder="至少 6 位" v-model="password" />
        </div>
        <div class="grid gap-2">
          <Label for="confirmPassword">确认密码</Label>
          <Input id="confirmPassword" type="password" placeholder="请再次输入密码" v-model="confirmPassword" @keyup.enter="register" />
        </div>
      </CardContent>
      <CardFooter class="flex flex-col gap-4">
        <Button class="w-full" @click="register" :disabled="loading">
          {{ loading ? '注册中...' : '注册' }}
        </Button>
        <div class="text-sm text-center text-muted-foreground w-full">
           <router-link to="/login" class="hover:underline">已有账号？去登录</router-link>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>
