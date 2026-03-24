<script setup lang="ts">
import { ref, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
} from 'echarts/components'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Monitor, Clock, Cpu, FileBox } from 'lucide-vue-next'

use([
  CanvasRenderer,
  LineChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
])

const metrics = ref({
  activeSites: 0,
  runningTasks: 0,
  cpuUsage: 0,
  memoryUsage: 0,
})

const qpsOption = ref({
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: [] as string[] },
  yAxis: { type: 'value' },
  series: [{ name: 'QPS', type: 'line', data: [] as number[], smooth: true }],
})

const latencyOption = ref({
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: [] as string[] },
  yAxis: { type: 'value', axisLabel: { formatter: '{value} ms' } },
  series: [{ name: 'P95 Latency', type: 'line', data: [] as number[], smooth: true }],
})

onMounted(() => {
  metrics.value = {
    activeSites: 42,
    runningTasks: 8,
    cpuUsage: 35,
    memoryUsage: 62,
  }

  const times = []
  const qpsData = []
  const latencyData = []

  for (let i = 0; i < 20; i++) {
    times.push(`${i}:00`)
    qpsData.push(Math.floor(Math.random() * 100))
    latencyData.push(Math.floor(Math.random() * 200))
  }

  qpsOption.value.xAxis.data = times
  qpsOption.value.series[0].data = qpsData

  latencyOption.value.xAxis.data = times
  latencyOption.value.series[0].data = latencyData
})
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold tracking-tight">系统监控</h1>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium">活跃站点</CardTitle>
          <Monitor class="h-4 w-4 text-blue-500" />
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ metrics.activeSites }}</div>
        </CardContent>
      </Card>
      
      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium">运行中任务</CardTitle>
          <Clock class="h-4 w-4 text-green-500" />
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ metrics.runningTasks }}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium">CPU 使用率</CardTitle>
          <Cpu class="h-4 w-4 text-orange-500" />
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ metrics.cpuUsage }}%</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium">内存使用率</CardTitle>
          <FileBox class="h-4 w-4 text-red-500" />
        </CardHeader>
        <CardContent>
          <div class="text-2xl font-bold">{{ metrics.memoryUsage }}%</div>
        </CardContent>
      </Card>
    </div>

    <!-- ECharts 图表 -->
    <div class="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>QPS 趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <v-chart :option="qpsOption" class="h-[300px] w-full" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>响应时间（P95）</CardTitle>
        </CardHeader>
        <CardContent>
          <v-chart :option="latencyOption" class="h-[300px] w-full" />
        </CardContent>
      </Card>
    </div>
  </div>
</template>
