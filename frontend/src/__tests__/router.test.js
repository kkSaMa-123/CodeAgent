import { expect, it } from 'vitest'
import { router } from '../router'

it('项目和对话 URL 可恢复且非法路径回退', async () => {
  await router.push('/projects/p1/conversations/c1'); await router.isReady()
  expect(router.currentRoute.value.params).toMatchObject({ projectId: 'p1', conversationId: 'c1' })
  await router.push('/unknown/path'); await new Promise((resolve) => setTimeout(resolve, 0))
  expect(router.currentRoute.value.path).toBe('/projects')
})
