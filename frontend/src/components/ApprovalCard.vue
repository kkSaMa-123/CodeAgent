<script setup>
defineProps({ store: { type: Object, required: true }, runStore: { type: Object, required: true } })
</script>

<template>
  <section v-if="store.pending" class="inline-approval" role="region" aria-labelledby="approval-title">
    <header><span class="approval-icon">!</span><div><p class="kicker">需要确认</p><h3 id="approval-title">允许 Agent 运行这条命令吗？</h3></div></header>
    <p class="approval-reason">{{ store.pending.reason || '这条命令可能修改工作区或产生其他副作用。' }}</p>
    <pre class="approval-command"><code>{{ store.pending.command }}</code></pre>
    <p class="approval-workspace"><span>工作目录</span><code>{{ store.pending.workspace }}</code></p>
    <p v-if="store.error" class="inline-error approval-error" role="alert">{{ store.error }}</p>
    <div class="inline-approval-actions">
      <button class="secondary" type="button" :disabled="store.loading" @click="store.resolve(false, runStore)">拒绝</button>
      <button class="danger" type="button" :disabled="store.loading" @click="store.cancel(runStore)">停止任务</button>
      <button class="primary" type="button" :disabled="store.loading" @click="store.resolve(true, runStore)">允许一次</button>
    </div>
  </section>
</template>
