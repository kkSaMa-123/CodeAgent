import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from '../api/client'
import { useConfigStore } from '../stores/config'

beforeEach(() => setActivePinia(createPinia()))

describe('统一 API 客户端与配置状态', () => {
  it('把网络错误转换为可重试的友好错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed')))
    await expect(new ApiClient('http://api.test').getConfigStatus()).rejects.toMatchObject({
      code: 'network_error', message: '无法连接后端，请确认服务已启动后重试。',
    })
    vi.unstubAllGlobals()
  })

  it('只保存非敏感配置摘要', async () => {
    const store = useConfigStore()
    await store.load({ getConfigStatus: vi.fn().mockResolvedValue({
      ready: true,
      summary: { provider: 'deepseek', model: 'deepseek-chat', base_url: 'https://api.deepseek.com', api_key_configured: true },
      errors: [],
    }) })

    expect(store.ready).toBe(true)
    expect(store.summary.api_key_configured).toBe(true)
    expect(JSON.stringify(store.$state)).not.toContain('sk-secret')
  })

  it('失败后允许重试并恢复就绪状态', async () => {
    const store = useConfigStore()
    const client = { getConfigStatus: vi.fn().mockRejectedValueOnce(new ApiError('后端离线')).mockResolvedValueOnce({ ready: true, summary: { provider: 'test', model: 'm' }, errors: [] }) }
    await store.load(client)
    expect(store.error).toBe('后端离线')
    await store.load(client)
    expect(store.error).toBe('')
    expect(store.ready).toBe(true)
  })
})
