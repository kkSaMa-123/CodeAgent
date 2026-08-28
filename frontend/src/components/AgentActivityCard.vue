<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({ run: { type: Object, required: true }, eventStore: { type: Object, required: true }, approval: { type: Object, required: true } })
const now = ref(Date.now())
let timer = null
onMounted(() => { timer = window.setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })

const elapsed = computed(() => Math.max(0, Math.floor((now.value - (props.run.startedAt || now.value)) / 1000)))
const activity = computed(() => {
  if (props.run.loading && !props.run.runId) return { phase: 'preparing', label: '正在创建任务…', detail: '正在连接 Agent 后端' }
  if (props.run.status === 'queued') return { phase: 'preparing', label: '正在准备任务…', detail: '' }
  if (props.run.status === 'waiting_approval' || props.approval.pending) return { phase: 'approval', label: '等待你确认命令', detail: '请在下方确认卡片中选择操作' }
  return props.eventStore.activity || { phase: 'thinking', label: 'Agent 正在分析任务…', detail: '' }
})
const waitHint = computed(() => {
  if (elapsed.value >= 45) return '仍在运行，你可以继续等待或停止任务。'
  if (elapsed.value >= 15) return '复杂任务或网络响应可能需要更长时间。'
  return ''
})
</script>

<template>
  <section v-if="run.isActive || run.loading" class="agent-activity" :data-phase="activity.phase" role="status" aria-live="polite">
    <span class="agent-avatar activity-avatar">A</span>
    <div class="activity-copy">
      <strong>{{ activity.label }}<span v-if="activity.phase !== 'approval'" class="thinking-dots" aria-hidden="true"><i /><i /><i /></span></strong>
      <code v-if="activity.detail" class="activity-detail">{{ activity.detail }}</code>
      <small>已运行 {{ elapsed }} 秒<span v-if="waitHint"> · {{ waitHint }}</span></small>
    </div>
    <button v-if="run.runId" type="button" class="activity-stop" @click="run.cancel()">停止</button>
  </section>
</template>
