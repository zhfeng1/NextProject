<script setup lang="ts">
import { FolderOpen, Folder, File, ChevronRight, ChevronDown } from 'lucide-vue-next'

export interface TreeNode {
  name: string
  path: string
  type: 'directory' | 'file'
  children: TreeNode[]
  loaded: boolean
  loading: boolean
  expanded: boolean
}

defineProps<{
  node: TreeNode
  depth: number
}>()

const emit = defineEmits<{
  (e: 'click-node', node: TreeNode): void
}>()
</script>

<template>
  <div>
    <div
      class="flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-accent rounded"
      :style="{ paddingLeft: `${depth * 16 + 4}px` }"
      @click="emit('click-node', node)"
    >
      <template v-if="node.type === 'directory'">
        <ChevronDown v-if="node.expanded" class="w-3 h-3 text-muted-foreground flex-shrink-0" />
        <ChevronRight v-else class="w-3 h-3 text-muted-foreground flex-shrink-0" />
        <FolderOpen v-if="node.expanded" class="w-4 h-4 text-muted-foreground flex-shrink-0" />
        <Folder v-else class="w-4 h-4 text-muted-foreground flex-shrink-0" />
      </template>
      <template v-else>
        <span class="w-3 h-3 inline-block flex-shrink-0" />
        <File class="w-4 h-4 text-muted-foreground flex-shrink-0" />
      </template>
      <span class="truncate">{{ node.name }}</span>
    </div>
    <template v-if="node.type === 'directory' && node.expanded">
      <div v-if="node.loading" class="text-xs text-muted-foreground" :style="{ paddingLeft: `${(depth + 1) * 16 + 4}px` }">
        加载中...
      </div>
      <template v-else>
        <TreeNodeItem
          v-for="child in node.children"
          :key="child.path"
          :node="child"
          :depth="depth + 1"
          @click-node="(n: TreeNode) => emit('click-node', n)"
        />
      </template>
    </template>
  </div>
</template>

<script lang="ts">
export default { name: 'TreeNodeItem' }
</script>
