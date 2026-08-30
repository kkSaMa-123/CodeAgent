import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCapabilityStore } from '../stores/capabilities'

beforeEach(() => setActivePinia(createPinia()))

it('加载对话能力并在启用 Skill 时自动补齐必需工具', async () => {
  const store = useCapabilityStore()
  const skill = { id: 's1', name: 'C++', required_tools: ['read_file', 'run_command'] }
  const client = {
    getToolCatalog: vi.fn().mockResolvedValue([{ name: 'read_file' }, { name: 'run_command' }]),
    listSkills: vi.fn().mockResolvedValue([skill]),
    getCapabilities: vi.fn().mockResolvedValue({ enabled_tools: ['read_file'], skills: [] }),
    updateCapabilities: vi.fn().mockImplementation((_id, tools, skills) => Promise.resolve({ enabled_tools: tools, skills: skills.map((id) => ({ id })) })),
  }
  await store.load('c1', client)
  await store.toggleSkill(skill, true, client)
  expect(store.enabledTools).toEqual(['read_file', 'run_command'])
  expect(store.enabledSkills).toEqual(['s1'])
})

it('阻止关闭已启用 Skill 的必需工具', async () => {
  const store = useCapabilityStore()
  store.skills = [{ id: 's1', name: '审查', required_tools: ['read_file'] }]
  store.enabledSkills = ['s1']; store.enabledTools = ['read_file']
  expect(await store.toggleTool('read_file', false, {})).toBe(false)
  expect(store.error).toContain('请先关闭')
})

it('后端拒绝保存时恢复原有工具选择', async () => {
  const store = useCapabilityStore()
  store.conversationId = 'c1'; store.enabledTools = ['read_file']
  const client = { updateCapabilities: vi.fn().mockRejectedValue(new Error('运行期间不能修改')) }
  expect(await store.toggleTool('write_file', true, client)).toBe(false)
  expect(store.enabledTools).toEqual(['read_file'])
  expect(store.error).toContain('运行期间')
})
