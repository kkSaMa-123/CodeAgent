import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ApprovalCard from '../components/ApprovalCard.vue'
import AgentActivityCard from '../components/AgentActivityCard.vue'
import AppHeader from '../components/AppHeader.vue'
import ChatPanel from '../components/ChatPanel.vue'
import EditorPanel from '../components/EditorPanel.vue'
import MarkdownContent from '../components/MarkdownContent.vue'
import ProjectSidebar from '../components/ProjectSidebar.vue'
import ToolActivityLine from '../components/ToolActivityLine.vue'

describe('Codex 风格项目与对话界面', () => {
  it('左侧展示项目、多个对话、固定目录及安全移除文案', async () => {
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(false))
    const wrapper = mount(ProjectSidebar, { props: {
      projects: { drawerOpen: true, currentId: 'p1', current: { id: 'p1', name: 'CodeAgent' }, items: [{ id: 'p1', name: 'CodeAgent', workspace: '/repo', available: true }], add: vi.fn(), rename: vi.fn(), remove: vi.fn(), load: vi.fn() },
      conversations: { currentId: 'c1', items: [{ id: 'c1', title: '对话一' }, { id: 'c2', title: '对话二' }], create: vi.fn(), rename: vi.fn(), remove: vi.fn() },
      workspace: { entries: [], visibleEntries: [], expanded: [], loadTree: vi.fn(), toggleDirectory: vi.fn(), loading: false, error: '' },
    } })
    expect(wrapper.text()).toContain('CodeAgent'); expect(wrapper.text()).toContain('对话一'); expect(wrapper.text()).toContain('/repo')
    await wrapper.find('[title="从 CodeAgent 移除"]').trigger('click')
    expect(confirm.mock.calls[0][0]).toContain('不会删除本地文件')
    await wrapper.find('[aria-label="收起项目栏"]').trigger('click')
    expect(wrapper.find('[aria-label="展开项目栏"]').text()).toBe('☰')
  })

  it('左侧根据相对路径正确展示文件名、层级和大小', async () => {
    const toggleDirectory = vi.fn()
    const wrapper = mount(ProjectSidebar, { props: {
      projects: { drawerOpen: true, currentId: 'p1', current: { id: 'p1', name: 'CodeAgent' }, items: [{ id: 'p1', name: 'CodeAgent', workspace: '/repo', available: true }], add: vi.fn(), rename: vi.fn(), remove: vi.fn(), load: vi.fn() },
      conversations: { currentId: '', items: [], create: vi.fn(), rename: vi.fn(), remove: vi.fn() },
      workspace: {
        entries: [{ path: 'src', type: 'directory' }, { path: 'src/App.vue', type: 'file', size: 2048 }, { path: 'README.md', type: 'file', size: 512 }],
        visibleEntries: [{ path: 'src', type: 'directory' }, { path: 'src/App.vue', type: 'file', size: 2048 }, { path: 'README.md', type: 'file', size: 512 }],
        expanded: ['src'], currentFile: 'src/App.vue', loadTree: vi.fn(), toggleDirectory, loading: false, error: '',
      },
    } })

    expect(wrapper.text()).toContain('项目文件 · CodeAgent')
    expect(wrapper.text()).toContain('App.vue')
    expect(wrapper.text()).toContain('2.0 KB')
    expect(wrapper.text()).toContain('README.md')
    expect(wrapper.find('[title="src/App.vue"]').classes()).toContain('selected')
    expect(wrapper.find('[title="src/App.vue"]').attributes('style')).toContain('23px')
    await wrapper.find('[title="src"]').trigger('click')
    expect(toggleDirectory).toHaveBeenCalledWith('src')
  })

  it('每轮显示独立消息和修改文件', () => {
    const wrapper = mount(ChatPanel, { props: {
      conversations: { current: { title: '修复任务' }, currentId: 'c1', runs: [{ id: 'r1', status: 'completed' }], messages: [{ run_id: 'r1', role: 'user', content: '修复它' }, { run_id: 'r1', role: 'assistant', content: '已修复' }], changesByRun: { r1: [{ id: 'f1', path: 'app.py', change_type: 'modified', additions: 2, deletions: 1 }] }, refresh: vi.fn(), error: '' },
      run: { status: 'completed', isActive: false, error: '', cancel: vi.fn() }, eventStore: { runId: 'r1', groupedToolTraces: [{ name: 'read_file', status: 'success', count: 3, successCount: 3, errorCount: 0, durationSeconds: 0.3, traces: [] }], connectionStatus: 'ended', error: '' },
      approval: { pending: null, error: '', loading: false },
    } })
    expect(wrapper.text()).toContain('修复它'); expect(wrapper.text()).toContain('读取了 3 个文件'); expect(wrapper.text()).toContain('已修复'); expect(wrapper.text()).toContain('app.py'); expect(wrapper.text()).toContain('+2 -1')
    expect(wrapper.find('.run-turn').element.lastElementChild.classList).toContain('final-answer')
  })

  it('运行中立即显示用户任务、当前工具和中文超时原因', () => {
    const active = mount(ChatPanel, { props: {
      conversations: { current: { title: '贪吃蛇' }, currentId: 'c1', runs: [{ id: 'r-live', status: 'running' }], messages: [], changesByRun: {}, error: '' },
      run: { runId: 'r-live', pendingTask: '实现贪吃蛇', status: 'running', isActive: true, startedAt: Date.now(), error: '', cancel: vi.fn() },
      eventStore: { runId: 'r-live', reasoningText: '先检查项目结构，再创建游戏逻辑。', groupedToolTraces: [{ name: 'write_file', status: 'running', count: 1, successCount: 0, errorCount: 0, traces: [{ id: 'tool-1', status: 'running', events: [{ event_type: 'tool.started', payload: { path: 'src/game.cpp' } }] }] }], activity: { phase: 'tool', label: '正在写入文件…', detail: 'src/game.cpp' }, error: '' },
      approval: { pending: null, error: '', loading: false },
    } })
    expect(active.text()).toContain('实现贪吃蛇')
    expect(active.text()).toContain('正在写入文件')
    expect(active.text()).toContain('Agent 思考过程')
    expect(active.text()).toContain('先检查项目结构')

    const failed = mount(ChatPanel, { props: {
      conversations: { current: { title: '超时任务' }, currentId: 'c1', runs: [{ id: 'r-timeout', status: 'failed', termination_reason: 'task_timeout' }], messages: [], changesByRun: {}, error: '' },
      run: { status: 'failed', isActive: false, error: '', cancel: vi.fn() },
      eventStore: { runId: '', groupedToolTraces: [], error: '' },
      approval: { pending: null, error: '', loading: false },
    } })
    expect(failed.text()).toContain('任务超过最大运行时长')
    expect(failed.text()).not.toContain('task_timeout')
  })

  it('在当前对话标题右侧打开工具和 Skill 配置', async () => {
    const wrapper = mount(ChatPanel, { props: {
      conversations: { current: { title: '当前修复对话' }, currentId: 'c1', runs: [], messages: [], changesByRun: {}, refresh: vi.fn(), error: '' },
      run: { status: 'idle', isActive: false, error: '', cancel: vi.fn() },
      eventStore: { runId: '', groupedToolTraces: [], error: '' },
      approval: { pending: null, error: '', loading: false },
      rightPanel: 'tools',
    } })
    expect(wrapper.find('.panel-heading h2').text()).toBe('当前修复对话')
    const buttons = wrapper.findAll('.conversation-capabilities button')
    expect(buttons).toHaveLength(2)
    expect(buttons[0].classes()).toContain('active')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('show-capabilities')[0]).toEqual(['skills'])
  })

  it('命令确认作为对话内卡片展示，并支持允许、拒绝和停止', async () => {
    const store = { pending: { command: 'npm install', workspace: '/repo', reason: '命令会修改依赖。' }, error: '', loading: false, resolve: vi.fn(), cancel: vi.fn() }
    const runStore = { cancel: vi.fn() }
    const wrapper = mount(ApprovalCard, { props: { store, runStore } })

    expect(wrapper.find('.inline-approval').exists()).toBe(true)
    expect(wrapper.find('.modal-backdrop').exists()).toBe(false)
    expect(wrapper.text()).toContain('npm install')
    expect(wrapper.text()).toContain('/repo')
    await wrapper.findAll('.inline-approval-actions button')[0].trigger('click')
    await wrapper.findAll('.inline-approval-actions button')[1].trigger('click')
    await wrapper.findAll('.inline-approval-actions button')[2].trigger('click')
    expect(store.resolve).toHaveBeenNthCalledWith(1, false, runStore)
    expect(store.cancel).toHaveBeenCalledWith(runStore)
    expect(store.resolve).toHaveBeenNthCalledWith(2, true, runStore)
  })

  it('相同命令压缩为中文单行，并可展开失败详情但不展示耗时', async () => {
    const wrapper = mount(ToolActivityLine, { props: { group: {
      name: 'run_command', status: 'error', count: 2, successCount: 1, errorCount: 1, durationSeconds: 0.42,
      traces: [{ id: 'call-1', status: 'error', summary: '命令以退出码 1 结束', command: 'g++ main.cpp', details: { command: 'g++ main.cpp', stderr: 'main.cpp: error' }, durationSeconds: 0.12 }],
    } } })
    expect(wrapper.text()).toContain('运行了 2 条命令')
    expect(wrapper.text()).toContain('1 次失败')
    expect(wrapper.text()).not.toContain('0.42 秒')
    await wrapper.find('.tool-activity-summary').trigger('click')
    expect(wrapper.text()).toContain('g++ main.cpp')
    expect(wrapper.text()).toContain('main.cpp: error')
    expect(wrapper.text()).not.toContain('0.12 秒')
  })

  it('运行期间在对话内展示当前阶段和停止入口', async () => {
    const cancel = vi.fn()
    const wrapper = mount(AgentActivityCard, { props: {
      run: { isActive: true, loading: false, runId: 'r1', status: 'running', startedAt: Date.now(), cancel },
      eventStore: { activity: { phase: 'tool', label: '正在执行工具：run_command', detail: 'npm test' } },
      approval: { pending: null },
    } })
    expect(wrapper.text()).toContain('正在执行工具：run_command')
    expect(wrapper.text()).toContain('npm test')
    expect(wrapper.findAll('.thinking-dots i')).toHaveLength(3)
    await wrapper.find('.activity-stop').trigger('click')
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('Agent 回复安全渲染 Markdown 标题、强调和代码块', () => {
    const wrapper = mount(MarkdownContent, { props: { content: '# 结果\n\n**完成**\n\n```js\nconst ok = true\n```\n\n<script>alert(1)</script>' } })
    expect(wrapper.find('h1').text()).toBe('结果')
    expect(wrapper.find('strong').text()).toBe('完成')
    expect(wrapper.find('pre code').text()).toContain('const ok = true')
    expect(wrapper.find('pre code .hljs-keyword').text()).toBe('const')
    expect(wrapper.find('script').exists()).toBe(false)
  })

  it('文件代码按扩展名高亮，行号与可复制源码分离', () => {
    const wrapper = mount(EditorPanel, { props: {
      workspace: { currentFile: 'app.js', fileContent: { content: 'const answer = 42\nconsole.log(answer)' }, fileLoading: false, fileError: '' },
      diffStore: { diff: '', preview: '', previewKind: 'text', lines: [], loading: false, error: '' },
      selectedChange: null,
    } })
    expect(wrapper.find('.code-source .hljs-keyword').text()).toBe('const')
    expect(wrapper.find('.line-numbers').attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('.line-numbers').text()).toContain('1')
    expect(wrapper.find('.code-source').text()).toBe('const answer = 42\nconsole.log(answer)')
    expect(wrapper.find('.code-source').text()).not.toContain('1const')
  })

  it('顶栏在模型状态旁提供有语义的主题切换按钮', async () => {
    const wrapper = mount(AppHeader, { props: {
      store: { loading: false, ready: true, summary: { provider: 'deepseek', model: 'test' }, load: vi.fn() },
      theme: 'dark',
    } })
    const button = wrapper.get('[aria-label="切换到亮色主题"]')
    expect(button.text()).toContain('☀')
    await button.trigger('click')
    expect(wrapper.emitted('toggle-theme')).toHaveLength(1)
  })

  it('右侧可切换本轮 Diff、历史版本和当前文件', async () => {
    const wrapper = mount(EditorPanel, { props: {
      workspace: { currentFile: 'app.py', fileContent: { content: 'current' }, fileLoading: false, fileError: '' },
      diffStore: { diff: '-old\n+new', preview: 'new', previewKind: 'text', lines: [{ id: 1, text: '+new', kind: 'addition' }], loading: false, error: '' },
      selectedChange: { path: 'app.py', change_type: 'modified', additions: 1, deletions: 1 },
    } })
    expect(wrapper.text()).toContain('本轮 Diff'); await wrapper.findAll('.view-switch button')[1].trigger('click'); expect(wrapper.text()).toContain('new')
    await wrapper.findAll('.view-switch button')[2].trigger('click'); expect(wrapper.text()).toContain('current')
  })

  it('Diff 明确提示折叠的未修改内容并可进入完整文件', async () => {
    const wrapper = mount(EditorPanel, { props: {
      workspace: { currentFile: 'app.cpp', fileContent: { content: 'current' }, fileLoading: false, fileError: '' },
      diffStore: {
        diff: '@@ -1,3 +1,4 @@\n old\n+new\n@@ -10,2 +11,3 @@\n tail\n+end',
        preview: '完整的本轮文件内容', previewKind: 'text', loading: false, error: '',
        lines: [
          { id: 0, text: '@@ -1,3 +1,4 @@', kind: 'hunk' },
          { id: 1, text: ' old', kind: 'context' },
          { id: 2, text: '+new', kind: 'addition' },
          { id: 3, text: '@@ -10,2 +11,3 @@', kind: 'hunk' },
          { id: 4, text: ' tail', kind: 'context' },
          { id: 5, text: '+end', kind: 'addition' },
        ],
      },
      selectedChange: { path: 'app.cpp', change_type: 'modified', additions: 2, deletions: 0 },
    } })
    wrapper.vm.select('diff'); await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('已折叠 6 行未修改内容')
    expect(wrapper.text()).toContain('Diff 只显示修改位置附近的内容')
    await wrapper.find('.diff-context-notice button').trigger('click')
    expect(wrapper.text()).toContain('完整的本轮文件内容')
  })
})
