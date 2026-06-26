<script setup lang="ts">
import type { Site } from '@/types/models'

defineProps<{
  repos: Site[]
  activeRepoId: string
}>()

const emit = defineEmits<{
  (e: 'select', repoId: string): void
  (e: 'viewBuildLog', repo: Site): void
}>()
</script>

<template>
  <div class="flex shrink-0 overflow-x-auto border-b bg-muted/20">
    <div
      v-for="repo in repos"
      :key="repo.site_id"
      class="flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors"
      :class="activeRepoId === repo.site_id
        ? 'border-primary font-medium text-foreground'
        : 'border-transparent text-muted-foreground hover:text-foreground'"
    >
      <button
        type="button"
        class="min-w-0 truncate"
        @click="emit('select', repo.site_id)"
      >
        {{ repo.name }}
      </button>
      <button
        v-if="repo.status === 'building'"
        type="button"
        class="flex items-center gap-1 text-xs text-warning hover:underline"
        @click="emit('viewBuildLog', repo)"
      >
        <span class="status-dot" data-tone="warning" data-pulse="true" />
        克隆中
      </button>
    </div>
  </div>
</template>
