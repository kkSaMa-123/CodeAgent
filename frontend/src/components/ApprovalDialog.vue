<script setup>
defineProps({ store: { type: Object, required: true }, sessionStore: { type: Object, required: true } })
</script>

<template>
  <div v-if="store.pending" class="modal-backdrop" role="presentation">
    <section class="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
      <p class="kicker">Safety gate</p>
      <h2 id="approval-title">命令需要你的批准</h2>
      <p class="approval-reason">{{ store.pending.reason || '该命令可能产生敏感副作用。' }}</p>
      <dl>
        <div><dt>完整命令</dt><dd><code>{{ store.pending.command }}</code></dd></div>
        <div><dt>工作目录</dt><dd><code>{{ store.pending.workspace }}</code></dd></div>
        <div v-if="store.pending.expires_at"><dt>有效期至</dt><dd>{{ store.pending.expires_at }}</dd></div>
      </dl>
      <p v-if="store.error" class="inline-error approval-error" role="alert">{{ store.error }}</p>
      <div class="approval-actions">
        <button class="danger" type="button" :disabled="store.loading" @click="store.cancel(sessionStore)">取消任务</button>
        <span />
        <button class="secondary" type="button" :disabled="store.loading" @click="store.resolve(false, sessionStore)">拒绝</button>
        <button class="primary" type="button" :disabled="store.loading" @click="store.resolve(true, sessionStore)">批准并继续</button>
      </div>
    </section>
  </div>
</template>
