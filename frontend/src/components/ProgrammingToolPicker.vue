<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'
import { programmingToolReason, type ProgrammingTool } from '@/api/programmingTools'

const props = withDefaults(defineProps<{
  modelValue: string
  tools: ProgrammingTool[]
  loading?: boolean
  disabled?: boolean
  disabledReason?: string
  ariaLabel?: string
}>(), {
  loading: false,
  disabled: false,
  disabledReason: '',
  ariaLabel: '编程工具',
})

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

function isDisabled(tool: ProgrammingTool) {
  return props.loading || props.disabled || !tool.available
}

function toolTitle(tool: ProgrammingTool) {
  if (props.disabled && props.disabledReason) return props.disabledReason
  return tool.available ? '' : programmingToolReason(tool)
}

function selectTool(tool: ProgrammingTool) {
  if (isDisabled(tool)) return
  emit('update:modelValue', tool.id)
}
</script>

<template>
  <div class="grid grid-cols-2 gap-2" role="group" :aria-label="ariaLabel" :aria-busy="loading">
    <button
      v-for="tool in tools"
      :key="tool.id"
      type="button"
      class="min-h-11 cursor-pointer rounded-md border px-2.5 py-2 text-xs font-medium transition-colors duration-200 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      :disabled="isDisabled(tool)"
      :aria-pressed="modelValue === tool.id"
      :aria-label="toolTitle(tool) ? `${tool.label}，${toolTitle(tool)}` : tool.label"
      :title="toolTitle(tool)"
      :class="[
        modelValue === tool.id
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-background text-foreground hover:bg-muted',
        isDisabled(tool) ? 'cursor-not-allowed opacity-50' : '',
      ]"
      @click="selectTool(tool)"
    >
      {{ tool.label }}
    </button>
    <div
      v-if="loading"
      role="status"
      aria-live="polite"
      class="col-span-2 flex min-h-11 items-center justify-center gap-2 rounded-md border border-dashed px-3 text-xs text-muted-foreground"
    >
      <Loader2 class="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      加载工具中…
    </div>
  </div>
</template>
