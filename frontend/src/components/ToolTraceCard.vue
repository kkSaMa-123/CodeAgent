<script setup>
import { ref } from 'vue'
defineProps({ trace: { type: Object, required: true } })
const expanded = ref(false)
</script>

<template>
  <article class="trace-card" :data-status="trace.status">
    <button type="button" class="trace-summary" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="trace-icon">{{ trace.status === 'running' ? '…' : trace.status === 'success' ? '✓' : '!' }}</span>
      <span><strong>{{ trace.name }}</strong><small>{{ trace.status }} · {{ trace.id }}</small></span>
      <span aria-hidden="true">{{ expanded ? '▴' : '▾' }}</span>
    </button>
    <div v-if="expanded" class="trace-detail">
      <div v-for="event in trace.events" :key="event.sequence"><code>#{{ event.sequence }} {{ event.event_type }}</code><span>{{ JSON.stringify(event.payload) }}</span></div>
    </div>
  </article>
</template>
