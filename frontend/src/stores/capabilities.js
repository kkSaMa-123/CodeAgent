import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useCapabilityStore = defineStore('capabilities', {
  state: () => ({ conversationId: '', tools: [], skills: [], enabledTools: [], enabledSkills: [], selectedSkill: null, loading: false, saving: false, error: '' }),
  getters: {
    enabledCount: (state) => state.enabledTools.length,
    isSkillEnabled: (state) => (id) => state.enabledSkills.includes(id),
  },
  actions: {
    async load(conversationId, client = apiClient) {
      this.conversationId = conversationId || ''; this.loading = true; this.error = ''
      try {
        const [tools, skills, config] = await Promise.all([
          client.getToolCatalog(), client.listSkills(), conversationId ? client.getCapabilities(conversationId) : Promise.resolve({ enabled_tools: [], skills: [] }),
        ])
        this.tools = tools; this.skills = skills
        this.enabledTools = config.enabled_tools || []
        this.enabledSkills = (config.skills || []).map((item) => item.id)
        if (this.selectedSkill) this.selectedSkill = skills.find((item) => item.id === this.selectedSkill.id) || null
        return true
      } catch (error) { this.error = error.message; return false }
      finally { this.loading = false }
    },
    async save(client = apiClient) {
      if (!this.conversationId) return false
      this.saving = true; this.error = ''
      try {
        const config = await client.updateCapabilities(this.conversationId, this.enabledTools, this.enabledSkills)
        this.enabledTools = config.enabled_tools; this.enabledSkills = config.skills.map((item) => item.id); return true
      } catch (error) { this.error = error.message; return false }
      finally { this.saving = false }
    },
    async toggleTool(name, enabled, client = apiClient) {
      if (!enabled) {
        const dependent = this.skills.find((skill) => this.enabledSkills.includes(skill.id) && skill.required_tools.includes(name))
        if (dependent) { this.error = `“${dependent.name}”需要该工具，请先关闭这个 Skill。`; return false }
      }
      const previousTools = [...this.enabledTools]
      const previousSkills = [...this.enabledSkills]
      this.enabledTools = enabled ? [...new Set([...this.enabledTools, name])] : this.enabledTools.filter((item) => item !== name)
      const saved = await this.save(client)
      if (!saved) { this.enabledTools = previousTools; this.enabledSkills = previousSkills }
      return saved
    },
    async toggleSkill(skill, enabled, client = apiClient) {
      const previousTools = [...this.enabledTools]
      const previousSkills = [...this.enabledSkills]
      if (enabled) {
        this.enabledTools = [...new Set([...this.enabledTools, ...skill.required_tools])]
        this.enabledSkills = [...new Set([...this.enabledSkills, skill.id])]
      } else this.enabledSkills = this.enabledSkills.filter((id) => id !== skill.id)
      const saved = await this.save(client)
      if (!saved) { this.enabledTools = previousTools; this.enabledSkills = previousSkills }
      return saved
    },
    async add(path, client = apiClient) {
      this.error = ''
      try { const item = await client.addSkill(path); await this.load(this.conversationId, client); await this.selectSkill(item.id, client); return item }
      catch (error) { this.error = error.message; return null }
    },
    async selectSkill(id, client = apiClient) {
      try { this.selectedSkill = await client.getSkill(id); return this.selectedSkill }
      catch (error) { this.error = error.message; return null }
    },
    async refreshSkill(id, client = apiClient) {
      try { const item = await client.refreshSkill(id); await this.load(this.conversationId, client); this.selectedSkill = item; return true }
      catch (error) { this.error = error.message; return false }
    },
    async removeSkill(id, client = apiClient) {
      try { await client.removeSkill(id); this.selectedSkill = null; await this.load(this.conversationId, client); return true }
      catch (error) { this.error = error.message; return false }
    },
  },
})
