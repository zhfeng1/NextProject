<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { AvatarFallback } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  delayMs?: number
}>()
</script>

<template>
  <AvatarFallback
    :delay-ms="props.delayMs"
    :class="cn('flex size-full items-center justify-center bg-muted', props.class)"
  >
    <slot />
  </AvatarFallback>
</template>
