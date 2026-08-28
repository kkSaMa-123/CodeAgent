<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ workspace: { type: Object, required: true }, diffStore: { type: Object, required: true }, selectedChange: { type: Object, default: null } })
const view = ref('current')
const content = computed(() => view.value === 'history' ? props.diffStore.preview : props.workspace.fileContent?.content || '')
const contentLines = computed(() => content.value.split('\n'))
const diffLines = computed(() => {
  let previousNewEnd = 0
  const result = []
  for (const line of props.diffStore.lines) {
    if (line.kind === 'hunk') {
      const match = line.text.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/)
      if (match) {
        const newStart = Number(match[1])
        const newCount = match[2] === undefined ? 1 : Number(match[2])
        const folded = previousNewEnd ? newStart - previousNewEnd - 1 : newStart - 1
        if (folded > 0) result.push({ id: `fold-${line.id}`, text: `⋯ 已折叠 ${folded} 行未修改内容 ⋯`, kind: 'collapsed' })
        previousNewEnd = newStart + newCount - 1
      }
    }
    result.push(line)
  }
  return result
})
function select(value) { view.value = value }
defineExpose({ select })
</script>

<template>
  <section class="panel editor-panel">
    <div class="panel-heading editor-heading"><div><p class="kicker">Changes & Preview</p><h2>{{ selectedChange?.path || workspace.currentFile || '文件预览' }}</h2></div><div class="view-switch"><button type="button" :class="{ active: view === 'diff' }" :disabled="!selectedChange" @click="view = 'diff'">本轮 Diff</button><button type="button" :class="{ active: view === 'history' }" :disabled="!selectedChange" @click="view = 'history'">本轮版本</button><button type="button" :class="{ active: view === 'current' }" @click="view = 'current'">当前文件</button></div></div>
    <div class="change-meta" v-if="selectedChange"><span>{{ selectedChange.preview_kind === 'binary' ? '生成产物' : selectedChange.change_type }}</span><code v-if="selectedChange.old_path">{{ selectedChange.old_path }} → </code><code>{{ selectedChange.path }}</code><small>{{ selectedChange.preview_kind === 'binary' ? '二进制文件' : `+${selectedChange.additions} -${selectedChange.deletions}` }}</small></div>
    <div class="editor-body">
      <div v-if="diffStore.loading || workspace.fileLoading" class="center-state"><span class="spinner" />正在读取…</div>
      <div v-else-if="diffStore.error || workspace.fileError" class="center-state error-state"><strong>无法预览</strong><span>{{ diffStore.error || workspace.fileError }}</span></div>
      <div v-else-if="view === 'diff' && !diffStore.diff" class="center-state"><strong>没有文本 Diff</strong><span>二进制、超限或纯重命名文件可能无法显示文本差异。</span></div>
      <div v-else-if="view === 'diff'" class="diff-content">
        <div class="diff-context-notice"><span>Diff 只显示修改位置附近的内容，未修改代码会被折叠。</span><button type="button" @click="view = 'history'">查看本轮完整文件</button></div>
        <pre class="diff-view"><code><span v-for="line in diffLines" :key="line.id" class="diff-line" :class="line.kind">{{ line.text || ' ' }}</span></code></pre>
      </div>
      <div v-else-if="!content && !selectedChange && !workspace.currentFile" class="center-state"><span class="file-glyph">{ }</span><strong>选择文件或历史修改</strong><span>可以预览当前文件、本轮结束版本和冻结 Diff。</span></div>
      <div v-else-if="view === 'history' && diffStore.previewKind !== 'text'" class="center-state"><strong>历史内容不可预览</strong><span>{{ diffStore.previewKind === 'binary' ? '二进制文件' : '文件超过历史预览上限' }}</span></div>
      <pre v-else class="code-view"><code><span v-for="(line, index) in contentLines" :key="index" class="code-line"><span class="line-number">{{ index + 1 }}</span><span class="line-content">{{ line || ' ' }}</span></span></code></pre>
    </div>
  </section>
</template>
