import { defineStore } from 'pinia'
import { apiClient } from '../api/client'
import { groupToolEvents } from './events'

export const useConversationStore = defineStore('conversations', {
  state: () => ({ projectId: '', items: [], currentId: '', messages: [], runs: [], changesByRun: {}, eventsByRun: {}, toolGroupsByRun: {}, loading: false, error: '' }),
  getters: { current: (state) => state.items.find((item) => item.id === state.currentId) || null },
  actions: {
    reset(projectId = '') { this.projectId = projectId; this.items = []; this.currentId = ''; this.messages = []; this.runs = []; this.changesByRun = {}; this.eventsByRun = {}; this.toolGroupsByRun = {}; this.error = '' },
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
        const results = await Promise.all(this.runs.map(async (run) => {
          const [changes, events] = await Promise.all([client.getChanges(run.id), client.getRunEvents(run.id)])
          return [run.id, changes, events]
        }))
        this.changesByRun = Object.fromEntries(results.map(([runId, changes]) => [runId, changes]))
        this.eventsByRun = Object.fromEntries(results.map(([runId, _changes, events]) => [runId, events]))
        this.toolGroupsByRun = Object.fromEntries(results.map(([runId, _changes, events]) => [runId, groupToolEvents(events)]))
        return true
      }
      catch (error) { this.error = error.message; return false }
      finally { this.loading = false }
    },
    async refresh(client = apiClient) { if (this.currentId) await this.select(this.currentId, client) },
    async rename(id, title, client = apiClient) { try { const item = await client.renameConversation(id, title); this.items = this.items.map((value) => value.id === id ? item : value); return true } catch (error) { this.error = error.message; return false } },
    async remove(id, client = apiClient) { try { await client.deleteConversation(id); this.items = this.items.filter((item) => item.id !== id); if (this.currentId === id) { this.currentId = ''; this.messages = []; this.runs = []; this.changesByRun = {}; this.eventsByRun = {}; this.toolGroupsByRun = {} } return true } catch (error) { this.error = error.message; return false } },
  },
})
