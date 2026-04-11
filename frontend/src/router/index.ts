// @ts-nocheck
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const normalizeSiteId = (value: unknown) => {
  const siteId = String(value ?? '').trim()
  return siteId || undefined
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Auth/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Auth/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/site-editor/:id',
    redirect: (to) => {
      const id = normalizeSiteId(to.params.id)
      return id
        ? { name: 'SiteEditor', params: { id }, query: to.query, hash: to.hash }
        : { name: 'SiteList' }
    },
  },
  {
    path: '/',
    component: () => import('@/components/Layout/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard/Index.vue'),
      },
      {
        path: 'projects',
        name: 'ProjectList',
        component: () => import('@/views/Projects/ProjectList.vue'),
      },
      {
        path: 'projects/:id',
        name: 'ProjectDetail',
        component: () => import('@/views/Projects/ProjectDetail.vue'),
      },
      {
        path: 'sites',
        redirect: '/projects',
      },
      {
        path: 'sites/:id',
        name: 'SiteDetail',
        component: () => import('@/views/Sites/SiteDetail.vue'),
      },
      {
        path: 'sites/:id/edit',
        name: 'SiteEditor',
        component: () => import('@/views/Sites/SiteEditor.vue'),
      },
      {
        path: 'templates',
        name: 'TemplateMarket',
        component: () => import('@/views/Templates/TemplateMarket.vue'),
      },
      {
        path: 'tasks',
        name: 'TaskList',
        component: () => import('@/views/Tasks/TaskList.vue'),
      },
      {
        path: 'mcp',
        name: 'McpCenter',
        component: () => import('@/views/Centers/McpCenter.vue'),
      },
      {
        path: 'skills',
        name: 'SkillCenter',
        component: () => import('@/views/Centers/SkillCenter.vue'),
      },
      {
        path: 'workflows',
        name: 'WorkflowCenter',
        component: () => import('@/views/Centers/WorkflowCenter.vue'),
      },
      {
        path: 'settings',
        redirect: '/settings/account',
      },
      {
        path: 'settings/account',
        name: 'AccountSettings',
        component: () => import('@/views/Settings/Account.vue'),
      },
      {
        path: 'settings/system',
        name: 'SystemSettings',
        component: () => import('@/views/Settings/System.vue'),
      },
      {
        path: 'monitor',
        redirect: '/',
      }
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：认证检查
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else {
    next()
  }
})

export default router
