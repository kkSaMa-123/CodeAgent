<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AppHeader from './components/AppHeader.vue'
import ApprovalDialog from './components/ApprovalDialog.vue'
import ChatPanel from './components/ChatPanel.vue'
import EditorPanel from './components/EditorPanel.vue'
import WorkspacePanel from './components/WorkspacePanel.vue'
import { useConfigStore } from './stores/config'
import { apiClient } from './api/client'
import { useApprovalStore } from './stores/approval'
import { useDiffStore } from './stores/diff'
import { useEventStore } from './stores/events'
import { useSessionStore } from './stores/session'
import { useWorkspaceStore } from './stores/workspace'

const config = useConfigStore()
const workspace = useWorkspaceStore()
const session = useSessionStore()
const events = useEventStore()
const diff = useDiffStore()
const approval = useApprovalStore()
const activePanel = ref('workspace')

onMounted(() => config.load())
onBeforeUnmount(() => { session.stopPolling(); events.disconnect() })

async function refreshSnapshot() {
  if (!session.sessionId) return
  try {
    const snapshot = await apiClient.getSession(session.sessionId)
    session.applySnapshot(snapshot)
    approval.syncFromSnapshot(snapshot)
  } catch (error) { session.error = error.message }
}

async function handleEvent(event) {
  session.applyEvent(event)
  approval.handleEvent(event)
  if (event.event_type === 'approval.requested' || event.event_type.startsWith('task.')) await refreshSnapshot()
  if (event.event_type === 'tool.completed' || event.event_type.startsWith('task.')) {
    await Promise.all([diff.load(session.sessionId), workspace.loadTree(session.sessionId)])
  }
}

async function openWorkspace(path) {
  const created = await session.create(path)
  if (created) {
    diff.reset()
    approval.syncFromSnapshot(created)
    events.connect(session.sessionId, { onEvent: handleEvent, onSnapshot: (snapshot) => { session.applySnapshot(snapshot); approval.syncFromSnapshot(snapshot) } })
    await workspace.loadTree(session.sessionId)
    activePanel.value = 'editor'
  }
}
</script>

<template>
  <main class="app-shell">
    <AppHeader :store="config" />
    <nav class="mobile-tabs" aria-label="工作台面板">
      <button v-for="item in [['workspace','文件'],['editor','预览'],['chat','Agent']]" :key="item[0]" type="button" :class="{ active: activePanel === item[0] }" @click="activePanel = item[0]">{{ item[1] }}</button>
    </nav>
    <div class="workbench">
      <WorkspacePanel class="workspace-slot" :class="{ 'is-active': activePanel === 'workspace' }" :store="workspace" :session-id="session.sessionId" @validated="openWorkspace" @open-file="workspace.openFile(session.sessionId, $event); activePanel = 'editor'" />
      <EditorPanel class="editor-slot" :class="{ 'is-active': activePanel === 'editor' }" :store="workspace" :diff-store="diff" :modified-files="session.modifiedFiles" @reload="workspace.reloadFile(session.sessionId)" @reload-diff="diff.load(session.sessionId)" @open-file="workspace.openFile(session.sessionId, $event)" />
      <ChatPanel class="chat-slot" :class="{ 'is-active': activePanel === 'chat' }" :store="session" :event-store="events" />
    </div>
    <ApprovalDialog :store="approval" :session-store="session" />
  </main>
</template>
