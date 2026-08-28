import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useDiffStore = defineStore('diff', {
  state: () => ({ runId: '', changeId: '', diff: '', preview: '', previewKind: '', path: '.', loading: false, error: '', loaded: false, view: 'diff' }),
  getters: {
    lines: (state) => state.diff ? state.diff.split('\n').map((text, index) => ({
      id: index, text,
      kind: text.startsWith('+++') || text.startsWith('---') ? 'meta'
        : text.startsWith('+') ? 'addition' : text.startsWith('-') ? 'deletion'
          : text.startsWith('@@') ? 'hunk' : 'context',
    })) : [],
  },
  actions: {
    async load(runId, client = apiClient) {
      if (!runId) return false
      this.runId = runId
      this.loading = true
      this.error = ''
      try {
        const result = await client.getDiff(runId, this.path)
        this.diff = result.diff || ''
        this.loaded = true
        return true
      } catch (error) {
        this.error = error.message
        return false
      } finally { this.loading = false }
    },
    async openChange(runId, changeId, client = apiClient) {
      this.loading = true; this.error = ''; this.runId = runId; this.changeId = changeId
      try { const item = await client.getChange(runId, changeId); this.path = item.path; this.diff = item.diff || ''; this.preview = item.preview || ''; this.previewKind = item.preview_kind; this.loaded = true; return item }
      catch (error) { this.error = error.message; return null }
      finally { this.loading = false }
    },
    reset() { this.runId = ''; this.changeId = ''; this.diff = ''; this.preview = ''; this.error = ''; this.loaded = false },
  },
})
