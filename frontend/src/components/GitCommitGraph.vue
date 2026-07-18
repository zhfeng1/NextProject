<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  GitBranch,
  GitCommitHorizontal,
  Loader2,
  RefreshCw,
  RotateCcw,
  Tag,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import type { GitGraph, GitGraphCommit, GitGraphLabel } from '@/api/git'

const props = withDefaults(defineProps<{
  graph: GitGraph | null
  loading?: boolean
  error?: string
  rollbackPending?: boolean
  rollbackDisabledReason?: string
  emptyText?: string
}>(), {
  loading: false,
  error: '',
  rollbackPending: false,
  rollbackDisabledReason: '',
  emptyText: '当前分支还没有可展示的提交',
})

const emit = defineEmits<{
  retry: []
  rollback: [commit: GitGraphCommit]
}>()

type GraphSegment = {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
  lane: number
}

const ROW_HEIGHT = 52
const NODE_Y = ROW_HEIGHT / 2
const selectedSha = ref('')
const rollbackDialogOpen = ref(false)
const rollbackConfirmation = ref('')

const commits = computed(() => props.graph?.commits || [])
const laneCount = computed(() => Math.max(1, props.graph?.lanes || 1))
const graphWidth = computed(() => Math.min(172, Math.max(44, laneCount.value * 20 + 12)))
const laneGap = computed(() => laneCount.value <= 1 ? 0 : (graphWidth.value - 24) / (laneCount.value - 1))
const laneX = (lane: number) => laneCount.value <= 1 ? graphWidth.value / 2 : 12 + Math.max(0, lane) * laneGap.value
const selectedCommit = computed(() => commits.value.find(commit => commit.sha === selectedSha.value) || null)
const confirmationPhrase = computed(() => selectedCommit.value ? `回滚 ${selectedCommit.value.short_sha}` : '')
const canConfirmRollback = computed(() => (
  Boolean(selectedCommit.value)
  && rollbackConfirmation.value.trim() === confirmationPhrase.value
  && !props.rollbackPending
))

const laneColors = [
  'hsl(var(--primary))',
  'hsl(var(--success))',
  'hsl(var(--warning))',
  'hsl(var(--destructive))',
  'hsl(var(--muted-foreground))',
]

function laneColor(lane: number) {
  return laneColors[Math.abs(lane) % laneColors.length]
}

const rowSegments = computed(() => {
  const indexBySha = new Map(commits.value.map((commit, index) => [commit.sha, index]))
  return commits.value.map((_, rowIndex) => {
    const segments: GraphSegment[] = []
    const seen = new Set<string>()

    commits.value.forEach((child, childIndex) => {
      if (childIndex > rowIndex) return
      const parentLanes = child.parent_lanes?.length
        ? child.parent_lanes
        : child.parents.map(parentSha => ({ parentSha, sha: parentSha, lane: child.lane }))

      parentLanes.forEach((parent, parentOffset) => {
        const parentIndex = indexBySha.get(parent.sha)
        const edgeEnd = parentIndex === undefined ? childIndex + 1 : parentIndex
        if (rowIndex > edgeEnd) return

        let x1 = laneX(parent.lane)
        let x2 = x1
        let y1 = 0
        let y2 = ROW_HEIGHT

        if (rowIndex === childIndex) {
          x1 = laneX(child.lane)
          x2 = laneX(parent.lane)
          y1 = NODE_Y
          y2 = ROW_HEIGHT
        } else if (rowIndex === edgeEnd) {
          y2 = NODE_Y
        }

        const geometry = `${x1}:${y1}:${x2}:${y2}:${parent.lane}`
        if (seen.has(geometry)) return
        seen.add(geometry)
        segments.push({
          key: `${child.sha}-${parent.sha}-${rowIndex}-${parentOffset}`,
          x1,
          y1,
          x2,
          y2,
          lane: parent.lane,
        })
      })
    })

    return segments
  })
})

watch(() => props.graph?.head_sha, () => {
  selectedSha.value = ''
})

watch(() => props.rollbackPending, (pending, wasPending) => {
  if (wasPending && !pending) {
    rollbackDialogOpen.value = false
    rollbackConfirmation.value = ''
    selectedSha.value = ''
  }
})

function displayDate(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 19).replace('T', ' ')
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function labelKind(label: GitGraphLabel) {
  if (label.type === 'tag') return 'Tag'
  if (label.type === 'remote' || label.type === 'remote_branch') return '远端'
  if (label.type === 'head' || label.current) return 'HEAD'
  return '分支'
}

function labelClass(label: GitGraphLabel) {
  if (label.type === 'tag') return 'border-warning/35 bg-warning/10 text-warning'
  if (label.type === 'remote' || label.type === 'remote_branch') return 'border-success/35 bg-success/10 text-success'
  if (label.type === 'head' || label.current) return 'border-primary/35 bg-primary/10 text-primary'
  return 'border-border bg-muted/60 text-foreground'
}

function openRollbackDialog() {
  if (!selectedCommit.value || selectedCommit.value.current || props.rollbackDisabledReason) return
  rollbackConfirmation.value = ''
  rollbackDialogOpen.value = true
}

function confirmRollback() {
  if (!selectedCommit.value || !canConfirmRollback.value) return
  emit('rollback', selectedCommit.value)
}
</script>

<template>
  <div class="overflow-hidden rounded-lg border bg-card">
    <div v-if="loading" role="status" aria-live="polite" class="space-y-2 p-3" aria-label="正在加载提交历史">
      <div v-for="index in 6" :key="index" class="flex h-12 items-center gap-3">
        <Skeleton class="h-8 w-16 shrink-0" />
        <div class="min-w-0 flex-1 space-y-2">
          <Skeleton class="h-3.5 w-3/5" />
          <Skeleton class="h-3 w-2/5" />
        </div>
      </div>
    </div>

    <div v-else-if="error" role="alert" class="flex min-h-40 flex-col items-center justify-center gap-3 px-5 py-8 text-center">
      <AlertTriangle class="size-6 text-destructive" />
      <div>
        <p class="text-sm font-medium">提交历史加载失败</p>
        <p class="mt-1 max-w-lg break-words text-xs leading-relaxed text-muted-foreground">{{ error }}</p>
      </div>
      <Button variant="outline" size="sm" @click="emit('retry')">
        <RefreshCw class="size-4" />
        重新加载
      </Button>
    </div>

    <div v-else-if="!commits.length" class="flex min-h-40 flex-col items-center justify-center px-5 py-8 text-center">
      <GitCommitHorizontal class="size-7 text-muted-foreground/50" />
      <p class="mt-3 text-sm text-muted-foreground">{{ emptyText }}</p>
    </div>

    <template v-else>
      <div class="flex flex-wrap items-start justify-between gap-3 border-b bg-muted/20 px-3 py-2.5 sm:px-4">
        <div class="min-w-0">
          <div class="flex min-w-0 items-center gap-2 text-sm font-medium">
            <GitBranch class="size-4 shrink-0 text-muted-foreground" />
            <span class="truncate font-mono-data">{{ graph?.branch }}</span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground">
            {{ graph?.total }} 个提交<span v-if="graph?.default_branch && graph.default_branch !== graph.branch"> · 主分支 {{ graph.default_branch }}</span>
          </div>
        </div>
        <div v-if="selectedCommit" class="flex min-w-0 flex-wrap items-center justify-end gap-2">
          <span class="font-mono-data text-xs text-muted-foreground">已选择 {{ selectedCommit.short_sha }}</span>
          <Button
            variant="destructive"
            size="sm"
            :disabled="selectedCommit.current || Boolean(rollbackDisabledReason) || rollbackPending"
            :title="selectedCommit.current ? '当前分支已经位于此提交' : rollbackDisabledReason"
            @click="openRollbackDialog"
          >
            <Loader2 v-if="rollbackPending" class="size-4 animate-spin" />
            <RotateCcw v-else class="size-4" />
            回滚到此提交
          </Button>
        </div>
      </div>

      <div :aria-label="`${graph?.name || '仓库'} ${graph?.branch || ''} 提交树`" class="divide-y">
        <button
          v-for="(commit, index) in commits"
          :key="commit.sha"
          type="button"
          class="grid min-h-[52px] w-full min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-stretch text-left transition-colors hover:bg-muted/35 focus-visible:relative focus-visible:z-10"
          :class="selectedSha === commit.sha ? 'bg-primary/5 ring-1 ring-inset ring-primary/35' : ''"
          :aria-pressed="selectedSha === commit.sha"
          :aria-label="`${commit.short_sha}，${commit.subject}，作者 ${commit.author_name}，${displayDate(commit.authored_at)}`"
          @click="selectedSha = selectedSha === commit.sha ? '' : commit.sha"
        >
          <span class="relative block shrink-0 overflow-hidden" :style="{ width: `${graphWidth}px`, height: `${ROW_HEIGHT}px` }" aria-hidden="true">
            <svg :width="graphWidth" :height="ROW_HEIGHT" class="absolute inset-0">
              <line
                v-for="segment in rowSegments[index]"
                :key="segment.key"
                :x1="segment.x1"
                :y1="segment.y1"
                :x2="segment.x2"
                :y2="segment.y2"
                :stroke="laneColor(segment.lane)"
                stroke-width="2"
                stroke-linecap="round"
                opacity="0.72"
              />
              <circle
                :cx="laneX(commit.lane)"
                :cy="NODE_Y"
                :r="commit.current ? 6 : 4.5"
                :fill="commit.current ? laneColor(commit.lane) : 'hsl(var(--card))'"
                :stroke="laneColor(commit.lane)"
                stroke-width="2.5"
              />
              <circle
                v-if="commit.current"
                :cx="laneX(commit.lane)"
                :cy="NODE_Y"
                r="9"
                fill="none"
                :stroke="laneColor(commit.lane)"
                stroke-width="1"
                opacity="0.35"
              />
            </svg>
          </span>

          <span class="flex min-w-0 flex-col justify-center gap-1 py-2 pr-3 sm:pr-4">
            <span class="flex min-w-0 flex-wrap items-center gap-1.5">
              <span class="min-w-0 break-words text-sm font-medium leading-snug">{{ commit.subject || '(无提交说明)' }}</span>
              <span
                v-for="label in commit.labels"
                :key="`${label.type}-${label.full_name || label.name}`"
                class="inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-0.5 font-mono-data text-[10px] font-medium leading-none"
                :class="labelClass(label)"
                :title="label.full_name || label.name"
              >
                <Tag v-if="label.type === 'tag'" class="size-2.5 shrink-0" />
                <GitBranch v-else class="size-2.5 shrink-0" />
                <span class="font-sans text-[9px] font-semibold uppercase tracking-wide">{{ labelKind(label) }}</span>
                <span class="max-w-48 truncate">{{ label.name }}</span>
              </span>
              <span v-if="commit.current && !commit.labels.some(label => label.current || label.type === 'head')" class="rounded border border-primary/35 bg-primary/10 px-1.5 py-0.5 font-mono-data text-[10px] font-semibold text-primary">HEAD</span>
            </span>
            <span class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
              <span class="font-mono-data font-medium text-foreground/75">{{ commit.short_sha }}</span>
              <span class="truncate">{{ commit.author_name || '未知作者' }}</span>
              <span class="tabular">{{ displayDate(commit.authored_at || commit.committed_at) }}</span>
            </span>
          </span>
        </button>
      </div>

      <div v-if="selectedCommit" class="border-t bg-muted/20 px-3 py-3 sm:px-4">
        <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="font-mono-data text-xs font-semibold">{{ selectedCommit.sha }}</div>
            <p v-if="selectedCommit.message && selectedCommit.message.trim() !== selectedCommit.subject.trim()" class="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
              {{ selectedCommit.message }}
            </p>
          </div>
          <span v-if="selectedCommit.current" class="shrink-0 rounded border border-success/35 bg-success/10 px-2 py-1 text-xs font-medium text-success">当前 HEAD</span>
          <span v-else-if="rollbackDisabledReason" class="max-w-sm shrink-0 text-xs leading-relaxed text-muted-foreground">{{ rollbackDisabledReason }}</span>
        </div>
      </div>

      <div v-if="graph?.truncated" class="border-t bg-warning/10 px-3 py-2 text-xs text-warning sm:px-4">
        提交较多，当前展示最新 {{ commits.length }} 条记录。
      </div>
    </template>
  </div>

  <Dialog v-model:open="rollbackDialogOpen">
    <DialogContent class="sm:max-w-[540px]">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2 text-destructive">
          <AlertTriangle class="size-5" />
          回滚分支到指定提交
        </DialogTitle>
        <DialogDescription>
          这是破坏性操作，请核对分支、提交和影响后再继续。
        </DialogDescription>
      </DialogHeader>

      <div v-if="selectedCommit" class="space-y-4">
        <dl class="grid gap-2 rounded-md border bg-muted/25 p-3 text-sm sm:grid-cols-[5rem_minmax(0,1fr)]">
          <dt class="text-muted-foreground">仓库</dt>
          <dd class="min-w-0 truncate font-medium">{{ graph?.name }}</dd>
          <dt class="text-muted-foreground">分支</dt>
          <dd class="break-all font-mono-data font-medium">{{ graph?.branch }}</dd>
          <dt class="text-muted-foreground">Commit</dt>
          <dd class="break-all font-mono-data">{{ selectedCommit.sha }}</dd>
          <dt class="text-muted-foreground">提交说明</dt>
          <dd class="break-words">{{ selectedCommit.subject || '(无提交说明)' }}</dd>
        </dl>

        <div role="alert" class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm leading-relaxed text-destructive">
          分支指针和服务器工作区将重置到该 Commit；此 Commit 之后的提交将不再属于当前分支。远端分支不会自动改写。
        </div>

        <div class="space-y-3">
          <div class="rounded-md border bg-muted/40 px-3 py-2.5">
            <p class="text-xs font-medium text-muted-foreground">请完整输入以下确认短语</p>
            <p class="mt-1.5 break-all font-mono-data text-base font-semibold text-foreground">
              {{ confirmationPhrase }}
            </p>
          </div>

          <div class="space-y-2">
            <Label for="rollback-confirmation">确认短语</Label>
            <Input
              id="rollback-confirmation"
              v-model="rollbackConfirmation"
              class="h-11 font-mono-data"
              :placeholder="`请输入完整短语：${confirmationPhrase}`"
              aria-describedby="rollback-confirmation-help"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              :disabled="rollbackPending"
              @keydown.enter.prevent="confirmRollback"
            />
            <p id="rollback-confirmation-help" class="text-xs leading-relaxed text-muted-foreground">
              需要输入“回滚”、一个空格和提交号，且必须与上方完整内容完全一致。
            </p>
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="rollbackPending" @click="rollbackDialogOpen = false">取消</Button>
        <Button variant="destructive" :disabled="!canConfirmRollback" @click="confirmRollback">
          <Loader2 v-if="rollbackPending" class="size-4 animate-spin" />
          <RotateCcw v-else class="size-4" />
          {{ rollbackPending ? '回滚中' : '确认回滚' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
