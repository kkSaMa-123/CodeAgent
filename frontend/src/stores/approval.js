import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

export const useApprovalStore = defineStore('approval', {
  state: () => ({ pending: null, loading: false, error: '' }),
  actions: {
    syncFromSnapshot(snapshot) {
      this.pending = snapshot?.pending_approvals?.[0] || null
    },
    handleEvent(event) {
      if (event.event_type === 'approval.requested') {
        this.pending = { ...event.payload }
        this.error = ''
      } else if (event.event_type === 'approval.resolved' && this.pending?.approval_id === event.payload.approval_id) {
        this.pending = null
      }
    },
    async resolve(approved, runStore, client = apiClient) {
      if (!this.pending || this.loading) return false
      this.loading = true
      this.error = ''
      const approvalId = this.pending.approval_id
      try {
        await client.resolveApproval(runStore.runId, approvalId, approved)
        this.pending = null
        return true
      } catch (error) {
        this.error = `审批未生效：${error.message}`
        try {
          const snapshot = await client.getRun(runStore.runId)
          runStore.apply(snapshot)
          this.syncFromSnapshot(snapshot)
        } catch (snapshotError) {
          runStore.error = snapshotError.message
        }
        return false
      } finally { this.loading = false }
    },
    async cancel(runStore, client = apiClient) {
      const cancelled = await runStore.cancel(client)
      if (cancelled) this.pending = null
      return cancelled
    },
  },
})
