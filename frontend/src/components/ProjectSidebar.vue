<script setup>
import { ref } from 'vue'

const props = defineProps({ projects: { type: Object, required: true }, conversations: { type: Object, required: true }, workspace: { type: Object, required: true } })
const emit = defineEmits(['select-project', 'select-conversation', 'open-file'])
const projectPath = ref('')

async function addProject() {
  const item = await props.projects.add(projectPath.value)
  if (item) { projectPath.value = ''; emit('select-project', item.id) }
}
async function renameProject(item) { const name = window.prompt('项目名称', item.name); if (name) await props.projects.rename(item.id, name) }
async function removeProject(item) { if (window.confirm(`从 CodeAgent 移除“${item.name}”？不会删除本地文件。`)) await props.projects.remove(item.id) }
async function renameConversation(item) { const title = window.prompt('对话标题', item.title); if (title) await props.conversations.rename(item.id, title) }
async function removeConversation(item) { if (window.confirm(`删除对话“${item.title}”？不会修改项目文件。`)) await props.conversations.remove(item.id) }
function fileName(path) { return path.split('/').at(-1) || path }
function fileDepth(path) { return Math.max(0, path.split('/').length - 1) }
function fileSize(size) {
  if (size === undefined || size === null) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <aside class="project-sidebar" :class="{ collapsed: !projects.drawerOpen }">
    <header class="sidebar-heading"><strong>项目</strong><button class="icon-button" type="button" aria-label="折叠项目栏" @click="projects.drawerOpen = !projects.drawerOpen">{{ projects.drawerOpen ? '‹' : '›' }}</button></header>
    <template v-if="projects.drawerOpen">
      <form class="project-add" @submit.prevent="addProject"><input v-model="projectPath" aria-label="项目文件夹" placeholder="本地项目绝对路径" /><button class="primary compact" :disabled="!projectPath.trim()">添加</button></form>
      <p v-if="projects.error" class="inline-error">{{ projects.error }} <button type="button" @click="projects.load()">重试</button></p>
      <div v-if="!projects.loading && !projects.items.length" class="sidebar-empty"><strong>还没有项目</strong><span>添加一个本地文件夹开始工作。</span></div>
      <div class="project-list">
        <section v-for="project in projects.items" :key="project.id" class="project-group">
          <div class="project-row" :class="{ selected: project.id === projects.currentId, unavailable: !project.available }">
            <button class="project-main" type="button" @click="emit('select-project', project.id)"><span>{{ project.name }}</span><small>{{ project.available ? project.workspace : '文件夹不可用' }}</small></button>
            <button type="button" title="重命名" @click="renameProject(project)">✎</button><button type="button" title="从 CodeAgent 移除" @click="removeProject(project)">×</button>
          </div>
          <div v-if="project.id === projects.currentId" class="conversation-list">
            <button class="new-conversation" type="button" @click="conversations.create().then((item) => item && emit('select-conversation', item.id))">＋ 新对话</button>
            <div v-for="conversation in conversations.items" :key="conversation.id" class="conversation-row" :class="{ selected: conversation.id === conversations.currentId }">
              <button type="button" class="conversation-main" @click="emit('select-conversation', conversation.id)"><span>◌</span>{{ conversation.title }}</button>
              <button type="button" title="重命名" @click="renameConversation(conversation)">✎</button><button type="button" title="删除对话" @click="removeConversation(conversation)">×</button>
            </div>
          </div>
        </section>
      </div>
      <section v-if="projects.currentId" class="sidebar-files">
        <div class="sidebar-section-title"><span>项目文件 · {{ projects.current?.name }}</span><button type="button" aria-label="刷新项目文件" @click="props.workspace.loadTree(projects.currentId)">↻</button></div>
        <p v-if="props.workspace.error" class="inline-error">{{ props.workspace.error }}</p>
        <div v-else-if="props.workspace.loading" class="sidebar-file-state">正在读取文件夹…</div>
        <div v-else-if="!props.workspace.entries.length" class="sidebar-file-state">文件夹为空</div>
        <button v-for="entry in props.workspace.visibleEntries" :key="entry.path" type="button" class="sidebar-file" :class="{ selected: entry.path === props.workspace.currentFile }" :style="{ paddingLeft: `${10 + fileDepth(entry.path) * 13}px` }" :title="entry.path" @click="entry.type === 'directory' ? props.workspace.toggleDirectory(entry.path) : emit('open-file', entry.path)">
          <span class="file-tree-icon">{{ entry.type === 'directory' ? (props.workspace.expanded.includes(entry.path) ? '▾' : '▸') : '·' }}</span>
          <span class="file-tree-name">{{ fileName(entry.path) }}</span>
          <small v-if="entry.type === 'file'">{{ fileSize(entry.size) }}</small>
        </button>
      </section>
    </template>
  </aside>
</template>
