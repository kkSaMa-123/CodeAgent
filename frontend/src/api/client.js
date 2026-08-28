export class ApiError extends Error {
  constructor(message, { status = 0, code = 'request_failed' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export class ApiClient {
  constructor(baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000') {
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  async request(path, options = {}) {
    let response
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: {
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...options.headers,
        },
      })
    } catch {
      throw new ApiError('无法连接后端，请确认服务已启动后重试。', { code: 'network_error' })
    }

    const contentType = response.headers.get('content-type') || ''
    const payload = contentType.includes('application/json') ? await response.json() : null
    if (!response.ok) {
      const detail = payload?.detail
      const code = detail?.error || detail?.code
      const friendlyMessages = {
        workspace_not_found: '工作区不存在，请检查路径后重试。',
        workspace_not_directory: '该路径不是目录。',
        path_outside_workspace: '不能访问工作区之外的路径。',
        binary_file: '二进制文件不支持预览。',
        model_not_configured: '模型尚未配置，请检查环境变量。',
      }
      const message = typeof detail === 'string' ? detail : detail?.message || friendlyMessages[code] || `请求失败（${response.status}）`
      throw new ApiError(message, { status: response.status, code })
    }
    return payload
  }

  getConfigStatus() { return this.request('/api/config/status') }
  validateWorkspace(path) {
    return this.request('/api/workspaces/validate', { method: 'POST', body: JSON.stringify({ path }) })
  }
  listProjects() { return this.request('/api/projects') }
  createProject(workspace, name) {
    return this.request('/api/projects', { method: 'POST', body: JSON.stringify({ workspace, name: name || null }) })
  }
  getProject(id) { return this.request(`/api/projects/${id}`) }
  renameProject(id, name) { return this.request(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }) }
  removeProject(id) { return this.request(`/api/projects/${id}`, { method: 'DELETE' }) }
  listConversations(projectId) { return this.request(`/api/projects/${projectId}/conversations`) }
  createConversation(projectId, title = '新对话') {
    return this.request(`/api/projects/${projectId}/conversations`, { method: 'POST', body: JSON.stringify({ title }) })
  }
  renameConversation(id, title) { return this.request(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }) }
  deleteConversation(id) { return this.request(`/api/conversations/${id}`, { method: 'DELETE' }) }
  getMessages(id) { return this.request(`/api/conversations/${id}/messages`) }
  getRuns(id) { return this.request(`/api/conversations/${id}/runs`) }
  runTask(id, task) { return this.request(`/api/conversations/${id}/runs`, { method: 'POST', body: JSON.stringify({ task }) }) }
  getRun(id) { return this.request(`/api/runs/${id}`) }
  getRunEvents(id) { return this.request(`/api/runs/${id}/events/history`) }
  cancelRun(id) { return this.request(`/api/runs/${id}/cancel`, { method: 'POST' }) }
  getFileTree(id, path = '.', depth = 8) {
    const query = new URLSearchParams({ path, depth: String(depth) })
    return this.request(`/api/projects/${id}/files/tree?${query}`)
  }
  getFileContent(id, path) {
    const query = new URLSearchParams({ path })
    return this.request(`/api/projects/${id}/files/content?${query}`)
  }
  getDiff(id, path = '.') {
    const query = new URLSearchParams({ path })
    return this.request(`/api/runs/${id}/diff?${query}`)
  }
  getChanges(id) { return this.request(`/api/runs/${id}/changes`) }
  getChange(id, changeId) { return this.request(`/api/runs/${id}/changes/${changeId}`) }
  getChangePreview(id, changeId) { return this.request(`/api/runs/${id}/changes/${changeId}/preview`) }
  resolveApproval(id, approvalId, approved) {
    return this.request(`/api/runs/${id}/approvals/${approvalId}`, {
      method: 'POST', body: JSON.stringify({ approved }),
    })
  }
  eventUrl(id, lastSequence = 0) {
    const query = new URLSearchParams({ last_event_id: String(lastSequence) })
    return `${this.baseUrl}/api/runs/${id}/events?${query}`
  }
}

export const apiClient = new ApiClient()
