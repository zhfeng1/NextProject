<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
} from 'echarts/components'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Monitor, Clock, Cpu, MemoryStick } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

use([
  CanvasRenderer,
  LineChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
])

const { theme } = useTheme()

const metrics = ref({
  activeSites: 0,
  runningTasks: 0,
  cpuUsage: 0,
  memoryUsage: 0,
})

const statCards = computed(() => [
  { label: '活跃站点', value: metrics.value.activeSites, icon: Monitor, tone: 'primary' as const },
  { label: '运行中任务', value: metrics.value.runningTasks, icon: Clock, tone: 'warning' as const },
  { label: 'CPU 使用率', value: `${metrics.value.cpuUsage}%`, icon: Cpu, tone: 'success' as const },
  { label: '内存使用率', value: `${metrics.value.memoryUsage}%`, icon: MemoryStick, tone: 'danger' as const },
])

type Series = { times: string[]; values: number[] }
const qpsSeries = ref<Series>({ times: [], values: [] })
const latencySeries = ref<Series>({ times: [], values: [] })

// Resolve a design-system token into a color string. Values live on :root/.dark
// as "H S% L%" triples, so we wrap them back into hsl().
function token(name: string, alpha = 1) {
  if (typeof window === 'undefined') return 'transparent'
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  if (!value) return 'transparent'
  return alpha === 1 ? `hsl(${value})` : `hsl(${value} / ${alpha})`
}

// Reading `theme` makes the palette re-evaluate on toggle, so the chart
// re-pulls every token after the .dark class has been applied.
const palette = computed(() => {
  theme.value
  return {
    line: token('--primary'),
    axis: token('--muted-foreground'),
    split: token('--border'),
    tooltipBg: token('--popover'),
    tooltipText: token('--popover-foreground'),
    areaTop: token('--primary', 0.18),
    areaBottom: token('--primary', 0),
  }
})

function buildOption(name: string, unit: string, series: Series) {
  const c = palette.value
  return {
    grid: { top: 16, right: 16, bottom: 28, left: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.tooltipBg,
      borderColor: 'transparent',
      textStyle: { color: c.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: series.times,
      axisLine: { lineStyle: { color: c.split } },
      axisLabel: { color: c.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: c.split } },
      axisLabel: { color: c.axis, fontSize: 11, formatter: unit ? `{value} ${unit}` : '{value}' },
    },
    series: [
      {
        name,
        type: 'line',
        data: series.values,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: c.line },
        itemStyle: { color: c.line },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: c.areaTop },
              { offset: 1, color: c.areaBottom },
            ],
          },
        },
      },
    ],
  }
}

const qpsOption = computed(() => buildOption('QPS', '', qpsSeries.value))
const latencyOption = computed(() => buildOption('P95', 'ms', latencySeries.value))

onMounted(() => {
  metrics.value = {
    activeSites: 42,
    runningTasks: 8,
    cpuUsage: 35,
    memoryUsage: 62,
  }

  const times: string[] = []
  const qpsData: number[] = []
  const latencyData: number[] = []

  for (let i = 0; i < 20; i++) {
    times.push(`${i}:00`)
    qpsData.push(Math.floor(Math.random() * 100))
    latencyData.push(Math.floor(Math.random() * 200))
  }

  qpsSeries.value = { times, values: qpsData }
  latencySeries.value = { times, values: latencyData }
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">系统监控</h1>
      <p class="mt-1 text-sm text-muted-foreground">站点、任务负载与资源占用趋势</p>
    </div>

    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card v-for="card in statCards" :key="card.label" class="shadow-none">
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium text-muted-foreground">{{ card.label }}</CardTitle>
          <div
            class="flex size-8 items-center justify-center rounded-lg"
            :class="{
              'bg-primary/10 text-primary': card.tone === 'primary',
              'bg-warning/10 text-warning': card.tone === 'warning',
              'bg-success/10 text-success': card.tone === 'success',
              'bg-destructive/10 text-destructive': card.tone === 'danger',
            }"
          >
            <component :is="card.icon" class="size-4" />
          </div>
        </CardHeader>
        <CardContent>
          <div class="stat-num text-3xl text-foreground">{{ card.value }}</div>
        </CardContent>
      </Card>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <Card class="shadow-none">
        <CardHeader>
          <CardTitle class="text-base">QPS 趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <v-chart :option="qpsOption" class="h-[300px] w-full" autoresize />
        </CardContent>
      </Card>

      <Card class="shadow-none">
        <CardHeader>
          <CardTitle class="text-base">响应时间（P95）</CardTitle>
        </CardHeader>
        <CardContent>
          <v-chart :option="latencyOption" class="h-[300px] w-full" autoresize />
        </CardContent>
      </Card>
    </div>
  </div>
</template>
