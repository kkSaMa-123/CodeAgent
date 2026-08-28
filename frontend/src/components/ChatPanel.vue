<script setup>
import { nextTick, ref, watch } from 'vue'
import AgentActivityCard from './AgentActivityCard.vue'
import ApprovalCard from './ApprovalCard.vue'
import MarkdownContent from './MarkdownContent.vue'
import ToolActivityLine from './ToolActivityLine.vue'

const props = defineProps({ conversations: { type: Object, required: true }, run: { type: Object, required: true }, eventStore: { type: Object, required: true }, approval: { type: Object, required: true } })
const emit = defineEmits(['submit', 'open-change'])
const task = ref('')
const messagesElement = ref(null)
const followsLatest = ref(true)

function message(runId, role) { return props.conversations.messages.find((item) => item.run_id === runId && item.role === role) }
function submit() { const value = task.value.trim(); if (!value) return; followsLatest.value = true; emit('submit', value); task.value = ''; scrollToLatest(true) }
function trackScroll() { const element = messagesElement.value; if (element) followsLatest.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }
async function scrollToLatest(force = false) { await nextTick(); const element = messagesElement.value; if (element && (force || followsLatest.value)) element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' }) }

watch(
  () => [props.conversations.messages.length, props.conversations.runs.length, props.eventStore.events?.length || 0, props.run.status, props.run.pendingTask, Boolean(props.approval.pending)],
  () => scrollToLatest(),
  { flush: 'post' },
)
</script>

<template>
  <section class="panel chat-panel">
    <div class="panel-heading"><div><p class="kicker">Conversation</p><h2>{{ conversations.current?.title || '选择一个对话' }}</h2></div><span class="status-badge" :data-status="run.status">{{ run.status }}</span></div>
    <div ref="messagesElement" class="messages" aria-live="polite" @scroll.passive="trackScroll">
      <div v-if="!conversations.currentId" class="agent-intro"><span class="agent-avatar">A</span><div><strong>选择或新建对话</strong><p>每个对话拥有独立上下文，可以连续进行多轮任务。</p></div></div>
      <article v-for="item in conversations.runs" :key="item.id" class="run-turn">
        <div v-if="message(item.id, 'user')" class="message user"><small>你</small><p>{{ message(item.id, 'user').content }}</p></div>
        <section v-if="eventStore.runId === item.id && eventStore.groupedToolTraces?.length" class="tool-activity-list" aria-label="Agent 执行过程">
          <p class="process-label">执行过程</p>
          <ToolActivityLine v-for="group in eventStore.groupedToolTraces" :key="group.name" :group="group" />
        </section>
        <div class="run-summary" :data-status="item.status">
          <span>{{ item.status === 'completed' ? '任务已完成' : item.status === 'failed' ? '任务失败' : item.status === 'cancelled' ? '任务已停止' : '任务进行中' }}</span><span v-if="item.termination_reason && item.termination_reason !== item.status">{{ item.termination_reason }}</span>
          <button v-for="change in conversations.changesByRun[item.id] || []" :key="change.id" type="button" :class="{ artifact: change.preview_kind === 'binary' }" @click="emit('open-change', item.id, change)"><b>{{ change.preview_kind === 'binary' ? 'BIN' : change.change_type[0].toUpperCase() }}</b>{{ change.path }} <small>{{ change.preview_kind === 'binary' ? '二进制生成物' : `+${change.additions} -${change.deletions}` }}</small></button>
        </div>
        <div v-if="message(item.id, 'assistant')" class="message assistant final-answer"><small>Agent · 最终输出</small><MarkdownContent :content="message(item.id, 'assistant').content" /></div>
      </article>
      <div v-if="run.pendingTask && !message(run.runId, 'user')" class="message user optimistic-message"><small>你</small><p>{{ run.pendingTask }}</p></div>
      <AgentActivityCard :run="run" :event-store="eventStore" :approval="approval" />
      <ApprovalCard :store="approval" :run-store="run" />
      <p v-if="eventStore.error" class="inline-error recoverable-error">{{ eventStore.error }}</p><p v-if="conversations.error || run.error" class="inline-error"><span>{{ conversations.error || run.error }}</span> <button type="button" @click="conversations.refresh()">重试</button></p>
    </div>
    <form class="composer" @submit.prevent="submit"><label for="task-input">继续对话</label><textarea id="task-input" v-model="task" rows="4" placeholder="描述下一项编码任务…" :disabled="run.isActive || !conversations.currentId" /><div class="composer-actions"><span>{{ conversations.currentId ? `对话 ${conversations.currentId.slice(0, 8)}` : '请先选择对话' }}</span><button v-if="run.isActive" class="danger" type="button" @click="run.cancel()">停止</button><button class="primary" type="submit" :disabled="run.isActive || !conversations.currentId || !task.trim()">发送</button></div></form>
  </section>
</template>
