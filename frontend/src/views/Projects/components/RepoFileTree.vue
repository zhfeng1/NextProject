<script setup lang="ts">
import { ref, watch } from 'vue'
import { projectsAPI } from '@/api/projects'
import { FolderOpen, File, ChevronRight, ChevronDown } from 'lucide-vue-next'

interface FileEntry {
  name: string
  path: string
  type: 'directory' | 'file'
  size?: number | null
}

const props = defineProps<{
  projectId: string
  repoId: string
  repoName: string
}>()

const emit = defineEmits<{
  (e: 'open-file', payload: { path: string; repoId: string; repoName: string }): void
}>()

const entries = ref<FileEntry[]>([])
const currentPath = ref('')
const loading = ref(false)
const expandedDirs = ref<Set<string>>(new Set())

async function loadFiles(path = '') {
  loading.value = true
  try {
    const res = await projectsAPI.listRepoFiles(props.projectId, props.repoId, path)
    entries.value = res.entries
    currentPath.value = path
  } finally {
    loading.value = false
  }
}

function handleClick(entry: FileEntry) {
  if (entry.type === 'directory') {
    if (expandedDirs.value.has(entry.path)) {
      expandedDirs.value.delete(entry.path)
    } else {
      expandedDirs.value.add(entry.path)
      loadFiles(entry.path)
    }
  } else {
    emit('open-file', {
      path: entry.path,
      repoId: props.repoId,
      repoName: props.repoName,
    })
  }
}

// 当仓库切换时重新加载根目录
watch(() => props.repoId, () => {
  entries.value = []
  expandedDirs.value.clear()
  loadFiles('')
}, { immediate: true })
</script>

<template>
  <div class="text-sm">
    <div v-if="loading" class="p-2 text-muted-foreground">加载中...</div>
    <div v-else>
      <div
        v-for="entry in entries"
        :key="entry.path"
        class="flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-accent rounded"
        @click="handleClick(entry)"
      >
        <component
          :is="entry.type === 'directory' ? FolderOpen : File"
          class="w-4 h-4 text-muted-foreground flex-shrink-0"
        />
        <span class="truncate">{{ entry.name }}</span>
      </div>
    </div>
  </div>
</template>
