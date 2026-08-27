<script setup>
import { ref } from 'vue'
import TerminalSummary from './TerminalSummary.vue'
import ToolTraceCard from './ToolTraceCard.vue'

const props = defineProps({ store: { type: Object, required: true }, eventStore: { type: Object, default: () => ({ toolTraces: [], connectionStatus: 'idle', compressed: false, error: '' }) } })
const task = ref('')

async function run() {
  const value = task.value
  if (await props.store.run(value)) task.value = ''
}
</script>

<template>
  <section class="panel chat-panel" aria-labelledby="chat-title">
    <div class="panel-heading">
      <div><p class="kicker">Agent</p><h2 id="chat-title">任务对话</h2></div>
      <span class="status-badge" :data-status="store.status">{{ store.status }}</span>
    </div>
    <div class="messages" aria-live="polite">
      <div v-if="!store.messages.length" class="agent-intro"><span class="agent-avatar">A</span><div><strong>准备就绪</strong><p>打开工作区，然后描述你希望完成的编码任务。</p></div></div>
      <article v-for="(message, index) in store.messages" :key="index" class="message" :class="message.kind">
        <small>{{ message.kind === 'user' ? '你' : 'Agent' }}</small><p>{{ message.text }}</p>
      </article>
      <section v-if="eventStore.toolTraces.length" class="trace-list" aria-label="工具执行轨迹">
        <p class="section-label">执行轨迹 · {{ eventStore.connectionStatus }}</p>
        <ToolTraceCard v-for="trace in eventStore.toolTraces" :key="trace.id" :trace="trace" />
      </section>
      <p v-if="eventStore.compressed" class="compressed-note">较早事件已压缩，当前状态已从会话快照恢复。</p>
      <p v-if="eventStore.error" class="inline-error recoverable-error" role="status">{{ eventStore.error }}</p>
      <p v-if="store.error" class="inline-error" role="alert">{{ store.error }}</p>
      <TerminalSummary v-if="store.isTerminal" :store="store" />
    </div>
    <form class="composer" @submit.prevent="run">
      <label for="task-input">任务描述</label>
      <textarea id="task-input" v-model="task" rows="4" placeholder="例如：为登录接口补充参数校验和单元测试" :disabled="store.isActive" />
      <div class="composer-actions">
        <span>{{ store.sessionId ? `会话 ${store.sessionId.slice(0, 8)}` : '请先打开工作区' }}</span>
        <button v-if="store.isActive" class="danger" type="button" @click="store.cancel()">取消</button>
        <button class="primary" type="submit" :disabled="store.isActive || !store.sessionId || !task.trim()">运行任务</button>
      </div>
    </form>
  </section>
</template>
