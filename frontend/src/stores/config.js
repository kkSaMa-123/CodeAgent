import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useConfigStore = defineStore('config', {
  state: () => ({ loading: false, ready: false, summary: null, errors: [], error: '' }),
  actions: {
    async load(client = apiClient) {
      this.loading = true
      this.error = ''
      try {
        const result = await client.getConfigStatus()
        this.ready = result.ready
        this.summary = result.summary
        this.errors = result.errors || []
      } catch (error) {
        this.ready = false
        this.error = error.message
      } finally {
        this.loading = false
      }
    },
  },
})
