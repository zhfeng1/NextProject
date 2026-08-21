<script setup lang="ts">
import ModelProviderSettings from '@/components/ModelProviderSettings.vue'
import ProgrammingToolVersions from '@/components/ProgrammingToolVersions.vue'
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">系统设置</h1>
      <p class="mt-1 text-sm text-muted-foreground">这里维护全局默认模型配置；项目未设置兼容 Provider 时，编程工具会自动使用全局配置。</p>
    </div>

    <ProgrammingToolVersions />

    <ModelProviderSettings
      scope-type="global"
      title="全局模型配置"
      description="作为所有项目的默认配置使用；项目页面配置了兼容 Provider 时，以项目配置为准。"
    />
  </div>
</template>
