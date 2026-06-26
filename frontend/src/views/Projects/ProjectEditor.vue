<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { projectsAPI } from '@/api/projects'
import RepoTabs from './components/RepoTabs.vue'
import RepoFileTree from './components/RepoFileTree.vue'
import { ArrowLeft, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/Editor/CodeEditor.vue'
import BuildLogModal from '@/components/BuildLogModal.vue'
import type { Site } from '@/types/models'

const buildLogOpen = ref(false)
const buildLogSiteId = ref('')
const buildLogSiteName = ref('')

function openBuildLog(repo: Site) {
  buildLogSiteId.value = repo.site_id
  buildLogSiteName.value = repo.name
  buildLogOpen.value = true
}

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const projectId = route.params.id as string

const activeRepoId = ref('')

interface EditorTab {
  id: string
  label: string
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

  const existing = openTabs.value.find(t => t.id === tabId)
  if (existing) {
    activeTabId.value = tabId
    return
  }

  let res: any
  try {
    res = await projectsAPI.getRepoFile(projectId, payload.repoId, payload.path)
  } catch {
    const { toast } = await import('vue-sonner')
    toast.error('无法打开文件')
    return
  }

  if (res.binary) {
    const { toast } = await import('vue-sonner')
    toast.warning('该文件为二进制文件，无法预览')
    return
  }

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
  <div class="flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
    <!-- Toolbar -->
    <div class="flex shrink-0 items-center gap-2 border-b bg-background px-4 py-2">
      <Button variant="ghost" size="sm" class="text-muted-foreground" @click="router.push(`/projects/${projectId}`)">
        <ArrowLeft class="size-4" />
        返回项目
      </Button>
      <span class="text-sm font-medium" v-if="projectStore.currentProject">
        {{ projectStore.currentProject.name }}
      </span>
    </div>

    <!-- Repo tabs -->
    <RepoTabs
      :repos="repos"
      :activeRepoId="activeRepoId"
      @select="handleSelectRepo"
      @viewBuildLog="openBuildLog"
    />

    <div class="flex flex-1 overflow-hidden">
      <!-- File tree -->
      <div class="w-64 shrink-0 overflow-y-auto border-r p-2" v-if="activeRepo">
        <RepoFileTree
          :projectId="projectId"
          :repoId="activeRepoId"
          :repoName="activeRepo.name"
          @open-file="handleOpenFile"
        />
      </div>

      <!-- Editor area -->
      <div class="flex flex-1 flex-col overflow-hidden">
        <!-- Open-file tabs -->
        <div class="flex shrink-0 overflow-x-auto border-b bg-muted/30" v-if="openTabs.length">
          <button
            v-for="tab in openTabs"
            :key="tab.id"
            class="group flex items-center gap-2 whitespace-nowrap border-r px-3 py-1.5 text-xs transition-colors"
            :class="activeTabId === tab.id ? 'bg-background font-medium text-foreground' : 'text-muted-foreground hover:bg-background/50'"
            @click="activeTabId = tab.id"
          >
            <span>{{ tab.label }}</span>
            <span
              class="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-muted hover:text-destructive group-hover:opacity-100"
              @click.stop="handleCloseTab(tab.id)"
            >
              <X class="size-3" />
            </span>
          </button>
        </div>

        <!-- Monaco -->
        <div class="flex-1 overflow-hidden" v-if="activeTabContent">
          <CodeEditor
            :modelValue="activeTabContent.content"
            :language="activeTabContent.language"
            :readonly="true"
            theme="vs-dark"
          />
        </div>
        <div v-else class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          从左侧选择文件查看内容
        </div>
      </div>
    </div>

    <BuildLogModal
      v-model:open="buildLogOpen"
      :site-id="buildLogSiteId"
      :site-name="buildLogSiteName"
    />
  </div>
</template>
