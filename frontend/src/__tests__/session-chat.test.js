import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPanel from '../components/ChatPanel.vue'
import { useSessionStore } from '../stores/session'

beforeEach(() => setActivePinia(createPinia()))

const snapshot = (status, extra = {}) => ({ session_id: 's1', status, iteration: 1, modified_files: [], ...extra })

describe('会话和任务交互', () => {
  it('运行期间阻止重复提交，并允许取消', async () => {
    const store = useSessionStore()
    store.sessionId = 's1'
    const client = {
      runTask: vi.fn().mockResolvedValue(snapshot('running')),
      cancelSession: vi.fn().mockResolvedValue(snapshot('cancelled', { termination_reason: 'user_cancelled' })),
    }
    expect(await store.run('修改代码', client, false)).toBe(true)
    expect(await store.run('重复任务', client, false)).toBe(false)
    expect(client.runTask).toHaveBeenCalledTimes(1)
    expect(await store.cancel(client)).toBe(true)
    expect(store.status).toBe('cancelled')
  })

  it('新建会话的 queued 快照不会阻止第一次任务提交', async () => {
    const store = useSessionStore()
    const client = {
      createSession: vi.fn().mockResolvedValue(snapshot('queued')),
      runTask: vi.fn().mockResolvedValue(snapshot('running')),
    }
    await store.create('/repo', client)
    expect(store.isActive).toBe(false)
    expect(await store.run('第一次任务', client, false)).toBe(true)
    expect(client.runTask).toHaveBeenCalledOnce()
  })

  it.each(['completed', 'failed', 'cancelled'])('显示终态 %s', async (status) => {
    const store = useSessionStore()
    store.sessionId = 's1'
    store.applySnapshot(snapshot(status, { termination_reason: `${status}_reason`, final_answer: status === 'completed' ? '任务完成' : '' }))
    const wrapper = mount(ChatPanel, { props: { store } })
    expect(wrapper.get('.status-badge').text()).toBe(status)
    expect(wrapper.get('.terminal-card').text()).toContain(status)
    expect(wrapper.text()).toContain(`${status}_reason`)
  })

  it('输入任务后显示消息，并在运行时切换为取消按钮', async () => {
    const store = useSessionStore()
    store.sessionId = 's1'
    store.run = vi.fn(async (task) => {
      store.messages.push({ kind: 'user', text: task })
      store.taskStarted = true
      store.status = 'running'
      return true
    })
    const wrapper = mount(ChatPanel, { props: { store } })
    await wrapper.get('textarea').setValue('补充测试')
    await wrapper.get('form').trigger('submit')
    expect(store.run).toHaveBeenCalledWith('补充测试')
    expect(wrapper.text()).toContain('补充测试')
    expect(wrapper.find('.danger').text()).toBe('取消')
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
  })
})
