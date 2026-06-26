<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  SidebarInset,
} from '@/components/ui/sidebar'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Home,
  LayoutTemplate,
  ListTodo,
  Settings2,
  LogOut,
  PlugZap,
  Sparkles,
  FolderKanban,
  Sun,
  Moon,
  ChevronUp,
  Gauge,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { theme, toggle } = useTheme()

const logout = () => {
  authStore.logout()
  router.push('/login')
}

const navGroups = [
  {
    label: '工作台',
    items: [
      { label: '系统概览', to: '/', icon: Home, match: (p: string) => p === '/' },
    ],
  },
  {
    label: '项目管理',
    items: [
      { label: '我的项目', to: '/projects', icon: FolderKanban, match: (p: string) => p === '/projects' || p.startsWith('/projects/') },
      { label: '任务看板', to: '/tasks', icon: ListTodo, match: (p: string) => p === '/tasks' },
      { label: '模板市场', to: '/templates', icon: LayoutTemplate, match: (p: string) => p === '/templates' },
    ],
  },
  {
    label: 'AI 中心',
    items: [
      { label: 'MCP 中心', to: '/mcp', icon: PlugZap, match: (p: string) => p === '/mcp' },
      { label: 'Skill 中心', to: '/skills', icon: Sparkles, match: (p: string) => p === '/skills' },
    ],
  },
  {
    label: '后台配置',
    items: [
      { label: '账户设置', to: '/settings/account', icon: Settings2, match: (p: string) => p === '/settings/account' },
      { label: '系统设置', to: '/settings/system', icon: Gauge, match: (p: string) => p === '/settings/system' },
    ],
  },
]

const activeRouteName = computed(() => {
  const match = navGroups
    .flatMap((g) => g.items)
    .find((item) => item.match(route.path))
  return match?.label ?? 'NextProject'
})

const initials = computed(() => {
  const name = authStore.user?.name || authStore.user?.email || 'U'
  return name.slice(0, 2).toUpperCase()
})

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
    <Sidebar collapsible="icon">
      <!-- Brand -->
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" as-child>
              <router-link to="/">
                <div
                  class="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground"
                >
                  <span class="font-mono-data text-sm font-bold leading-none">N</span>
                </div>
                <div class="grid flex-1 text-left leading-none">
                  <span class="truncate text-sm font-semibold">NextProject</span>
                  <span class="truncate text-xs text-muted-foreground">AI 工作流控制台</span>
                </div>
              </router-link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <!-- Navigation -->
      <SidebarContent>
        <SidebarGroup v-for="group in navGroups" :key="group.label">
          <SidebarGroupLabel>{{ group.label }}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem v-for="item in group.items" :key="item.to">
                <SidebarMenuButton
                  as-child
                  :is-active="item.match(route.path)"
                  :tooltip="item.label"
                >
                  <router-link :to="item.to">
                    <component :is="item.icon" />
                    <span>{{ item.label }}</span>
                  </router-link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <!-- User footer -->
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" class="data-[state=open]:bg-sidebar-accent" :is-active="false">
              <Avatar class="size-8 rounded-lg">
                <AvatarFallback class="rounded-lg bg-primary/10 text-primary font-mono-data text-xs">
                  {{ initials }}
                </AvatarFallback>
              </Avatar>
              <div class="grid flex-1 text-left leading-none">
                <span class="truncate text-sm font-medium">
                  {{ authStore.user?.name || '账户' }}
                </span>
                <span class="truncate text-xs text-muted-foreground">
                  {{ authStore.user?.email || '—' }}
                </span>
              </div>
              <LogOut class="ml-auto size-4 text-muted-foreground" @click="logout" />
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>

    <SidebarInset class="flex flex-col min-h-screen">
      <header
        class="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60"
      >
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-1 h-4" />
        <nav class="flex items-center gap-1.5 text-sm">
          <span class="text-muted-foreground">NextProject</span>
          <span class="text-muted-foreground/40">/</span>
          <span class="font-medium text-foreground">{{ activeRouteName }}</span>
        </nav>

        <div class="ml-auto flex items-center gap-1.5">
          <Button variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="切换主题" @click="toggle">
            <Sun v-if="theme === 'dark'" class="size-4" />
            <Moon v-else class="size-4" />
          </Button>
          <Separator orientation="vertical" class="h-4" />
          <Button variant="ghost" size="sm" class="text-muted-foreground" @click="logout">
            <LogOut class="size-4" />
            退出
          </Button>
        </div>
      </header>
      <main class="flex-1 overflow-auto bg-muted/30 p-6">
        <router-view />
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
