import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const ACTIVE_STATUSES = ['queued', 'running', 'waiting_approval']
export const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled']

export const useSessionStore = defineStore('session', {
  state: () => ({
    sessionId: '', status: 'idle', iteration: 0, terminationReason: '', finalAnswer: '',
    modifiedFiles: [], messages: [], loading: false, error: '', pollTimer: null, taskStarted: false,
  }),
  getters: {
    isActive: (state) => state.taskStarted && ACTIVE_STATUSES.includes(state.status),
    isTerminal: (state) => state.taskStarted && TERMINAL_STATUSES.includes(state.status),
  },
  actions: {
    applySnapshot(snapshot) {
      this.status = snapshot.status
      if (snapshot.status !== 'queued' && snapshot.status !== 'idle') this.taskStarted = true
      this.iteration = snapshot.iteration || 0
      this.terminationReason = snapshot.termination_reason || ''
      this.finalAnswer = snapshot.final_answer || ''
      this.modifiedFiles = snapshot.modified_files || []
      if (this.finalAnswer && !this.messages.some((item) => item.kind === 'answer' && item.text === this.finalAnswer)) {
        this.messages.push({ kind: 'answer', text: this.finalAnswer })
      }
      if (TERMINAL_STATUSES.includes(this.status)) this.stopPolling()
    },
    async create(workspace, client = apiClient) {
      this.loading = true
      this.error = ''
      try {
        const snapshot = await client.createSession(workspace)
        this.sessionId = snapshot.session_id
        this.taskStarted = false
        this.applySnapshot(snapshot)
        return snapshot
      } catch (error) {
        this.status = 'failed'
        this.error = error.message
        return null
      } finally {
        this.loading = false
      }
    },
    async run(task, client = apiClient, poll = false) {
      if (this.isActive || !this.sessionId || !task.trim()) return false
      this.taskStarted = true
      this.status = 'queued'
      this.error = ''
      this.messages.push({ kind: 'user', text: task.trim() })
      try {
        const snapshot = await client.runTask(this.sessionId, task.trim())
        if (snapshot.status) this.applySnapshot(snapshot)
        if (poll && this.isActive) this.startPolling(client)
        return true
      } catch (error) {
        this.status = 'failed'
        this.error = error.message
        return false
      }
    },
    applyEvent(event) {
      if (event.session_id !== this.sessionId) return
      if (event.event_type === 'state.changed') {
        this.status = event.payload.current
        if (this.status !== 'queued') this.taskStarted = true
      }
      if (event.event_type.startsWith('task.')) {
        this.status = event.event_type.slice(5)
        this.terminationReason = event.payload.reason || ''
        this.taskStarted = true
      }
      if (event.event_type === 'model.started') this.iteration = event.payload.iteration || this.iteration
    },
    startPolling(client = apiClient) {
      this.stopPolling()
      this.pollTimer = window.setInterval(async () => {
        try { this.applySnapshot(await client.getSession(this.sessionId)) }
        catch (error) { this.error = error.message }
      }, 700)
    },
    stopPolling() {
      if (this.pollTimer) window.clearInterval(this.pollTimer)
      this.pollTimer = null
    },
    async cancel(client = apiClient) {
      if (!this.isActive) return false
      try {
        this.applySnapshot(await client.cancelSession(this.sessionId))
        return true
      } catch (error) {
        this.error = error.message
        return false
      }
    },
  },
})
