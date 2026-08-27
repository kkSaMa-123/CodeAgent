import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ToolTraceCard from '../components/ToolTraceCard.vue'
import { useEventStore } from '../stores/events'

class FakeEventSource {
  constructor(url) { this.url = url; this.listeners = {}; this.closed = false }
  addEventListener(type, handler) { this.listeners[type] = handler }
  emit(type, data) { this.listeners[type]?.({ data: JSON.stringify(data) }) }
  close() { this.closed = true }
}

const event = (session, sequence, type, payload = {}) => ({
  session_id: session, sequence, event_type: type, timestamp: '2026-01-01T00:00:00Z', payload,
})

beforeEach(() => setActivePinia(createPinia()))

describe('SSE eventStore', () => {
  it('按 sequence 去重并隔离不同会话', () => {
    const store = useEventStore()
    store.reset('s1')
    expect(store.ingest(event('s1', 1, 'model.started'))).toBe(true)
    expect(store.ingest(event('s1', 1, 'model.started'))).toBe(false)
    expect(store.ingest(event('s2', 2, 'model.started'))).toBe(false)
    expect(store.events).toHaveLength(1)
    expect(store.lastSequence).toBe(1)
  })

  it('断线后携带最后 sequence 重连并继续去重', () => {
    const store = useEventStore()
    const sources = []
    const client = { eventUrl: vi.fn((id, sequence) => `/events/${id}?last_event_id=${sequence}`) }
    const sourceFactory = (url) => { const source = new FakeEventSource(url); sources.push(source); return source }
    const scheduler = (callback) => { callback(); return 1 }

    store.connect('s1', { client, sourceFactory, scheduler })
    sources[0].onopen()
    sources[0].emit('model.started', event('s1', 3, 'model.started', { iteration: 1 }))
    sources[0].onerror()

    expect(sources).toHaveLength(2)
    expect(sources[0].closed).toBe(true)
    expect(sources[1].url).toContain('last_event_id=3')
    sources[1].emit('model.completed', event('s1', 3, 'model.completed'))
    sources[1].emit('model.completed', event('s1', 4, 'model.completed'))
    expect(store.events.map((item) => item.sequence)).toEqual([3, 4])
  })

  it('缓冲过期时从快照恢复状态', () => {
    const store = useEventStore()
    const snapshots = []
    const source = new FakeEventSource('/events')
    store.connect('s1', { client: { eventUrl: () => '/events' }, sourceFactory: () => source, onSnapshot: (value) => snapshots.push(value) })
    source.emit('snapshot', { session_id: 's1', latest_sequence: 18, status: 'running' })
    expect(store.compressed).toBe(true)
    expect(store.lastSequence).toBe(18)
    expect(snapshots[0].status).toBe('running')
  })

  it.each(['task.completed', 'task.failed', 'task.cancelled'])('收到终态事件 %s 后正常结束且不再重连', (type) => {
    const store = useEventStore()
    const sources = []
    const scheduler = vi.fn()
    const sourceFactory = (url) => { const source = new FakeEventSource(url); sources.push(source); return source }
    store.connect('s1', { client: { eventUrl: () => '/events' }, sourceFactory, scheduler })
    sources[0].emit(type, event('s1', 8, type, { reason: type }))

    expect(store.terminalReached).toBe(true)
    expect(store.connectionStatus).toBe('ended')
    expect(store.error).toBe('')
    expect(sources[0].closed).toBe(true)
    sources[0].onerror()
    expect(scheduler).not.toHaveBeenCalled()
    expect(sources).toHaveLength(1)
  })

  it.each(['completed', 'failed', 'cancelled'])('终态快照 %s 会关闭事件流且禁止再次连接', (status) => {
    const store = useEventStore()
    const source = new FakeEventSource('/events')
    const factory = vi.fn().mockReturnValue(source)
    store.connect('s1', { client: { eventUrl: () => '/events' }, sourceFactory: factory })
    source.emit('snapshot', { session_id: 's1', latest_sequence: 12, status })
    store.connect('s1', { client: { eventUrl: () => '/events' }, sourceFactory: factory })

    expect(store.connectionStatus).toBe('ended')
    expect(store.error).toBe('')
    expect(source.closed).toBe(true)
    expect(factory).toHaveBeenCalledOnce()
  })
})

describe('工具轨迹归并', () => {
  it('started 和 completed 事件按调用 ID 合并为一张卡片', async () => {
    const store = useEventStore()
    store.reset('s1')
    store.ingest(event('s1', 1, 'tool.started', { tool_call_id: 'call-1', name: 'read_file' }))
    store.ingest(event('s1', 2, 'tool.completed', { tool_call_id: 'call-1', name: 'read_file', status: 'success' }))
    expect(store.toolTraces).toHaveLength(1)
    expect(store.toolTraces[0].events).toHaveLength(2)

    const wrapper = mount(ToolTraceCard, { props: { trace: store.toolTraces[0] } })
    expect(wrapper.text()).toContain('read_file')
    await wrapper.get('button').trigger('click')
    expect(wrapper.findAll('.trace-detail div')).toHaveLength(2)
  })

  it('不同调用 ID 保持独立且忽略无法关联的无 ID 事件', () => {
    const store = useEventStore()
    store.reset('s1')
    store.ingest(event('s1', 1, 'tool.started', { tool_call_id: 'a', name: 'read_file' }))
    store.ingest(event('s1', 2, 'tool.completed', { name: 'orphan', status: 'success' }))
    store.ingest(event('s1', 3, 'tool.started', { tool_call_id: 'b', name: 'git_diff' }))
    expect(store.toolTraces.map((item) => item.id)).toEqual(['a', 'b'])
  })
})
