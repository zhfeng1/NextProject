<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  SidebarInset
} from '@/components/ui/sidebar'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Home, Globe, LayoutTemplate, ListTodo, Settings2, UserCog, LogOut, PlugZap, Sparkles, GitBranchPlus, FolderKanban } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const logout = () => {
   authStore.logout()
   router.push('/login')
}

onMounted(async () => {
  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {
      authStore.logout()
      router.replace('/')
    }
  }
})
</script>

<template>
  <SidebarProvider>
    <Sidebar>
      <SidebarHeader class="h-14 flex items-center justify-center border-b">
        <span class="font-bold text-lg leading-none tracking-tight">NextProject</span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>首页</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/'">
                  <router-link to="/">
                    <Home class="w-4 h-4 mr-2" />
                    <span>工作台首页</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>项目管理</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/projects' || route.path.startsWith('/projects/')">
                  <router-link to="/projects">
                    <FolderKanban class="w-4 h-4 mr-2" />
                    <span>我的项目</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/templates'">
                  <router-link to="/templates">
                    <LayoutTemplate class="w-4 h-4 mr-2" />
                    <span>模板市场</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/tasks'">
                  <router-link to="/tasks">
                    <ListTodo class="w-4 h-4 mr-2" />
                    <span>任务列表</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>AI 中心</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/mcp'">
                  <router-link to="/mcp">
                    <PlugZap class="w-4 h-4 mr-2" />
                    <span>MCP 中心</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/skills'">
                  <router-link to="/skills">
                    <Sparkles class="w-4 h-4 mr-2" />
                    <span>Skill 中心</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/workflows'">
                  <router-link to="/workflows">
                    <GitBranchPlus class="w-4 h-4 mr-2" />
                    <span>工作流中心</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>后台配置</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/settings/account'">
                  <router-link to="/settings/account">
                    <UserCog class="w-4 h-4 mr-2" />
                    <span>账户设置</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton as-child :isActive="route.path === '/settings/system'">
                  <router-link to="/settings/system">
                    <Settings2 class="w-4 h-4 mr-2" />
                    <span>系统设置</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>

    <SidebarInset class="flex flex-col min-h-screen">
      <header class="flex h-14 items-center justify-between gap-4 border-b bg-background px-6">
        <div class="flex items-center gap-4">
          <SidebarTrigger />
          <Separator orientation="vertical" class="h-6" />
        </div>
        <div>
          <Button variant="ghost" size="sm" @click="logout">
            <LogOut class="w-4 h-4 mr-2" />
            退出登录
          </Button>
        </div>
      </header>
      <main class="flex-1 p-6 overflow-auto bg-muted/20">
        <router-view />
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
