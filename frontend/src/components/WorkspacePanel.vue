<script setup>
const props = defineProps({ store: { type: Object, required: true }, sessionId: { type: String, default: '' } })
const emit = defineEmits(['validated', 'open-file'])

async function submit() {
  const result = await props.store.validate()
  if (result) emit('validated', result.path)
}

function depth(path) { return path === '.' ? 0 : path.split('/').length - 1 }
function name(path) { return path.split('/').at(-1) }
</script>

<template>
  <section class="panel workspace-panel" aria-labelledby="workspace-title">
    <div class="panel-heading"><div><p class="kicker">Workspace</p><h2 id="workspace-title">工作区</h2></div></div>
    <form class="workspace-form" @submit.prevent="submit">
      <label for="workspace-path">绝对路径</label>
      <div class="input-row">
        <input id="workspace-path" v-model="store.inputPath" placeholder="/Users/me/project" autocomplete="off" />
        <button class="primary compact" type="submit" :disabled="store.loading">{{ store.loading ? '载入中' : '打开' }}</button>
      </div>
    </form>
    <p v-if="store.workspace" class="workspace-root" :title="store.workspace">{{ store.workspace }}</p>
    <p v-if="store.error" class="inline-error" role="alert">{{ store.error }}</p>
    <div class="tree" aria-label="文件树">
      <p v-if="!store.entries.length && !store.loading" class="empty-copy">打开工作区后浏览文件。</p>
      <button
        v-for="entry in store.visibleEntries" :key="entry.path" type="button" class="tree-item"
        :class="{ selected: entry.path === store.currentFile }" :style="{ paddingLeft: `${12 + depth(entry.path) * 16}px` }"
        @click="entry.type === 'directory' ? store.toggleDirectory(entry.path) : emit('open-file', entry.path)"
      >
        <span aria-hidden="true">{{ entry.type === 'directory' ? (store.expanded.includes(entry.path) ? '▾' : '▸') : '·' }}</span>
        <span class="tree-name">{{ name(entry.path) }}</span>
      </button>
    </div>
  </section>
</template>
