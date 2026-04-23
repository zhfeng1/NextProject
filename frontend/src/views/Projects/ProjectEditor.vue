<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { projectsAPI } from '@/api/projects'
import RepoTabs from './components/RepoTabs.vue'
import RepoFileTree from './components/RepoFileTree.vue'
import type { Site } from '@/types/models'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const projectId = route.params.id as string

// 当前选中的仓库
const activeRepoId = ref('')

// 已打开的编辑器标签（只读浏览）
interface EditorTab {
  id: string          // 唯一 key: `${repoId}:${path}`
  label: string       // 显示: `[repoName] filename`
  repoId: string
  repoName: string
  path: string
  content: string
  language: string
}
const openTabs = ref<EditorTab[]>([])
const activeTabId = ref('')

const repos = computed<Site[]>(() => projectStore.currentProject?.repos || [])
const activeRepo = computed(() => repos.value.find(r => r.site_id === activeRepoId.value))

onMounted(async () => {
  await projectStore.fetchProject(projectId)
  if (repos.value.length > 0) {
    activeRepoId.value = repos.value[0].site_id
  }
})

function handleSelectRepo(repoId: string) {
  activeRepoId.value = repoId
  // 切换仓库不关闭已打开标签 (D-12)
}

function detectLanguage(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescriptreact', js: 'javascript', jsx: 'javascriptreact',
    py: 'python', vue: 'html', html: 'html', css: 'css', scss: 'scss',
    json: 'json', md: 'markdown', yaml: 'yaml', yml: 'yaml',
    sh: 'shell', bash: 'shell', sql: 'sql', dockerfile: 'dockerfile',
  }
  return map[ext] || 'plaintext'
}

async function handleOpenFile(payload: { path: string; repoId: string; repoName: string }) {
  const tabId = `${payload.repoId}:${payload.path}`

  // 已打开则切换到该标签
  const existing = openTabs.value.find(t => t.id === tabId)
  if (existing) {
    activeTabId.value = tabId
    return
  }

  // 获取文件内容
  const res = await projectsAPI.getRepoFile(projectId, payload.repoId, payload.path)
  const filename = payload.path.split('/').pop() || payload.path

  const tab: EditorTab = {
    id: tabId,
    label: `[${payload.repoName}] ${filename}`,
    repoId: payload.repoId,
    repoName: payload.repoName,
    path: payload.path,
    content: res.content || '',
    language: detectLanguage(filename),
  }
  openTabs.value.push(tab)
  activeTabId.value = tabId
}

function handleCloseTab(tabId: string) {
  openTabs.value = openTabs.value.filter(t => t.id !== tabId)
  if (activeTabId.value === tabId) {
    activeTabId.value = openTabs.value.length > 0 ? openTabs.value[openTabs.value.length - 1].id : ''
  }
}

const activeTabContent = computed(() => openTabs.value.find(t => t.id === activeTabId.value))
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 仓库 Tabs -->
    <RepoTabs
      :repos="repos"
      :activeRepoId="activeRepoId"
      @select="handleSelectRepo"
    />

    <div class="flex flex-1 overflow-hidden">
      <!-- 左侧文件树 -->
      <div class="w-64 border-r overflow-y-auto p-2" v-if="activeRepo">
        <RepoFileTree
          :projectId="projectId"
          :repoId="activeRepoId"
          :repoName="activeRepo.name"
          @open-file="handleOpenFile"
        />
      </div>

      <!-- 右侧编辑区（只读浏览） -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <!-- 编辑器标签栏 -->
        <div class="flex border-b overflow-x-auto bg-muted/30" v-if="openTabs.length">
          <button
            v-for="tab in openTabs"
            :key="tab.id"
            class="px-3 py-1.5 text-xs whitespace-nowrap border-r flex items-center gap-1"
            :class="activeTabId === tab.id ? 'bg-background font-medium' : 'text-muted-foreground hover:bg-background/50'"
            @click="activeTabId = tab.id"
          >
            {{ tab.label }}
            <span class="ml-1 hover:text-destructive" @click.stop="handleCloseTab(tab.id)">&times;</span>
          </button>
        </div>

        <!-- Monaco 编辑器区域（只读） -->
        <!-- [ISSUE-05] Monaco Editor 以 readOnly 模式渲染 -->
        <!-- readOnly: true -->
        <div class="flex-1 overflow-hidden" v-if="activeTabContent">
          <div class="p-4 text-sm font-mono whitespace-pre-wrap overflow-auto h-full">
            {{ activeTabContent.content }}
          </div>
        </div>
        <div v-else class="flex-1 flex items-center justify-center text-muted-foreground">
          选择文件查看内容
        </div>
      </div>
    </div>
  </div>
</template>
