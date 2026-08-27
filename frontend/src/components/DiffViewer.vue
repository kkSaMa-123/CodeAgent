<script setup>
defineProps({ store: { type: Object, required: true }, modifiedFiles: { type: Array, default: () => [] } })
defineEmits(['reload', 'open-file'])
</script>

<template>
  <div class="diff-shell">
    <div v-if="modifiedFiles.length" class="changed-files" aria-label="修改文件列表">
      <button v-for="file in modifiedFiles" :key="file" type="button" @click="$emit('open-file', file)">M&nbsp; {{ file }}</button>
    </div>
    <div v-if="store.loading" class="center-state"><span class="spinner" />正在生成累计差异…</div>
    <div v-else-if="store.error" class="center-state error-state" role="alert"><strong>Diff 加载失败</strong><span>{{ store.error }}</span><button class="secondary compact" type="button" @click="$emit('reload')">重试</button></div>
    <div v-else-if="!store.diff" class="center-state"><span class="file-glyph">±</span><strong>暂无代码差异</strong><span>Agent 修改文件后，累计 diff 会显示在这里。</span></div>
    <pre v-else class="diff-view" aria-label="累计代码差异"><code><span v-for="line in store.lines" :key="line.id" class="diff-line" :class="line.kind">{{ line.text || ' ' }}</span></code></pre>
  </div>
</template>
