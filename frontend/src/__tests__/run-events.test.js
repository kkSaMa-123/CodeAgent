import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useEventStore } from '../stores/events'

class FakeSource {
  constructor() { this.listeners = {}; this.closed = false }
  addEventListener(type, callback) { this.listeners[type] = callback }
  emit(type, data) { this.listeners[type]?.({ data: JSON.stringify(data) }) }
  close() { this.closed = true }
}

beforeEach(() => setActivePinia(createPinia()))

it('按 run_id 和 sequence 隔离事件并在终态正常关闭', () => {
  const store = useEventStore(); const source = new FakeSource()
  store.connect('r1', { client: { eventUrl: () => '/events' }, sourceFactory: () => source, scheduler: vi.fn() })
  source.emit('tool.started', { run_id: 'other', sequence: 1, event_type: 'tool.started', payload: { tool_call_id: 'x' } })
  source.emit('tool.started', { run_id: 'r1', sequence: 1, event_type: 'tool.started', payload: { tool_call_id: 'x', name: 'read' } })
  source.emit('task.completed', { run_id: 'r1', sequence: 2, event_type: 'task.completed', payload: {} })
  expect(store.events).toHaveLength(2); expect(store.toolTraces).toHaveLength(1)
  expect(store.connectionStatus).toBe('ended'); expect(source.closed).toBe(true)
})

it('切换运行会关闭旧 EventSource 并清空旧轨迹', () => {
  const store = useEventStore(); const first = new FakeSource(); const second = new FakeSource()
  let count = 0
  store.connect('r1', { client: { eventUrl: () => '/events' }, sourceFactory: () => count++ ? second : first })
  first.emit('tool.started', { run_id: 'r1', sequence: 1, event_type: 'tool.started', payload: { tool_call_id: 'x' } })
  store.connect('r2', { client: { eventUrl: () => '/events' }, sourceFactory: () => second })
  expect(first.closed).toBe(true); expect(store.runId).toBe('r2'); expect(store.events).toEqual([])
})

it('工具轨迹保留结构化命令错误详情', () => {
  const store = useEventStore()
  store.reset('r1')
  store.ingest({ run_id: 'r1', sequence: 1, event_type: 'tool.started', payload: { tool_call_id: 'cmd', name: 'run_command', command: 'g++ main.cpp' } })
  store.ingest({ run_id: 'r1', sequence: 2, event_type: 'tool.completed', payload: {
    tool_call_id: 'cmd', name: 'run_command', status: 'error', summary: '命令以退出码 1 结束', error_type: 'command_failed',
    metadata: { exit_code: 1 }, details: { command: 'g++ main.cpp', exit_code: 1, stderr: 'compile error' }, modified_files: [],
  } })
  const trace = store.toolTraces[0]
  expect(trace.command).toBe('g++ main.cpp')
  expect(trace.errorType).toBe('command_failed')
  expect(trace.details.stderr).toBe('compile error')
  expect(trace.metadata.exit_code).toBe(1)
  expect(store.groupedToolTraces).toHaveLength(1)
  expect(store.groupedToolTraces[0].count).toBe(1)
  expect(store.groupedToolTraces[0].errorCount).toBe(1)
})

it('相同工具调用聚合为一组并累加耗时', () => {
  const store = useEventStore(); store.reset('r1')
  for (const [sequence, id, timestamp, type] of [
    [1, 'a', '2026-01-01T00:00:00.000Z', 'tool.started'], [2, 'a', '2026-01-01T00:00:00.100Z', 'tool.completed'],
    [3, 'b', '2026-01-01T00:00:01.000Z', 'tool.started'], [4, 'b', '2026-01-01T00:00:01.200Z', 'tool.completed'],
  ]) store.ingest({ run_id: 'r1', sequence, timestamp, event_type: type, payload: { tool_call_id: id, name: 'read_file', ...(type === 'tool.completed' ? { status: 'success' } : {}) } })
  expect(store.groupedToolTraces).toHaveLength(1)
  expect(store.groupedToolTraces[0].count).toBe(2)
  expect(store.groupedToolTraces[0].durationSeconds).toBeCloseTo(0.3)
})

it('流式累积多轮思考内容并展示模型重试状态', () => {
  const store = useEventStore(); store.reset('r1')
  store.ingest({ run_id: 'r1', sequence: 1, event_type: 'model.started', payload: { iteration: 1 } })
  store.ingest({ run_id: 'r1', sequence: 2, event_type: 'model.reasoning.delta', payload: { content: '先读取文件。' } })
  store.ingest({ run_id: 'r1', sequence: 3, event_type: 'model.started', payload: { iteration: 2 } })
  store.ingest({ run_id: 'r1', sequence: 4, event_type: 'model.reasoning.delta', payload: { content: '然后修复测试。' } })
  expect(store.reasoningText).toBe('先读取文件。\n\n然后修复测试。')

  store.ingest({ run_id: 'r1', sequence: 5, event_type: 'model.retrying', payload: { attempt: 2, error_kind: 'request_timeout' } })
  expect(store.activity.label).toContain('第 2 次重试')
})
