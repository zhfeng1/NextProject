<script setup lang="ts">
import { ref, watch } from 'vue'
import { projectsAPI } from '@/api/projects'
import { FolderOpen, Folder, File, ChevronRight, ChevronDown } from 'lucide-vue-next'
import TreeNodeItem from './TreeNodeItem.vue'

export interface TreeNode {
  name: string
  path: string
  type: 'directory' | 'file'
  size?: number | null
  children: TreeNode[]
  loaded: boolean
  loading: boolean
  expanded: boolean
}

const props = defineProps<{
  projectId: string
  repoId: string
  repoName: string
}>()

const emit = defineEmits<{
  (e: 'open-file', payload: { path: string; repoId: string; repoName: string }): void
}>()

const rootNodes = ref<TreeNode[]>([])
const rootLoading = ref(false)
const loadError = ref('')

async function fetchChildren(parentPath: string): Promise<TreeNode[]> {
  const res = await projectsAPI.listRepoFiles(props.projectId, props.repoId, parentPath)
  return (res.entries || []).map((e: any) => ({
    name: e.name,
    path: e.path,
    type: e.type,
    size: e.size,
    children: [],
    loaded: false,
    loading: false,
    expanded: false,
  }))
}

async function loadRoot() {
  rootLoading.value = true
  loadError.value = ''
  try {
    rootNodes.value = await fetchChildren('')
  } catch {
    loadError.value = '加载文件列表失败'
  } finally {
    rootLoading.value = false
  }
}

async function handleClickNode(node: TreeNode) {
  if (node.type === 'directory') {
    if (node.expanded) {
      node.expanded = false
    } else {
      node.expanded = true
      if (!node.loaded) {
        node.loading = true
        try {
          node.children = await fetchChildren(node.path)
          node.loaded = true
        } catch {
          node.children = []
        } finally {
          node.loading = false
        }
      }
    }
  } else {
    emit('open-file', {
      path: node.path,
      repoId: props.repoId,
      repoName: props.repoName,
    })
  }
}

watch(() => props.repoId, () => {
  rootNodes.value = []
  loadRoot()
}, { immediate: true })
</script>

<template>
  <div class="text-sm select-none">
    <div v-if="rootLoading" class="p-2 text-muted-foreground">加载中...</div>
    <div v-else-if="loadError" class="p-2 text-destructive">{{ loadError }}</div>
    <div v-else-if="rootNodes.length === 0" class="p-2 text-muted-foreground">空目录</div>
    <template v-else>
      <TreeNodeItem
        v-for="node in rootNodes"
        :key="node.path"
        :node="node"
        :depth="0"
        @click-node="handleClickNode"
      />
    </template>
  </div>
</template>
