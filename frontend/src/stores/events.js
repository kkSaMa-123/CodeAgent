import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { apiClient } from '../api/client'

export const EVENT_TYPES = [
  'state.changed', 'model.started', 'model.retrying', 'model.completed', 'model.error',
  'tool.started', 'tool.completed', 'tool.repeated', 'approval.requested',
  'approval.resolved', 'files.changed', 'task.completed', 'task.failed', 'task.cancelled',
]

export const TERMINAL_EVENT_TYPES = new Set(['task.completed', 'task.failed', 'task.cancelled'])
export const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export const useEventStore = defineStore('events', {
  state: () => ({
    sessionId: '', events: [], lastSequence: 0, connectionStatus: 'idle', error: '',
    compressed: false, source: null, reconnectTimer: null, reconnectDelay: 500,
    terminalReached: false,
  }),
  getters: {
    toolTraces(state) {
      const calls = new Map()
      for (const event of state.events) {
        if (!event.event_type.startsWith('tool.')) continue
        const id = event.payload?.tool_call_id
        if (!id) continue
        const current = calls.get(id) || { id, name: event.payload.name || 'tool', status: 'running', events: [] }
        current.name = event.payload.name || current.name
        current.events.push(event)
        if (event.event_type === 'tool.completed') current.status = event.payload.status || 'completed'
        if (event.event_type === 'tool.repeated') current.status = event.payload.action === 'stop' ? 'failed' : 'warning'
        calls.set(id, current)
      }
      return [...calls.values()]
    },
  },
  actions: {
    reset(sessionId) {
      this.disconnect()
      this.sessionId = sessionId
      this.events = []
      this.lastSequence = 0
      this.connectionStatus = 'idle'
      this.error = ''
      this.compressed = false
      this.terminalReached = false
    },
    ingest(event, expectedSessionId = this.sessionId) {
      if (!event || event.session_id !== expectedSessionId || expectedSessionId !== this.sessionId) return false
      if (!Number.isInteger(event.sequence) || event.sequence <= this.lastSequence) return false
      this.events.push(event)
      this.lastSequence = event.sequence
      return true
    },
    applySnapshot(snapshot, onSnapshot) {
      if (!snapshot || snapshot.session_id !== this.sessionId) return false
      this.lastSequence = Math.max(this.lastSequence, snapshot.latest_sequence || 0)
      this.compressed = true
      onSnapshot?.(snapshot)
      if (TERMINAL_STATUSES.has(snapshot.status)) {
        this.finishStream()
      }
      return true
    },
    connect(sessionId, {
      client = apiClient,
      sourceFactory = (url) => new EventSource(url),
      scheduler = (callback, delay) => window.setTimeout(callback, delay),
      onEvent,
      onSnapshot,
    } = {}) {
      if (this.sessionId !== sessionId) this.reset(sessionId)
      if (this.terminalReached) {
        this.connectionStatus = 'ended'
        this.error = ''
        return
      }
      this.disconnectSource()
      const source = markRaw(sourceFactory(client.eventUrl(sessionId, this.lastSequence)))
      this.source = source
      this.connectionStatus = 'connecting'
      source.onopen = () => { this.connectionStatus = 'connected'; this.error = '' }
      source.addEventListener('snapshot', (message) => {
        try { this.applySnapshot(JSON.parse(message.data), onSnapshot) }
        catch { this.error = '事件快照无法解析。' }
      })
      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (message) => {
          try {
            const event = JSON.parse(message.data)
            if (this.ingest(event, sessionId)) {
              onEvent?.(event)
              if (TERMINAL_EVENT_TYPES.has(event.event_type)) this.finishStream()
            }
          } catch { this.error = '实时事件无法解析。' }
        })
      }
      source.onerror = () => {
        if (source !== this.source) return
        if (this.terminalReached) {
          this.finishStream()
          return
        }
        this.connectionStatus = 'reconnecting'
        this.error = '实时连接已中断，正在恢复…'
        this.disconnectSource()
        this.reconnectTimer = scheduler(() => this.connect(sessionId, { client, sourceFactory, scheduler, onEvent, onSnapshot }), this.reconnectDelay)
      }
    },
    disconnectSource() {
      this.source?.close?.()
      this.source = null
    },
    finishStream() {
      this.terminalReached = true
      this.connectionStatus = 'ended'
      this.error = ''
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
      this.disconnectSource()
    },
    disconnect() {
      this.disconnectSource()
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
      if (this.connectionStatus !== 'idle') this.connectionStatus = 'closed'
    },
  },
})
