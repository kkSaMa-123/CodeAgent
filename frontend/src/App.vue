<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import ChatPanel from './components/ChatPanel.vue'
import EditorPanel from './components/EditorPanel.vue'
import ProjectSidebar from './components/ProjectSidebar.vue'
import { useApprovalStore } from './stores/approval'
import { useConfigStore } from './stores/config'
import { useConversationStore } from './stores/conversations'
import { useDiffStore } from './stores/diff'
import { useEventStore, TERMINAL_EVENT_TYPES } from './stores/events'
import { useProjectStore } from './stores/projects'
import { useRunStore } from './stores/runs'
import { useWorkspaceStore } from './stores/workspace'

const route = useRoute(); const router = useRouter()
const config = useConfigStore(); const projects = useProjectStore(); const conversations = useConversationStore(); const run = useRunStore(); const events = useEventStore(); const workspace = useWorkspaceStore(); const diff = useDiffStore(); const approval = useApprovalStore()
const editor = ref(null); const selectedChange = ref(null); const activePanel = ref('chat')

onMounted(initialize)
onBeforeUnmount(() => events.disconnect())

async function initialize() {
  await Promise.all([config.load(), projects.load()])
  const requested = route.params.projectId
  const project = projects.items.find((item) => item.id === requested) || projects.items[0]
  if (!project) { await router.replace('/projects'); return }
  await selectProject(project.id, route.params.conversationId)
}

async function selectProject(projectId, requestedConversation = '') {
  events.reset(''); run.reset(); diff.reset(); approval.pending = null; selectedChange.value = null
  projects.select(projectId)
  await Promise.all([conversations.load(projectId), workspace.loadTree(projectId)])
  const conversation = conversations.items.find((item) => item.id === requestedConversation) || conversations.items[0]
  if (conversation) await selectConversation(conversation.id)
  else await router.push(`/projects/${projectId}`)
}

async function selectConversation(conversationId) {
  events.reset(''); run.reset(); diff.reset(); approval.pending = null; selectedChange.value = null
  if (!await conversations.select(conversationId)) return
  await router.push(`/projects/${projects.currentId}/conversations/${conversationId}`)
  const latest = conversations.runs.at(-1)
  if (latest) { run.apply(latest); connectRun(latest.id) }
}

function connectRun(runId) {
  events.connect(runId, { onEvent: handleEvent })
}

async function submit(task) {
  const created = await run.submit(conversations.currentId, task)
  if (!created) return
  await conversations.refresh()
  connectRun(created.id)
}

async function handleEvent(event) {
  run.applyEvent(event); approval.handleEvent(event)
  if (event.event_type === 'approval.requested') return
  if (TERMINAL_EVENT_TYPES.has(event.event_type)) {
    await run.refresh(); await conversations.refresh(); await workspace.loadTree(projects.currentId)
  }
}

async function openChange(runId, change) {
  selectedChange.value = change
  await diff.openChange(runId, change.id)
  if (change.change_type !== 'deleted') await workspace.openFile(projects.currentId, change.path)
  await nextTick(); editor.value?.select('diff'); activePanel.value = 'editor'
}

async function openCurrentFile(path) { selectedChange.value = null; await workspace.openFile(projects.currentId, path); await nextTick(); editor.value?.select('current'); activePanel.value = 'editor' }
</script>

<template>
  <main class="app-shell">
    <AppHeader :store="config" />
    <nav class="mobile-tabs"><button type="button" @click="activePanel = 'projects'">项目</button><button type="button" @click="activePanel = 'chat'">对话</button><button type="button" @click="activePanel = 'editor'">变更</button></nav>
    <div class="codex-layout">
      <ProjectSidebar class="project-slot" :class="{ 'is-active': activePanel === 'projects' }" :projects="projects" :conversations="conversations" :workspace="workspace" @select-project="selectProject" @select-conversation="selectConversation" @open-file="openCurrentFile" />
      <ChatPanel class="chat-slot" :class="{ 'is-active': activePanel === 'chat' }" :conversations="conversations" :run="run" :event-store="events" :approval="approval" @submit="submit" @open-change="openChange" />
      <EditorPanel ref="editor" class="editor-slot" :class="{ 'is-active': activePanel === 'editor' }" :workspace="workspace" :diff-store="diff" :selected-change="selectedChange" />
    </div>
  </main>
</template>
