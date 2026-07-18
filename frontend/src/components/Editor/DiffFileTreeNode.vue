<script lang="ts">
export interface DiffTreeNodeData {
  id: string
  name: string
  path: string
  kind: 'folder' | 'file'
  status?: string
  children?: DiffTreeNodeData[]
}
</script>

<script setup lang="ts">
import { ref } from 'vue'
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen } from 'lucide-vue-next'

defineOptions({ name: 'DiffFileTreeNode' })

const props = withDefaults(defineProps<{
  node: DiffTreeNodeData
  selectedPath?: string
  depth?: number
}>(), {
  selectedPath: '',
  depth: 0,
})

const emit = defineEmits<{
  select: [path: string]
}>()

const expanded = ref(true)

function statusClass(status = '') {
  if (status.startsWith('A')) return 'bg-success/10 text-success'
  if (status.startsWith('D')) return 'bg-destructive/10 text-destructive'
  if (status.startsWith('R')) return 'bg-primary/10 text-primary'
  return 'bg-warning/10 text-warning'
}
</script>

<template>
  <div>
    <button
      v-if="node.kind === 'folder'"
      type="button"
      class="flex min-h-8 w-full cursor-pointer items-center gap-1.5 rounded px-2 text-left text-xs text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :style="{ paddingLeft: `${8 + depth * 14}px` }"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <ChevronDown v-if="expanded" class="size-3.5 shrink-0" />
      <ChevronRight v-else class="size-3.5 shrink-0" />
      <FolderOpen v-if="expanded" class="size-3.5 shrink-0 text-primary/70" />
      <Folder v-else class="size-3.5 shrink-0 text-primary/70" />
      <span class="truncate">{{ node.name }}</span>
    </button>

    <button
      v-else
      type="button"
      class="flex min-h-8 w-full cursor-pointer items-center gap-1.5 rounded px-2 text-left text-xs transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="selectedPath === node.path ? 'bg-primary/10 text-foreground' : 'text-muted-foreground'"
      :style="{ paddingLeft: `${30 + depth * 14}px` }"
      :aria-current="selectedPath === node.path ? 'true' : undefined"
      :title="node.path"
      @click="emit('select', node.path)"
    >
      <FileCode2 class="size-3.5 shrink-0" />
      <span class="min-w-0 flex-1 truncate">{{ node.name }}</span>
      <span
        class="min-w-5 rounded px-1 py-0.5 text-center font-mono-data text-[10px] font-semibold"
        :class="statusClass(node.status)"
      >{{ node.status || 'M' }}</span>
    </button>

    <div v-if="node.kind === 'folder' && expanded">
      <DiffFileTreeNode
        v-for="child in node.children || []"
        :key="child.id"
        :node="child"
        :selected-path="selectedPath"
        :depth="depth + 1"
        @select="emit('select', $event)"
      />
    </div>
  </div>
</template>
