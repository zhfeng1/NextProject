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

const register = async () => {
  if (!email.value || !password.value) {
    alert('请输入邮箱和密码')
    return
  }
  try {
    loading.value = true
    await authStore.register(email.value, password.value)
    alert('注册成功，请重新登录')
    router.push('/login')
  } catch (e) {
    //
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
        <div class="grid gap-2">
          <Label for="email">邮箱</Label>
          <Input id="email" type="email" placeholder="m@example.com" v-model="email" />
        </div>
        <div class="grid gap-2">
          <Label for="password">密码</Label>
          <Input id="password" type="password" v-model="password" @keyup.enter="register" />
        </div>
      </CardContent>
      <CardFooter class="flex flex-col gap-4">
        <Button class="w-full" @click="register" :disabled="loading">注册</Button>
        <div class="text-sm text-center text-muted-foreground w-full">
           <router-link to="/login" class="hover:underline">已有账号？去登录</router-link>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>
