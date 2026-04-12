<script setup lang="ts">
import type { Site } from '@/types/models'

const props = defineProps<{
  repos: Site[]
  activeRepoId: string
}>()

const emit = defineEmits<{
  (e: 'select', repoId: string): void
}>()
</script>

<template>
  <div class="flex border-b overflow-x-auto">
    <button
      v-for="repo in repos"
      :key="repo.site_id"
      class="px-4 py-2 text-sm whitespace-nowrap border-b-2 transition-colors"
      :class="activeRepoId === repo.site_id
        ? 'border-primary text-primary font-medium'
        : 'border-transparent text-muted-foreground hover:text-foreground'"
      @click="emit('select', repo.site_id)"
    >
      {{ repo.name }}
      <span
        v-if="repo.status === 'building'"
        class="ml-1 text-xs text-yellow-500"
      >克隆中...</span>
    </button>
  </div>
</template>
