<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import ChatPanel from './components/ChatPanel.vue'
import EditorPanel from './components/EditorPanel.vue'
import ProjectSidebar from './components/ProjectSidebar.vue'
import SkillSettingsPage from './components/SkillSettingsPage.vue'
import ToolSettingsPage from './components/ToolSettingsPage.vue'
import { useApprovalStore } from './stores/approval'
import { useConfigStore } from './stores/config'
import { useCapabilityStore } from './stores/capabilities'
import { useConversationStore } from './stores/conversations'
import { useDiffStore } from './stores/diff'
import { useEventStore, TERMINAL_EVENT_TYPES } from './stores/events'
import { useProjectStore } from './stores/projects'
import { useRunStore } from './stores/runs'
import { useWorkspaceStore } from './stores/workspace'

const route = useRoute(); const router = useRouter()
const config = useConfigStore(); const capabilities = useCapabilityStore(); const projects = useProjectStore(); const conversations = useConversationStore(); const run = useRunStore(); const events = useEventStore(); const workspace = useWorkspaceStore(); const diff = useDiffStore(); const approval = useApprovalStore()
const editor = ref(null); const selectedChange = ref(null); const activePanel = ref('chat'); const rightPanel = ref('changes')
const theme = ref(readTheme())
const paneSizes = reactive(readPaneSizes())
const paneStorageKey = 'codeagent-pane-sizes-v1'
let stopResize = null

onMounted(() => { applyTheme(); normalizePaneSizes(); initialize() })
onBeforeUnmount(() => { events.disconnect(); stopResize?.() })

function readTheme() {
  if (typeof window === 'undefined') return 'dark'
  const saved = window.localStorage.getItem('codeagent-theme')
  return saved === 'light' || saved === 'dark' ? saved : 'dark'
}

function applyTheme() {
  document.documentElement.dataset.theme = theme.value
  window.localStorage.setItem('codeagent-theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme()
}

function readPaneSizes() {
  const fallback = { sidebar: 260, chat: 520 }
  if (typeof window === 'undefined') return fallback
  try {
    const saved = JSON.parse(window.localStorage.getItem('codeagent-pane-sizes-v1') || '{}')
    return {
      sidebar: Number.isFinite(saved.sidebar) ? saved.sidebar : fallback.sidebar,
      chat: Number.isFinite(saved.chat) ? saved.chat : fallback.chat,
    }
  } catch { return fallback }
}

function paneMaximum(pane) {
  const width = typeof window === 'undefined' ? 1440 : window.innerWidth
  if (pane === 'sidebar') return Math.max(190, Math.min(420, width - paneSizes.chat - 370))
  const sidebar = projects.drawerOpen ? paneSizes.sidebar : 0
  return Math.max(340, width - sidebar - 370)
}

function setPaneSize(pane, value) {
  const minimum = pane === 'sidebar' ? 190 : 340
  paneSizes[pane] = Math.round(Math.min(paneMaximum(pane), Math.max(minimum, value)))
  window.localStorage.setItem(paneStorageKey, JSON.stringify(paneSizes))
}

function normalizePaneSizes() {
  if (window.innerWidth <= 900) return
  setPaneSize('sidebar', paneSizes.sidebar)
  setPaneSize('chat', paneSizes.chat)
}

function startResize(pane, event) {
  if (window.innerWidth <= 900) return
  event.preventDefault()
  const startX = event.clientX
  const startSize = paneSizes[pane]
  const move = (moveEvent) => setPaneSize(pane, startSize + moveEvent.clientX - startX)
  const finish = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', finish)
    document.body.classList.remove('resizing-panes')
    stopResize = null
  }
  stopResize?.()
  stopResize = finish
  document.body.classList.add('resizing-panes')
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', finish)
}

function adjustPane(pane, delta) { setPaneSize(pane, paneSizes[pane] + delta) }

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
  await capabilities.load(conversationId)
  await router.push(`/projects/${projects.currentId}/conversations/${conversationId}`)
  const latest = conversations.runs.at(-1)
  if (latest) { run.apply(latest); connectRun(latest.id) }
}

async function showCapabilities(view) { await capabilities.load(conversations.currentId); rightPanel.value = view; activePanel.value = 'editor' }

function connectRun(runId) {
  events.connect(runId, { onEvent: handleEvent })
}

async function submit(task) {
  const created = await run.submit(conversations.currentId, task)
  if (!created) return
  conversations.trackRun(created)
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
  rightPanel.value = 'changes'
  selectedChange.value = change
  await diff.openChange(runId, change.id)
  if (change.change_type !== 'deleted') await workspace.openFile(projects.currentId, change.path)
  await nextTick(); editor.value?.select('diff'); activePanel.value = 'editor'
}

async function openCurrentFile(path) { rightPanel.value = 'changes'; selectedChange.value = null; await workspace.openFile(projects.currentId, path); await nextTick(); editor.value?.select('current'); activePanel.value = 'editor' }
</script>

<template>
  <main class="app-shell">
    <AppHeader :store="config" :theme="theme" @toggle-theme="toggleTheme" />
    <nav class="mobile-tabs"><button type="button" @click="activePanel = 'projects'">项目</button><button type="button" @click="activePanel = 'chat'">对话</button><button type="button" @click="activePanel = 'editor'">{{ rightPanel === 'changes' ? '变更' : '设置' }}</button></nav>
    <div class="codex-layout" :class="{ 'sidebar-collapsed': !projects.drawerOpen }" :style="{ '--sidebar-width': `${paneSizes.sidebar}px`, '--chat-width': `${paneSizes.chat}px` }">
      <ProjectSidebar class="project-slot" :class="{ 'is-active': activePanel === 'projects' }" :projects="projects" :conversations="conversations" :workspace="workspace" @select-project="selectProject" @select-conversation="selectConversation" @open-file="openCurrentFile" />
      <button class="pane-resizer sidebar-resizer" type="button" role="separator" aria-label="调整项目栏宽度" aria-orientation="vertical" @pointerdown="startResize('sidebar', $event)" @keydown.left.prevent="adjustPane('sidebar', -12)" @keydown.right.prevent="adjustPane('sidebar', 12)" />
      <ChatPanel class="chat-slot" :class="{ 'is-active': activePanel === 'chat' }" :right-panel="rightPanel" :conversations="conversations" :run="run" :event-store="events" :approval="approval" @submit="submit" @open-change="openChange" @show-capabilities="showCapabilities" />
      <button class="pane-resizer chat-resizer" type="button" role="separator" aria-label="调整对话与右侧区域宽度" aria-orientation="vertical" @pointerdown="startResize('chat', $event)" @keydown.left.prevent="adjustPane('chat', -12)" @keydown.right.prevent="adjustPane('chat', 12)" />
      <ToolSettingsPage v-if="rightPanel === 'tools'" class="settings-slot" :class="{ 'is-active': activePanel === 'editor' }" :store="capabilities" :conversations="conversations" :run="run" />
      <SkillSettingsPage v-else-if="rightPanel === 'skills'" class="settings-slot" :class="{ 'is-active': activePanel === 'editor' }" :store="capabilities" :conversations="conversations" :run="run" />
      <EditorPanel v-else ref="editor" class="editor-slot" :class="{ 'is-active': activePanel === 'editor' }" :workspace="workspace" :diff-store="diff" :selected-change="selectedChange" />
    </div>
  </main>
</template>
