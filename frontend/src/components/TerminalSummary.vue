<script setup>
import { computed } from 'vue'
const props = defineProps({ store: { type: Object, required: true } })
const presentation = computed(() => ({
  completed: { title: '任务已完成', detail: 'Agent 已给出最终回答。' },
  failed: { title: '任务执行失败', detail: '任务未完成，请根据原因调整后重新创建会话。' },
  cancelled: { title: '任务已取消', detail: '后续模型和工具活动已停止。' },
}[props.store.status] || { title: '任务已结束', detail: '' }))
</script>

<template>
  <div class="terminal-card" :data-status="store.status" role="status">
    <strong>{{ presentation.title }}</strong>
    <span>{{ store.terminationReason || presentation.detail }}</span>
    <div v-if="store.modifiedFiles.length" class="terminal-files"><small>修改文件</small><code v-for="file in store.modifiedFiles" :key="file">{{ file }}</code></div>
  </div>
</template>
