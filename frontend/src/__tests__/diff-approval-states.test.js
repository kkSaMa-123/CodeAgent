import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ApprovalDialog from '../components/ApprovalDialog.vue'
import DiffViewer from '../components/DiffViewer.vue'
import TerminalSummary from '../components/TerminalSummary.vue'
import { ApiError } from '../api/client'
import { useApprovalStore } from '../stores/approval'
import { useDiffStore } from '../stores/diff'
import { useSessionStore } from '../stores/session'

beforeEach(() => setActivePinia(createPinia()))

describe('累计 Diff', () => {
  it('区分新增、删除、修改上下文并显示修改文件', async () => {
    const store = useDiffStore()
    await store.load('s1', { getDiff: vi.fn().mockResolvedValue({ diff: [
      'diff --git a/a.py b/a.py', '--- a/a.py', '+++ b/a.py', '@@ -1,2 +1,2 @@', '-old', '+new', ' same',
    ].join('\n') }) })
    const wrapper = mount(DiffViewer, { props: { store, modifiedFiles: ['a.py'] } })
    expect(wrapper.findAll('.diff-line.addition')).toHaveLength(1)
    expect(wrapper.findAll('.diff-line.deletion')).toHaveLength(1)
    expect(wrapper.findAll('.diff-line.hunk')).toHaveLength(1)
    expect(wrapper.get('.changed-files').text()).toContain('a.py')
  })

  it('分别呈现空 diff、加载中和可恢复错误', async () => {
    const store = useDiffStore()
    const empty = mount(DiffViewer, { props: { store } })
    expect(empty.text()).toContain('暂无代码差异')
    store.loading = true
    await nextTick()
    expect(empty.text()).toContain('正在生成累计差异')
    store.loading = false
    store.error = '后端暂时不可达'
    await nextTick()
    expect(empty.get('[role="alert"]').text()).toContain('后端暂时不可达')
    expect(empty.text()).toContain('重试')
  })
})

describe('阻塞式审批', () => {
  const pending = { approval_id: 'approval-1', command: 'rm generated.txt', workspace: '/repo', reason: '删除文件', expires_at: '2026-01-01T00:00:00Z' }

  it('展示完整安全上下文并提供批准、拒绝、取消', async () => {
    const actions = { pending, loading: false, error: '', resolve: vi.fn(), cancel: vi.fn() }
    const session = { sessionId: 's1' }
    const wrapper = mount(ApprovalDialog, { props: { store: actions, sessionStore: session } })
    expect(wrapper.get('[role="dialog"]').text()).toContain('rm generated.txt')
    expect(wrapper.text()).toContain('/repo')
    expect(wrapper.text()).toContain('删除文件')

    const buttons = wrapper.findAll('button')
    await buttons[2].trigger('click')
    await buttons[1].trigger('click')
    await buttons[0].trigger('click')
    expect(actions.resolve).toHaveBeenNthCalledWith(1, true, session)
    expect(actions.resolve).toHaveBeenNthCalledWith(2, false, session)
    expect(actions.cancel).toHaveBeenCalledWith(session)
  })

  it('审批过期时刷新快照并明确提示未生效', async () => {
    const store = useApprovalStore()
    const session = useSessionStore()
    session.sessionId = 's1'
    store.pending = pending
    const client = {
      resolveApproval: vi.fn().mockRejectedValue(new ApiError('审批已过期', { status: 409 })),
      getSession: vi.fn().mockResolvedValue({ session_id: 's1', status: 'failed', termination_reason: 'approval_denied', modified_files: [], pending_approvals: [] }),
    }
    expect(await store.resolve(true, session, client)).toBe(false)
    expect(store.error).toContain('审批未生效')
    expect(store.error).toContain('审批已过期')
    expect(store.pending).toBeNull()
    expect(session.status).toBe('failed')
  })
})

describe('终态总结', () => {
  it.each([
    ['completed', '任务已完成'], ['failed', '任务执行失败'], ['cancelled', '任务已取消'],
  ])('%s 使用独立且准确的终态标题', (status, title) => {
    const store = { status, terminationReason: `${status}_reason`, modifiedFiles: status === 'completed' ? ['src/a.js'] : [] }
    const wrapper = mount(TerminalSummary, { props: { store } })
    expect(wrapper.text()).toContain(title)
    expect(wrapper.attributes('data-status')).toBe(status)
    if (status !== 'completed') expect(wrapper.text()).not.toContain('任务已完成')
  })
})
