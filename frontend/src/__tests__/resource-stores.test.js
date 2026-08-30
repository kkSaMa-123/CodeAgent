import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '../stores/projects'
import { useConversationStore } from '../stores/conversations'
import { useRunStore } from '../stores/runs'

beforeEach(() => setActivePinia(createPinia()))

describe('项目、对话与运行 Store', () => {
  it('加载最近项目并在切换项目时清理对话状态', async () => {
    const projects = useProjectStore(); const conversations = useConversationStore()
    const client = { listProjects: vi.fn().mockResolvedValue([{ id: 'p1', name: 'One' }]), listConversations: vi.fn().mockResolvedValue([]) }
    await projects.load(client); projects.select('p1'); conversations.messages = [{ content: 'old' }]
    await conversations.load('p1', client)
    expect(projects.current.name).toBe('One'); expect(conversations.messages).toEqual([])
  })

  it('恢复多轮消息、运行和每轮修改', async () => {
    const store = useConversationStore()
    const client = {
      listConversations: vi.fn().mockResolvedValue([{ id: 'c1', title: '任务' }]),
      getMessages: vi.fn().mockResolvedValue([{ run_id: 'r1', role: 'user', content: '第一轮' }]),
      getRuns: vi.fn().mockResolvedValue([{ id: 'r1', status: 'completed' }]),
      getChanges: vi.fn().mockResolvedValue([{ id: 'f1', path: 'app.py' }]),
      getRunEvents: vi.fn().mockResolvedValue([
        { sequence: 1, timestamp: '2026-01-01T00:00:00Z', event_type: 'tool.started', payload: { tool_call_id: 't1', name: 'read_file', path: 'app.py' } },
        { sequence: 2, timestamp: '2026-01-01T00:00:00.1Z', event_type: 'tool.completed', payload: { tool_call_id: 't1', name: 'read_file', status: 'success' } },
      ]),
      getRunCapabilities: vi.fn().mockResolvedValue({ enabled_tools: ['read_file'], skills: [], legacy: false }),
    }
    await store.load('p1', client); await store.select('c1', client)
    expect(store.messages[0].content).toBe('第一轮'); expect(store.changesByRun.r1[0].path).toBe('app.py')
    expect(store.toolGroupsByRun.r1[0].name).toBe('read_file')
    expect(store.toolGroupsByRun.r1[0].count).toBe(1)
  })

  it('同一对话活动运行时拒绝前端重复提交并隔离晚到事件', async () => {
    const store = useRunStore(); store.apply({ id: 'r1', status: 'running' })
    const client = { runTask: vi.fn() }
    expect(await store.submit('c1', 'duplicate', client)).toBeNull(); expect(client.runTask).not.toHaveBeenCalled()
    expect(store.applyEvent({ run_id: 'other', event_type: 'task.completed', payload: {} })).toBe(false)
    expect(store.status).toBe('running')
  })

  it('提交后立即进入 queued 并保留乐观用户消息', async () => {
    const store = useRunStore(); store.apply({ id: 'previous', status: 'completed', final_answer: '上一轮' })
    let finishRequest
    const client = { runTask: vi.fn(() => new Promise((resolve) => { finishRequest = resolve })) }
    const submission = store.submit('c1', '  修复测试  ', client)
    expect(store.status).toBe('queued')
    expect(store.runId).toBe('')
    expect(store.pendingTask).toBe('修复测试')
    expect(store.startedAt).toEqual(expect.any(Number))
    finishRequest({ id: 'r1', status: 'running' })
    await submission
    expect(store.runId).toBe('r1')
    expect(store.status).toBe('running')
  })

  it('新运行可立即加入对话以承载实时工具事件', () => {
    const store = useConversationStore()
    store.runs = [{ id: 'old', status: 'completed' }]

    expect(store.trackRun({ id: 'r1', status: 'running' })).toBe(true)
    expect(store.runs.map((item) => item.id)).toEqual(['old', 'r1'])
    store.trackRun({ id: 'r1', status: 'completed' })
    expect(store.runs.find((item) => item.id === 'r1').status).toBe('completed')
  })
})
