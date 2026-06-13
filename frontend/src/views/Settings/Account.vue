<script setup lang="ts">
// @ts-nocheck
import { ref, reactive, onMounted } from 'vue'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/auth'
import { authAPI } from '@/api/auth'

const authStore = useAuthStore()

const profileForm = reactive({ name: '' })
const profileLoading = ref(false)
const profileMsg = ref('')

const emailForm = reactive({ new_email: '', current_password: '' })
const emailLoading = ref(false)
const emailMsg = ref('')

const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' })
const passwordLoading = ref(false)
const passwordMsg = ref('')

onMounted(async () => {
  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {}
  }
  profileForm.name = authStore.user?.name || ''
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
  <div class="space-y-8 max-w-5xl">
    <h1 class="text-3xl font-bold tracking-tight">账户设置</h1>

    <div class="grid gap-6 xl:grid-cols-2">
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
  </div>
</template>
