<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = withDefaults(defineProps<{
  original: string
  modified: string
  language?: string
  theme?: 'light' | 'dark'
  fileKey: string
}>(), {
  language: 'plaintext',
  theme: 'light',
})

const editorContainer = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneDiffEditor | null = null
let originalModel: monaco.editor.ITextModel | null = null
let modifiedModel: monaco.editor.ITextModel | null = null

function disposeModels() {
  editor?.setModel(null)
  originalModel?.dispose()
  modifiedModel?.dispose()
  originalModel = null
  modifiedModel = null
}

function setModels() {
  if (!editor) return
  disposeModels()
  const safeKey = encodeURIComponent(props.fileKey || 'file')
  originalModel = monaco.editor.createModel(
    props.original,
    props.language,
    monaco.Uri.parse(`inmemory://nextproject-diff/${safeKey}/before`),
  )
  modifiedModel = monaco.editor.createModel(
    props.modified,
    props.language,
    monaco.Uri.parse(`inmemory://nextproject-diff/${safeKey}/after`),
  )
  editor.setModel({ original: originalModel, modified: modifiedModel })
}

onMounted(() => {
  if (!editorContainer.value) return
  editor = monaco.editor.createDiffEditor(editorContainer.value, {
    theme: props.theme === 'dark' ? 'vs-dark' : 'vs',
    automaticLayout: true,
    readOnly: true,
    originalEditable: false,
    renderSideBySide: true,
    useInlineViewWhenSpaceIsLimited: false,
    enableSplitViewResizing: true,
    splitViewDefaultRatio: 0.5,
    diffAlgorithm: 'advanced',
    accessibilityVerbose: true,
    originalAriaLabel: '修改前文件内容',
    modifiedAriaLabel: '修改后文件内容',
    hideUnchangedRegions: {
      enabled: true,
      contextLineCount: 3,
      minimumLineCount: 5,
      revealLineCount: 20,
    },
    minimap: { enabled: false },
    lineNumbers: 'on',
    glyphMargin: false,
    folding: true,
    renderOverviewRuler: false,
    scrollBeyondLastLine: false,
    wordWrap: 'off',
    renderWhitespace: 'selection',
    ignoreTrimWhitespace: false,
    fontSize: 13,
    lineHeight: 20,
    padding: { top: 8, bottom: 8 },
  })
  setModels()
})

watch(
  () => [props.fileKey, props.original, props.modified, props.language],
  setModels,
)

watch(() => props.theme, (theme) => {
  monaco.editor.setTheme(theme === 'dark' ? 'vs-dark' : 'vs')
})

onBeforeUnmount(() => {
  disposeModels()
  editor?.dispose()
  editor = null
})
</script>

<template>
  <div
    ref="editorContainer"
    class="h-full min-h-[28rem] w-full"
    aria-label="左右文件修改对比"
  />
</template>
