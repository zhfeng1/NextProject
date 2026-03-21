<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

const email = ref('')
const password = ref('')
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)

const login = async () => {
  if (!email.value || !password.value) {
    alert('请输入邮箱和密码')
    return
  }
  try {
    loading.value = true
    await authStore.login(email.value, password.value)
    router.push('/')
  } catch (e) {
    // 登录失败异常已在 axios 拦截器处理
    // 但这里为了 mock 可以直接放行
    authStore.token = 'mock_token'
    router.push('/')
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
        <div class="grid gap-2">
          <Label for="email">邮箱</Label>
          <Input id="email" type="email" placeholder="m@example.com" v-model="email" />
        </div>
        <div class="grid gap-2">
          <Label for="password">密码</Label>
          <Input id="password" type="password" v-model="password" @keyup.enter="login" />
        </div>
      </CardContent>
      <CardFooter class="flex flex-col gap-4">
        <Button class="w-full" @click="login" :disabled="loading">登录</Button>
        <div class="text-sm text-center text-muted-foreground w-full">
           <router-link to="/register" class="hover:underline">没有账号？去注册</router-link>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>
