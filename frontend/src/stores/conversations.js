import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useConversationStore = defineStore('conversations', {
  state: () => ({ projectId: '', items: [], currentId: '', messages: [], runs: [], changesByRun: {}, loading: false, error: '' }),
  getters: { current: (state) => state.items.find((item) => item.id === state.currentId) || null },
  actions: {
    reset(projectId = '') { this.projectId = projectId; this.items = []; this.currentId = ''; this.messages = []; this.runs = []; this.changesByRun = {}; this.error = '' },
    async load(projectId, client = apiClient) {
      if (this.projectId !== projectId) this.reset(projectId)
      this.loading = true; this.error = ''
      try { this.items = await client.listConversations(projectId); return this.items }
      catch (error) { this.error = error.message; return [] }
      finally { this.loading = false }
    },
    async create(client = apiClient) {
      try { const item = await client.createConversation(this.projectId); this.items = [item, ...this.items]; await this.select(item.id, client); return item }
      catch (error) { this.error = error.message; return null }
    },
    async select(id, client = apiClient) {
      this.currentId = id; this.loading = true; this.error = ''
      try {
        [this.messages, this.runs] = await Promise.all([client.getMessages(id), client.getRuns(id)])
        const results = await Promise.all(this.runs.map(async (run) => [run.id, await client.getChanges(run.id)]))
        this.changesByRun = Object.fromEntries(results)
        return true
      }
      catch (error) { this.error = error.message; return false }
      finally { this.loading = false }
    },
    async refresh(client = apiClient) { if (this.currentId) await this.select(this.currentId, client) },
    async rename(id, title, client = apiClient) { try { const item = await client.renameConversation(id, title); this.items = this.items.map((value) => value.id === id ? item : value); return true } catch (error) { this.error = error.message; return false } },
    async remove(id, client = apiClient) { try { await client.deleteConversation(id); this.items = this.items.filter((item) => item.id !== id); if (this.currentId === id) { this.currentId = ''; this.messages = []; this.runs = [] } return true } catch (error) { this.error = error.message; return false } },
  },
})
