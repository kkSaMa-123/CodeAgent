<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  running: { type: Boolean, default: false },
})
const expanded = ref(props.running)
const contentElement = ref(null)

watch(() => props.running, (running) => { expanded.value = running })
watch(() => props.content, async () => {
  await nextTick()
  if (expanded.value && contentElement.value) {
    contentElement.value.scrollTop = contentElement.value.scrollHeight
  }
})
</script>

<template>
  <section class="reasoning-card" :class="{ running }">
    <button type="button" class="reasoning-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="reasoning-icon">{{ running ? '◌' : '✓' }}</span>
      <span>Agent 思考过程</span>
      <small>{{ running ? '持续更新中' : '已结束' }}</small>
      <span class="reasoning-chevron">{{ expanded ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="expanded" ref="contentElement" class="reasoning-content">{{ content }}</div>
  </section>
</template>
