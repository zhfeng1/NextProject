<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  ChevronsUpDown,
  FileCode2,
  FolderGit2,
  Loader2,
  RefreshCw,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  conversationsAPI,
  type ConversationGitFile,
  type ConversationGitFileDiff,
  type ConversationGitRepository,
} from '@/api/conversations'
import { useTheme } from '@/composables/useTheme'
import DiffFileTreeNode, { type DiffTreeNodeData } from '@/components/Editor/DiffFileTreeNode.vue'
import SideBySideDiffEditor from '@/components/Editor/SideBySideDiffEditor.vue'

const props = defineProps<{
  conversationId: string
  repositories: ConversationGitRepository[]
}>()

const { theme } = useTheme()
const selectedRepoId = ref('')
const selectedPath = ref('')
const fileDiff = ref<ConversationGitFileDiff | null>(null)
const loading = ref(false)
const error = ref('')
let requestSeq = 0

function buildFileTree(files: ConversationGitFile[]): DiffTreeNodeData[] {
  const root: DiffTreeNodeData = { id: 'root', name: '', path: '', kind: 'folder', children: [] }
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean)
    let parent = root
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      const isFile = index === parts.length - 1
      let node = parent.children?.find(child => child.name === part && child.kind === (isFile ? 'file' : 'folder'))
      if (!node) {
        node = {
          id: `${isFile ? 'file' : 'folder'}:${path}`,
          name: part,
          path,
          kind: isFile ? 'file' : 'folder',
          status: isFile ? file.status.slice(0, 1).toUpperCase() : undefined,
          children: isFile ? undefined : [],
        }
        parent.children?.push(node)
      }
      parent = node
    })
  }

  const sortNodes = (nodes: DiffTreeNodeData[]) => {
    nodes.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1
      return a.name.localeCompare(b.name, 'zh-CN')
    })
    nodes.forEach(node => node.children && sortNodes(node.children))
  }
  sortNodes(root.children || [])
  return root.children || []
}

const repositoryTrees = computed(() => props.repositories.map(repo => ({
  repo,
  nodes: buildFileTree(repo.files || []),
})))
const activeRepo = computed(() => props.repositories.find(repo => repo.site_id === selectedRepoId.value) || null)
const activeFile = computed(() => activeRepo.value?.files.find(file => file.path === selectedPath.value) || null)
const totalFiles = computed(() => props.repositories.reduce((total, repo) => total + (repo.files?.length || 0), 0))

function detectLanguage(path: string): string {
  const filename = path.split('/').pop()?.toLowerCase() || ''
  if (filename === 'dockerfile') return 'dockerfile'
  const ext = filename.split('.').pop() || ''
  const languages: Record<string, string> = {
    ts: 'typescript', tsx: 'typescriptreact', js: 'javascript', jsx: 'javascriptreact',
    vue: 'html', html: 'html', htm: 'html', css: 'css', scss: 'scss', less: 'less',
    py: 'python', java: 'java', kt: 'kotlin', kts: 'kotlin', go: 'go', rs: 'rust',
    php: 'php', rb: 'ruby', swift: 'swift', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp',
    cs: 'csharp', sql: 'sql', sh: 'shell', bash: 'shell', zsh: 'shell',
    json: 'json', jsonc: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml',
    md: 'markdown', mdx: 'markdown', ini: 'ini', toml: 'ini', graphql: 'graphql',
  }
  return languages[ext] || 'plaintext'
}

function statusLabel(status = '') {
  if (status.startsWith('A')) return '新增'
  if (status.startsWith('D')) return '删除'
  if (status.startsWith('R')) return '重命名'
  if (status.startsWith('C')) return '复制'
  return '修改'
}

function shortRevision(value = '') {
  return value.length > 10 ? value.slice(0, 10) : value
}

async function selectFile(repo: ConversationGitRepository, path: string) {
  selectedRepoId.value = repo.site_id
  selectedPath.value = path
  fileDiff.value = null
  error.value = ''
  loading.value = true
  const seq = ++requestSeq
  try {
    const response = await conversationsAPI.getGitFileDiff(props.conversationId, repo.site_id, path)
    if (seq !== requestSeq) return
    fileDiff.value = response.file
  } catch (reason: any) {
    if (seq !== requestSeq) return
    error.value = reason?.response?.data?.detail || '文件对比加载失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function selectInitialFile() {
  const currentRepo = props.repositories.find(repo => repo.site_id === selectedRepoId.value)
  if (currentRepo?.files.some(file => file.path === selectedPath.value)) return
  const firstRepo = props.repositories.find(repo => repo.files?.length)
  const firstFile = firstRepo?.files?.[0]
  if (firstRepo && firstFile) {
    void selectFile(firstRepo, firstFile.path)
    return
  }
  selectedRepoId.value = ''
  selectedPath.value = ''
  fileDiff.value = null
}

watch(
  () => [props.conversationId, ...props.repositories.flatMap(repo => [repo.site_id, ...repo.files.map(file => file.path)])],
  selectInitialFile,
  { immediate: true },
)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col md:flex-row">
    <aside class="flex max-h-56 shrink-0 flex-col border-b bg-muted/15 md:max-h-none md:w-72 md:border-b-0 md:border-r">
      <div class="shrink-0 border-b px-3 py-3">
        <div class="flex items-center gap-2 text-sm font-semibold">
          <FolderGit2 class="size-4 text-muted-foreground" />
          修改文件
        </div>
        <div class="mt-1 text-xs text-muted-foreground">{{ totalFiles }} 个文件 · {{ repositories.length }} 个仓库</div>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto p-2" aria-label="修改文件树">
        <details
          v-for="entry in repositoryTrees"
          :key="entry.repo.site_id"
          open
          class="mb-2"
        >
          <summary class="flex min-h-9 cursor-pointer list-none items-center gap-2 rounded px-2 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <FolderGit2 class="size-3.5 shrink-0 text-primary" />
            <span class="min-w-0 flex-1 truncate">{{ entry.repo.name }}</span>
            <span class="font-mono-data text-[10px] text-muted-foreground">{{ entry.repo.files.length }}</span>
          </summary>
          <div class="mt-0.5">
            <DiffFileTreeNode
              v-for="node in entry.nodes"
              :key="`${entry.repo.site_id}:${node.id}`"
              :node="node"
              :selected-path="selectedRepoId === entry.repo.site_id ? selectedPath : ''"
              @select="selectFile(entry.repo, $event)"
            />
          </div>
        </details>

        <div v-if="!totalFiles" class="px-3 py-10 text-center text-xs text-muted-foreground">
          当前分支没有文件改动
        </div>
      </div>
    </aside>

    <section class="flex min-h-[32rem] min-w-0 flex-1 flex-col bg-background">
      <div v-if="activeRepo && activeFile" class="shrink-0 border-b">
        <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
          <div class="flex min-w-0 items-center gap-2">
            <FileCode2 class="size-4 shrink-0 text-muted-foreground" />
            <span class="truncate font-mono-data text-xs font-medium" :title="activeFile.path">{{ activeFile.path }}</span>
            <span class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{{ statusLabel(activeFile.status) }}</span>
          </div>
          <div class="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <ChevronsUpDown class="size-3.5" />
            未改动区域可用中间箭头向上或向下展开
          </div>
        </div>
        <div class="grid grid-cols-2 border-t bg-muted/20 text-xs">
          <div class="min-w-0 border-r px-4 py-2">
            <span class="text-muted-foreground">修改前</span>
            <span class="ml-2 font-mono-data">{{ activeRepo.main_branch }}</span>
            <span v-if="fileDiff?.before_revision" class="ml-2 font-mono-data text-muted-foreground">{{ shortRevision(fileDiff.before_revision) }}</span>
          </div>
          <div class="min-w-0 px-4 py-2">
            <span class="text-muted-foreground">修改后</span>
            <span class="ml-2 font-mono-data">{{ activeRepo.branch_name }}</span>
            <span v-if="fileDiff?.after_revision" class="ml-2 font-mono-data text-muted-foreground">{{ shortRevision(fileDiff.after_revision) }}</span>
          </div>
        </div>
      </div>

      <div v-if="loading" class="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground" role="status">
        <Loader2 class="mr-2 size-4 animate-spin" />
        正在加载文件内容...
      </div>

      <div v-else-if="error" class="flex min-h-0 flex-1 items-center justify-center p-6 text-center">
        <div class="max-w-md rounded-lg border border-destructive/30 bg-destructive/5 p-5">
          <AlertTriangle class="mx-auto size-5 text-destructive" />
          <div class="mt-2 text-sm font-medium">无法显示文件对比</div>
          <div class="mt-1 text-xs leading-relaxed text-muted-foreground">{{ error }}</div>
          <Button v-if="activeRepo && selectedPath" variant="outline" size="sm" class="mt-4" @click="selectFile(activeRepo, selectedPath)">
            <RefreshCw class="size-4" />
            重试
          </Button>
        </div>
      </div>

      <div v-else-if="fileDiff?.binary" class="flex min-h-0 flex-1 items-center justify-center p-6 text-center">
        <div class="max-w-sm">
          <FileCode2 class="mx-auto size-7 text-muted-foreground/60" />
          <div class="mt-3 text-sm font-medium">二进制文件无法进行文本对比</div>
          <div class="mt-1 text-xs text-muted-foreground">{{ fileDiff.path }}</div>
        </div>
      </div>

      <div v-else-if="fileDiff" class="min-h-0 flex-1">
        <SideBySideDiffEditor
          :file-key="`${fileDiff.site_id}:${fileDiff.path}`"
          :original="fileDiff.before"
          :modified="fileDiff.after"
          :language="detectLanguage(fileDiff.path)"
          :theme="theme"
        />
      </div>

      <div v-else class="flex min-h-0 flex-1 items-center justify-center p-6 text-center text-sm text-muted-foreground">
        从左侧文件树选择文件查看修改前后对比
      </div>

      <div v-if="fileDiff?.truncated" class="shrink-0 border-t bg-warning/10 px-4 py-2 text-xs text-warning">
        文件内容超过 2 MB，当前仅展示前 2 MB。
      </div>
    </section>
  </div>
</template>
