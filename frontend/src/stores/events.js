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
const TOOL_ACTIONS = { list_files: '查看项目文件', read_file: '读取文件', search_text: '搜索代码', write_file: '写入文件', replace_in_file: '修改文件', git_diff: '查看代码变更', run_command: '运行命令' }

export function buildToolTraces(events = []) {
  const calls = new Map()
  for (const event of events) {
    if (!event.event_type.startsWith('tool.')) continue
    const id = event.payload?.tool_call_id
    if (!id) continue
    const current = calls.get(id) || { id, name: event.payload.name || 'tool', status: 'running', events: [] }
    current.name = event.payload.name || current.name
    current.events.push(event)
    if (event.payload.command) current.command = event.payload.command
    if (event.event_type === 'tool.completed') {
      current.status = event.payload.status || 'completed'
      current.summary = event.payload.summary || ''
      current.errorType = event.payload.error_type || ''
      current.output = event.payload.output || ''
      current.metadata = event.payload.metadata || {}
      current.details = event.payload.details || {}
      current.modifiedFiles = event.payload.modified_files || []
    }
    if (event.event_type === 'tool.repeated') current.status = event.payload.action === 'stop' ? 'failed' : 'warning'
    calls.set(id, current)
  }
  return [...calls.values()]
}

export function groupToolEvents(events = []) {
  const groups = new Map()
  for (const trace of buildToolTraces(events)) {
    const started = trace.events.find((event) => event.event_type === 'tool.started')
    const completed = trace.events.find((event) => event.event_type === 'tool.completed')
    const measured = started && completed ? Math.max(0, (Date.parse(completed.timestamp) - Date.parse(started.timestamp)) / 1000) : 0
    const duration = Number(trace.metadata?.duration_seconds ?? measured) || 0
    const group = groups.get(trace.name) || { name: trace.name, traces: [], count: 0, successCount: 0, errorCount: 0, durationSeconds: 0, status: 'success' }
    group.traces.push({ ...trace, durationSeconds: duration })
    group.count += 1
    group.durationSeconds += duration
    if (trace.status === 'success') group.successCount += 1
    else if (trace.status === 'running') group.status = 'running'
    else { group.errorCount += 1; if (group.status !== 'running') group.status = 'error' }
    groups.set(trace.name, group)
  }
  return [...groups.values()]
}

export const useEventStore = defineStore('events', {
  state: () => ({
    runId: '', events: [], lastSequence: 0, connectionStatus: 'idle', error: '',
    compressed: false, source: null, reconnectTimer: null, reconnectDelay: 500,
    terminalReached: false,
  }),
  getters: {
    toolTraces: (state) => buildToolTraces(state.events),
    activity(state) {
      if (state.connectionStatus === 'reconnecting') return { phase: 'reconnecting', label: '实时连接中断，正在恢复…', detail: 'Agent 仍可能在后端继续运行。' }
      const event = state.events.at(-1)
      if (!event) return { phase: 'thinking', label: 'Agent 正在分析任务…', detail: '' }
      if (event.event_type === 'tool.started') return { phase: 'tool', label: `正在${TOOL_ACTIONS[event.payload?.name] || `调用 ${event.payload?.name || '工具'}`}…`, detail: event.payload?.path || event.payload?.query || event.payload?.command || '' }
      if (event.event_type === 'tool.completed' || event.event_type === 'tool.repeated') return { phase: 'thinking', label: 'Agent 正在分析工具结果…', detail: '' }
      if (event.event_type === 'model.started') return { phase: 'thinking', label: 'Agent 正在分析任务…', detail: `第 ${event.payload?.iteration || 1} 轮` }
      if (event.event_type === 'model.completed') return { phase: 'planning', label: 'Agent 正在准备下一步操作…', detail: '' }
      if (event.event_type === 'approval.requested') return { phase: 'approval', label: '等待你确认命令', detail: '' }
      return { phase: 'preparing', label: '正在准备任务…', detail: '' }
    },
    groupedToolTraces: (state) => groupToolEvents(state.events),
  },
  actions: {
    reset(runId) {
      this.disconnect()
      this.runId = runId
      this.events = []
      this.lastSequence = 0
      this.connectionStatus = 'idle'
      this.error = ''
      this.compressed = false
      this.terminalReached = false
    },
    ingest(event, expectedRunId = this.runId) {
      if (!event || event.run_id !== expectedRunId || expectedRunId !== this.runId) return false
      if (!Number.isInteger(event.sequence) || event.sequence <= this.lastSequence) return false
      this.events.push(event)
      this.lastSequence = event.sequence
      return true
    },
    applySnapshot(snapshot, onSnapshot) {
      if (!snapshot || snapshot.id !== this.runId) return false
      this.lastSequence = Math.max(this.lastSequence, snapshot.latest_sequence || 0)
      this.compressed = true
      onSnapshot?.(snapshot)
      if (TERMINAL_STATUSES.has(snapshot.status)) {
        this.finishStream()
      }
      return true
    },
    connect(runId, {
      client = apiClient,
      sourceFactory = (url) => new EventSource(url),
      scheduler = (callback, delay) => window.setTimeout(callback, delay),
      onEvent,
      onSnapshot,
    } = {}) {
      if (this.runId !== runId) this.reset(runId)
      if (this.terminalReached) {
        this.connectionStatus = 'ended'
        this.error = ''
        return
      }
      this.disconnectSource()
      const source = markRaw(sourceFactory(client.eventUrl(runId, this.lastSequence)))
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
            if (this.ingest(event, runId)) {
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
        this.reconnectTimer = scheduler(() => this.connect(runId, { client, sourceFactory, scheduler, onEvent, onSnapshot }), this.reconnectDelay)
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
