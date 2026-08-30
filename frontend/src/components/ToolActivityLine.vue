<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ group: { type: Object, required: true } })
const expanded = ref(false)
const descriptions = {
  list_files: (count) => count === 1 ? '查看了项目文件' : `查看了项目文件 ${count} 次`,
  read_file: (count) => `读取了 ${count} 个文件`,
  search_text: (count) => `搜索了代码 ${count} 次`,
  write_file: (count) => `写入了 ${count} 个文件`,
  replace_in_file: (count) => `修改了 ${count} 个文件`,
  git_diff: (count) => `查看了 ${count} 次代码变更`,
  run_command: (count) => `运行了 ${count} 条命令`,
}
const runningDescriptions = {
  list_files: '正在查看项目文件',
  read_file: '正在读取文件',
  search_text: '正在搜索代码',
  write_file: '正在写入文件',
  replace_in_file: '正在修改文件',
  git_diff: '正在查看代码变更',
  run_command: '正在运行命令',
}
const description = computed(() => {
  if (props.group.status === 'running') return runningDescriptions[props.group.name] || `正在调用 ${props.group.name}`
  return (descriptions[props.group.name] || ((count) => `调用了 ${props.group.name} ${count} 次`))(props.group.count)
})
function traceTarget(trace) { const started = trace.events?.find((event) => event.event_type === 'tool.started')?.payload || {}; return trace.metadata?.path || started.path || started.query || trace.details?.command || trace.command || '' }
function traceError(trace) { return trace.details?.stderr || trace.summary || trace.output || '' }
</script>

<template>
  <div class="tool-activity" :data-status="group.status">
    <button type="button" class="tool-activity-summary" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="tool-activity-icon">{{ group.status === 'running' ? '◌' : group.errorCount ? '!' : '✓' }}</span>
      <span>{{ description }}</span>
      <small v-if="group.errorCount">{{ group.errorCount }} 次失败</small>
      <span class="tool-activity-chevron">{{ expanded ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="expanded" class="tool-activity-details">
      <div v-for="(trace, index) in group.traces" :key="trace.id" class="tool-activity-detail" :data-status="trace.status">
        <span>{{ trace.status === 'success' ? '✓' : trace.status === 'running' ? '◌' : '!' }}</span>
        <code>{{ traceTarget(trace) || `${description} #${index + 1}` }}</code>
        <small>{{ trace.status === 'success' ? '成功' : trace.status === 'running' ? '执行中' : '失败' }}</small>
        <pre v-if="trace.status === 'error' && traceError(trace)"><code>{{ traceError(trace) }}</code></pre>
      </div>
    </div>
  </div>
</template>
