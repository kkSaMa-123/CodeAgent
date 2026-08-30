<script setup>
const props = defineProps({ store: { type: Object, required: true }, conversations: { type: Object, required: true }, run: { type: Object, required: true } })
const groups = [
  ['readonly', '只读工具', '用于了解项目，不修改工作区'],
  ['editing', '文件修改', '会创建、覆盖或修改项目文件'],
  ['command', '命令执行', '部分命令仍需要用户在对话中确认'],
]
</script>

<template>
  <section class="settings-page">
    <header class="settings-header"><div><p class="kicker">Capabilities</p><h2>工具管理</h2><p>控制当前对话中 Agent 可以看到并执行的工具。</p></div><span>{{ store.enabledCount }}/{{ store.tools.length }} 已启用</span></header>
    <div v-if="!conversations.currentId" class="settings-empty">请先在左侧选择或创建一个对话。</div>
    <div v-else class="settings-body">
      <div class="settings-scope"><strong>当前对话</strong><span>{{ conversations.current?.title }}</span><small v-if="run.isActive">本轮运行中，能力配置已冻结</small></div>
      <p v-if="store.error" class="inline-error">{{ store.error }}</p>
      <div v-if="!store.enabledTools.length" class="chat-only-notice">仅聊天模式：Agent 无法读取、修改文件或执行命令。</div>
      <section v-for="group in groups" :key="group[0]" class="capability-group">
        <div><h3>{{ group[1] }}</h3><p>{{ group[2] }}</p></div>
        <label v-for="tool in store.tools.filter((item) => item.group === group[0])" :key="tool.name" class="capability-row">
          <span><strong>{{ tool.label }}</strong><code>{{ tool.name }}</code><small>{{ tool.description }} · {{ tool.risk }}</small></span>
          <input type="checkbox" :checked="store.enabledTools.includes(tool.name)" :disabled="run.isActive || store.saving" @change="store.toggleTool(tool.name, $event.target.checked)" />
        </label>
      </section>
    </div>
  </section>
</template>
