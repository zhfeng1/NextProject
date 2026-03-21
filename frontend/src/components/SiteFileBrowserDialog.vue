<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { sitesAPI } from '@/api/sites'
import { ArrowLeft, FileText, FolderTree, RefreshCw, X } from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
  siteId: string
  siteName?: string
  refreshKey?: number
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const fileEntries = ref<Array<{ name: string; path: string; type: 'directory' | 'file'; size?: number | null }>>([])
const fileBrowserPath = ref('')
const fileParentPath = ref('')
const fileLoading = ref(false)
const selectedFilePath = ref('')
const selectedFileContent = ref('')
const selectedFileBinary = ref(false)
const selectedFileTruncated = ref(false)
const selectedFileSize = ref(0)
const fileContentLoading = ref(false)

const title = computed(() => props.siteName || props.siteId || '文件浏览')

function closeDialog() {
  emit('update:open', false)
}

function resetBrowser() {
  fileEntries.value = []
  fileBrowserPath.value = ''
  fileParentPath.value = ''
  selectedFilePath.value = ''
  selectedFileContent.value = ''
  selectedFileBinary.value = false
  selectedFileTruncated.value = false
  selectedFileSize.value = 0
}

function formatFileSize(size?: number | null) {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

async function loadFileList(path = fileBrowserPath.value) {
  if (!props.siteId) return
  fileLoading.value = true
  try {
    const res = await sitesAPI.listFiles(props.siteId, path)
    fileEntries.value = res.entries || []
    fileBrowserPath.value = res.current_path || ''
    fileParentPath.value = res.parent_path || ''
  } catch {
    fileEntries.value = []
  } finally {
    fileLoading.value = false
  }
}

async function openFile(path: string) {
  if (!props.siteId) return
  fileContentLoading.value = true
  try {
    const res = await sitesAPI.getFileContent(props.siteId, path)
    selectedFilePath.value = res.path || path
    selectedFileContent.value = res.content || ''
    selectedFileBinary.value = !!res.binary
    selectedFileTruncated.value = !!res.truncated
    selectedFileSize.value = Number(res.size || 0)
  } finally {
    fileContentLoading.value = false
  }
}

async function navigateFileEntry(entry: { path: string; type: 'directory' | 'file' }) {
  if (entry.type === 'directory') {
    await loadFileList(entry.path)
    return
  }
  await openFile(entry.path)
}

async function refreshFileBrowser(reloadSelected = true) {
  await loadFileList(fileBrowserPath.value)
  if (reloadSelected && selectedFilePath.value) {
    await openFile(selectedFilePath.value)
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) {
    closeDialog()
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    if (!fileEntries.value.length) {
      await loadFileList('')
    } else {
      await refreshFileBrowser(true)
    }
  }
)

watch(
  () => props.siteId,
  async () => {
    resetBrowser()
    if (props.open && props.siteId) {
      await loadFileList('')
    }
  }
)

watch(
  () => props.refreshKey,
  async (next, prev) => {
    if (!props.open || next === prev) return
    await refreshFileBrowser(true)
  }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/70 p-4 backdrop-blur-sm"
      @click.self="closeDialog"
    >
      <div class="flex h-[min(90vh,62rem)] w-[min(95vw,96rem)] flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl">
        <div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3 shrink-0">
          <div class="min-w-0">
            <div class="truncate text-sm font-medium text-zinc-100">文件浏览</div>
            <div class="mt-1 truncate text-xs text-zinc-400">
              {{ title }}
              <span class="mx-1">·</span>
              <span class="font-mono">/{{ fileBrowserPath || '' }}</span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              class="h-8 px-2 text-xs text-zinc-300 hover:text-zinc-100"
              @click="refreshFileBrowser(true)"
            >
              <RefreshCw class="mr-1 h-4 w-4" />
              刷新
            </Button>
            <Button
              size="sm"
              variant="ghost"
              class="h-8 px-2 text-xs text-zinc-400 hover:text-zinc-100"
              @click="closeDialog"
            >
              <X class="mr-1 h-4 w-4" />
              关闭
            </Button>
          </div>
        </div>

        <div class="grid min-h-0 flex-1 grid-cols-[20rem_minmax(0,1fr)]">
          <div class="flex min-h-0 flex-col border-r border-zinc-800 bg-zinc-900/80">
            <div class="border-b border-zinc-800 px-4 py-3 text-xs font-medium text-zinc-300">
              文件树
            </div>
            <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2">
              <button
                v-if="fileBrowserPath"
                type="button"
                class="mb-1 flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs text-zinc-300 transition-colors hover:bg-zinc-800/80 hover:text-zinc-100"
                @click="loadFileList(fileParentPath)"
              >
                <span class="shrink-0 text-zinc-400">
                  <ArrowLeft class="h-4 w-4" />
                </span>
                <span class="min-w-0 flex-1 truncate font-mono">..</span>
                <span class="shrink-0 text-[10px] text-zinc-500">返回上级</span>
              </button>
              <button
                v-for="entry in fileEntries"
                :key="entry.path"
                type="button"
                class="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs text-zinc-200 transition-colors hover:bg-zinc-800/80"
                :class="selectedFilePath === entry.path ? 'bg-zinc-800 text-zinc-50' : ''"
                @click="navigateFileEntry(entry)"
              >
                <span class="shrink-0 text-zinc-400">
                  <FolderTree v-if="entry.type === 'directory'" class="h-4 w-4" />
                  <FileText v-else class="h-4 w-4" />
                </span>
                <span class="min-w-0 flex-1 truncate font-mono">{{ entry.name }}</span>
                <span v-if="entry.type === 'file' && entry.size" class="shrink-0 text-[10px] text-zinc-500">
                  {{ formatFileSize(entry.size) }}
                </span>
              </button>
              <div v-if="fileLoading" class="px-2 py-6 text-center text-xs text-zinc-500">加载目录中...</div>
              <div v-else-if="!fileEntries.length" class="px-2 py-6 text-center text-xs text-zinc-500">当前目录为空</div>
            </div>
          </div>

          <div class="flex min-h-0 flex-col">
            <div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3 text-xs">
              <div class="min-w-0 truncate font-mono text-zinc-200">
                {{ selectedFilePath || '请选择左侧文件查看内容' }}
              </div>
              <div v-if="selectedFilePath" class="ml-3 shrink-0 text-zinc-500">
                {{ formatFileSize(selectedFileSize) }}
              </div>
            </div>
            <div class="min-h-0 flex-1 overflow-auto bg-zinc-950 px-4 py-4 font-mono text-xs leading-relaxed text-zinc-200">
              <div v-if="fileContentLoading" class="text-zinc-500">加载文件内容中...</div>
              <div v-else-if="selectedFileBinary" class="text-zinc-500">该文件为二进制文件，暂不支持文本预览。</div>
              <div v-else-if="selectedFilePath">
                <div v-if="selectedFileTruncated" class="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
                  文件过大，当前仅展示前 256 KB 预览。
                </div>
                <pre class="whitespace-pre-wrap break-all">{{ selectedFileContent }}</pre>
              </div>
              <div v-else class="pt-10 text-center text-zinc-500">点击左侧文件即可查看内容。</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
