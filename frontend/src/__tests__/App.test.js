import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App.vue'

afterEach(() => vi.unstubAllGlobals())

describe('三栏工作台', () => {
  it('同时呈现工作区、文件预览和任务面板，并提供窄屏标签', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })

    expect(wrapper.find('.workbench').exists()).toBe(true)
    expect(wrapper.findAll('.panel')).toHaveLength(3)
    expect(wrapper.text()).toContain('工作区')
    expect(wrapper.text()).toContain('文件预览')
    expect(wrapper.text()).toContain('任务对话')
    expect(wrapper.findAll('.mobile-tabs button').map((item) => item.text())).toEqual(['文件', '预览', 'Agent'])

    wrapper.unmount()
  })
})
