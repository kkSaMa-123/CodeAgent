import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

function parentDirectories(path) {
  const parts = path.split('/')
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'))
}

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    inputPath: '', workspace: '', entries: [], expanded: ['.'], currentFile: '', fileContent: null,
    loading: false, error: '', fileLoading: false, fileError: '',
  }),
  getters: {
    visibleEntries(state) {
      return state.entries.filter((entry) => parentDirectories(entry.path).every((path) => state.expanded.includes(path)))
    },
  },
  actions: {
    async validate(client = apiClient) {
      if (!this.inputPath.trim()) {
        this.error = '请输入工作区绝对路径。'
        return null
      }
      this.loading = true
      this.error = ''
      try {
        const result = await client.validateWorkspace(this.inputPath.trim())
        this.workspace = result.path
        return result
      } catch (error) {
        this.error = error.message
        return null
      } finally {
        this.loading = false
      }
    },
    async loadTree(sessionId, client = apiClient) {
      this.loading = true
      this.error = ''
      try {
        const result = await client.getFileTree(sessionId)
        this.entries = result.entries || []
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },
    toggleDirectory(path) {
      this.expanded = this.expanded.includes(path)
        ? this.expanded.filter((item) => item !== path)
        : [...this.expanded, path]
    },
    async openFile(sessionId, path, client = apiClient) {
      this.currentFile = path
      this.fileLoading = true
      this.fileError = ''
      try {
        this.fileContent = await client.getFileContent(sessionId, path)
      } catch (error) {
        this.fileContent = null
        this.fileError = error.message
      } finally {
        this.fileLoading = false
      }
    },
    reloadFile(sessionId, client = apiClient) {
      if (this.currentFile) return this.openFile(sessionId, this.currentFile, client)
    },
  },
})
