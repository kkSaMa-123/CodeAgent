<script setup>
import { computed } from 'vue'

const props = defineProps({ store: { type: Object, required: true }, theme: { type: String, default: 'dark' } })
defineEmits(['toggle-theme'])
const statusText = computed(() => props.store.loading ? '检查中' : props.store.ready ? '已就绪' : '未就绪')
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark">CA</span>
      <div><h1>CodeAgent</h1><p>本地编程智能体工作台</p></div>
    </div>
    <div class="provider" aria-live="polite">
      <span class="status-dot" :class="{ ready: store.ready }" aria-hidden="true" />
      <div>
        <strong>{{ statusText }}</strong>
        <small v-if="store.summary">{{ store.summary.provider }} · {{ store.summary.model }}</small>
        <small v-else-if="store.error">{{ store.error }}</small>
        <small v-else>等待读取模型配置</small>
      </div>
      <button class="icon-button theme-toggle" type="button" :aria-label="theme === 'dark' ? '切换到亮色主题' : '切换到深色主题'" :title="theme === 'dark' ? '亮色主题' : '深色主题'" @click="$emit('toggle-theme')"><span aria-hidden="true">{{ theme === 'dark' ? '☀' : '☾' }}</span></button>
      <button class="icon-button" type="button" :disabled="store.loading" aria-label="重试模型配置" @click="store.load()">↻</button>
    </div>
  </header>
</template>
