<script setup>
import { computed, ref } from 'vue'
import DiffViewer from './DiffViewer.vue'

const props = defineProps({ store: { type: Object, required: true }, diffStore: { type: Object, default: () => ({ loading: false, error: '', diff: '', lines: [] }) }, modifiedFiles: { type: Array, default: () => [] } })
defineEmits(['reload', 'reload-diff', 'open-file'])
const lines = computed(() => props.store.fileContent?.content?.split('\n') || [])
const view = ref('file')
</script>

<template>
  <section class="panel editor-panel" aria-labelledby="editor-title">
    <div class="panel-heading editor-heading">
      <div><p class="kicker">Editor</p><h2 id="editor-title">{{ view === 'diff' ? '累计 Diff' : (store.currentFile || '文件预览') }}</h2></div>
      <div class="view-switch"><button type="button" :class="{ active: view === 'file' }" @click="view = 'file'">文件</button><button type="button" :class="{ active: view === 'diff' }" @click="view = 'diff'; $emit('reload-diff')">Diff <span v-if="modifiedFiles.length">{{ modifiedFiles.length }}</span></button></div>
    </div>
    <div v-if="view === 'file'" class="editor-body">
      <button v-if="store.currentFile" class="editor-reload secondary compact" type="button" :disabled="store.fileLoading" @click="$emit('reload')">重新加载</button>
      <div v-if="store.fileLoading" class="center-state"><span class="spinner" />正在读取文件…</div>
      <div v-else-if="store.fileError" class="center-state error-state" role="alert"><strong>无法预览</strong><span>{{ store.fileError }}</span></div>
      <div v-else-if="!store.fileContent" class="center-state"><span class="file-glyph">{ }</span><strong>选择一个文件开始预览</strong><span>内容只读显示，修改由 Agent 工具完成。</span></div>
      <pre v-else class="code-view" :aria-label="`${store.currentFile} 文件内容`"><code><span v-for="(line, index) in lines" :key="index" class="code-line"><span class="line-number">{{ index + 1 }}</span><span class="line-content">{{ line || ' ' }}</span></span></code></pre>
    </div>
    <DiffViewer v-else :store="diffStore" :modified-files="modifiedFiles" @reload="$emit('reload-diff')" @open-file="view = 'file'; $emit('open-file', $event)" />
  </section>
</template>
