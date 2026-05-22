<script setup lang="ts">
import { ref, watch } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import TaskLogs from '@/components/TaskLogs.vue'
import { tasksAPI } from '@/api/tasks'

const props = defineProps<{
  open: boolean
  siteId: string
  siteName?: string
}>()

const emit = defineEmits<{
  'update:open': [boolean]
}>()

const taskId = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function load() {
  if (!props.open || !props.siteId) return
  loading.value = true
  errorMsg.value = ''
  taskId.value = ''
  try {
    const res = await tasksAPI.listBySite(props.siteId, {
      task_type: 'clone_repo',
      limit: 1,
    })
    const t = res.tasks?.[0]
    if (!t) {
      errorMsg.value = '尚未找到构建任务，可能还在排队，稍后再试'
    } else {
      taskId.value = t.id
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || '加载构建任务失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.open, props.siteId], load, { immediate: true })
</script>

<template>
  <Dialog :open="open" @update:open="(v: boolean) => emit('update:open', v)">
    <DialogContent class="max-w-3xl p-0">
      <DialogHeader class="px-6 pt-6 pb-2">
        <DialogTitle>构建日志 — {{ siteName || siteId }}</DialogTitle>
      </DialogHeader>
      <div class="px-6 pb-6">
        <div v-if="loading" class="py-12 text-center text-sm text-muted-foreground">
          加载构建任务中…
        </div>
        <div v-else-if="errorMsg" class="py-12 text-center text-sm text-destructive">
          {{ errorMsg }}
          <div class="mt-3">
            <button type="button" class="text-xs underline text-muted-foreground" @click="load">重试</button>
          </div>
        </div>
        <div v-else-if="taskId" class="h-[60vh]">
          <TaskLogs :task-id="taskId" />
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
