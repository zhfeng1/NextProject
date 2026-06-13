<script setup lang="ts">
import 'vue-sonner/style.css'
import { Toaster as Sonner, type ToasterProps } from 'vue-sonner'

const props = withDefaults(defineProps<ToasterProps>(), {
  position: 'top-center',
  duration: 3000,
  richColors: true,
  closeButton: true,
})
</script>

<template>
  <Sonner v-bind="props" />
</template>
