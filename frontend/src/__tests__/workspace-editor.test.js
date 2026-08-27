import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EditorPanel from '../components/EditorPanel.vue'
import WorkspacePanel from '../components/WorkspacePanel.vue'
import { ApiError } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

beforeEach(() => setActivePinia(createPinia()))

describe('工作区与文件树', () => {
  it('校验有效目录并加载、展开文件树', async () => {
    const store = useWorkspaceStore()
    store.inputPath = '/repo'
    const client = {
      validateWorkspace: vi.fn().mockResolvedValue({ valid: true, path: '/repo' }),
      getFileTree: vi.fn().mockResolvedValue({ entries: [
        { path: 'src', type: 'directory' }, { path: 'src/main.js', type: 'file' }, { path: 'README.md', type: 'file' },
      ] }),
    }
    expect(await store.validate(client)).toEqual({ valid: true, path: '/repo' })
    await store.loadTree('s1', client)
    expect(store.visibleEntries.map((item) => item.path)).toEqual(['src', 'README.md'])
    store.toggleDirectory('src')
    expect(store.visibleEntries.map((item) => item.path)).toContain('src/main.js')
  })

  it('显示空路径、无效目录和加载错误', async () => {
    const store = useWorkspaceStore()
    expect(await store.validate()).toBeNull()
    expect(store.error).toContain('绝对路径')
    store.inputPath = '/missing'
    await store.validate({ validateWorkspace: vi.fn().mockRejectedValue(new ApiError('工作区不存在')) })
    expect(store.error).toBe('工作区不存在')
    await store.loadTree('s1', { getFileTree: vi.fn().mockRejectedValue(new ApiError('文件树加载失败')) })
    expect(store.error).toBe('文件树加载失败')
  })

  it('组件可点击展开目录和选择文件', async () => {
    const store = useWorkspaceStore()
    store.entries = [{ path: 'src', type: 'directory' }, { path: 'src/main.js', type: 'file' }]
    const wrapper = mount(WorkspacePanel, { props: { store, sessionId: 's1' } })
    await wrapper.get('.tree-item').trigger('click')
    expect(wrapper.findAll('.tree-item')).toHaveLength(2)
    await wrapper.findAll('.tree-item')[1].trigger('click')
    expect(wrapper.emitted('open-file')[0]).toEqual(['src/main.js'])
  })
})

describe('文件预览', () => {
  it('显示文本和行号，并支持文件切换与重新加载', async () => {
    const store = useWorkspaceStore()
    const client = { getFileContent: vi.fn()
      .mockResolvedValueOnce({ path: 'a.js', content: 'const a = 1\nexport { a }', total_lines: 2 })
      .mockResolvedValueOnce({ path: 'b.js', content: 'second', total_lines: 1 })
      .mockResolvedValueOnce({ path: 'b.js', content: 'updated', total_lines: 1 }) }
    await store.openFile('s1', 'a.js', client)
    const wrapper = mount(EditorPanel, { props: { store } })
    expect(wrapper.findAll('.line-number').map((item) => item.text())).toEqual(['1', '2'])
    await store.openFile('s1', 'b.js', client)
    expect(wrapper.text()).toContain('second')
    await store.reloadFile('s1', client)
    expect(wrapper.text()).toContain('updated')
  })

  it('清楚显示二进制文件错误', async () => {
    const store = useWorkspaceStore()
    await store.openFile('s1', 'logo.png', { getFileContent: vi.fn().mockRejectedValue(new ApiError('二进制文件不支持预览')) })
    const wrapper = mount(EditorPanel, { props: { store } })
    expect(wrapper.get('[role="alert"]').text()).toContain('二进制文件不支持预览')
  })
})
