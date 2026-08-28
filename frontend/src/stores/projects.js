import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useProjectStore = defineStore('projects', {
  state: () => ({ items: [], currentId: '', loading: false, error: '', drawerOpen: true }),
  getters: { current: (state) => state.items.find((item) => item.id === state.currentId) || null },
  actions: {
    async load(client = apiClient) {
      this.loading = true; this.error = ''
      try { this.items = await client.listProjects(); return this.items }
      catch (error) { this.error = error.message; return [] }
      finally { this.loading = false }
    },
    select(id) { this.currentId = id },
    async add(workspace, name = '', client = apiClient) {
      this.error = ''
      try {
        const project = await client.createProject(workspace, name)
        this.items = [project, ...this.items.filter((item) => item.id !== project.id)]
        this.currentId = project.id
        return project
      } catch (error) { this.error = error.message; return null }
    },
    async rename(id, name, client = apiClient) {
      try { const updated = await client.renameProject(id, name); this.items = this.items.map((item) => item.id === id ? updated : item); return true }
      catch (error) { this.error = error.message; return false }
    },
    async remove(id, client = apiClient) {
      try { await client.removeProject(id); this.items = this.items.filter((item) => item.id !== id); if (this.currentId === id) this.currentId = ''; return true }
      catch (error) { this.error = error.message; return false }
    },
  },
})
