import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useDiffStore = defineStore('diff', {
  state: () => ({ diff: '', path: '.', loading: false, error: '', loaded: false }),
  getters: {
    lines: (state) => state.diff ? state.diff.split('\n').map((text, index) => ({
      id: index, text,
      kind: text.startsWith('+++') || text.startsWith('---') ? 'meta'
        : text.startsWith('+') ? 'addition' : text.startsWith('-') ? 'deletion'
          : text.startsWith('@@') ? 'hunk' : 'context',
    })) : [],
  },
  actions: {
    async load(sessionId, client = apiClient) {
      if (!sessionId) return false
      this.loading = true
      this.error = ''
      try {
        const result = await client.getDiff(sessionId, this.path)
        this.diff = result.diff || ''
        this.loaded = true
        return true
      } catch (error) {
        this.error = error.message
        return false
      } finally { this.loading = false }
    },
    reset() { this.diff = ''; this.error = ''; this.loaded = false },
  },
})
