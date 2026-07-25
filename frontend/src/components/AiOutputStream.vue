<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  content?: string
  emptyText?: string
  active?: boolean
  compact?: boolean
  variant?: 'default' | 'terminal'
}>(), {
  content: '',
  emptyText: '等待编程工具输出面向用户的说明…',
  active: false,
  compact: false,
  variant: 'default',
})

const blocks = computed(() => {
  const normalized = String(props.content || '').replace(/\r\n?/g, '\n').trim()
  if (!normalized) return []
  return normalized
    .split('\u001e')
    .map(block => block.replace(/^\n+|\n+$/g, ''))
    .filter(Boolean)
})

const isTerminal = computed(() => props.variant === 'terminal')
</script>

<template>
  <div role="status" aria-live="polite" aria-atomic="false" class="min-w-0">
    <ol v-if="blocks.length" class="space-y-0">
      <li
        v-for="(block, index) in blocks"
        :key="index"
        class="relative grid min-w-0 grid-cols-[1rem_minmax(0,1fr)] gap-2.5"
        :class="index === blocks.length - 1 ? '' : compact ? 'pb-3' : 'pb-4'"
      >
        <div aria-hidden="true" class="relative flex justify-center">
          <span
            class="relative z-10 mt-2 size-2 rounded-full border-2"
            :class="[
              index === blocks.length - 1 && active
                ? 'animate-pulse border-primary bg-primary'
                : isTerminal
                  ? 'border-zinc-500 bg-zinc-800'
                  : 'border-muted-foreground/45 bg-background',
            ]"
          />
          <span
            v-if="index < blocks.length - 1"
            class="absolute bottom-[-0.5rem] top-3 w-px"
            :class="isTerminal ? 'bg-zinc-700' : 'bg-border'"
          />
        </div>

        <article
          class="min-w-0 rounded-lg border"
          :class="[
            compact ? 'px-3 py-2.5' : 'px-3.5 py-3',
            isTerminal
              ? 'border-zinc-800 bg-zinc-900/70 text-zinc-200'
              : 'border-border/80 bg-background/80 text-foreground',
          ]"
        >
          <div
            class="whitespace-pre-wrap break-words"
            :class="compact ? 'text-xs leading-relaxed' : 'text-sm leading-6'"
          >{{ block }}</div>
        </article>
      </li>
    </ol>

    <div
      v-else
      class="rounded-lg border border-dashed px-4 py-8 text-center"
      :class="isTerminal ? 'border-zinc-800 text-zinc-600' : 'border-border text-muted-foreground'"
    >
      <span
        v-if="active"
        aria-hidden="true"
        class="mr-2 inline-block size-2 animate-pulse rounded-full bg-primary align-middle"
      />
      <span :class="compact ? 'text-xs' : 'text-sm'">{{ emptyText }}</span>
    </div>
  </div>
</template>
