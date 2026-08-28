import { defineStore } from 'pinia'
import { apiClient } from '../api/client'

const ACTIVE = new Set(['queued', 'running', 'waiting_approval'])
const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

export const useRunStore = defineStore('runs', {
  state: () => ({ runId: '', status: 'idle', finalAnswer: '', terminationReason: '', iteration: 0, changes: [], loading: false, error: '', pendingTask: '', startedAt: null }),
  getters: { isActive: (state) => ACTIVE.has(state.status), isTerminal: (state) => TERMINAL.has(state.status) },
  actions: {
    reset() { this.runId = ''; this.status = 'idle'; this.finalAnswer = ''; this.terminationReason = ''; this.iteration = 0; this.changes = []; this.error = ''; this.pendingTask = ''; this.startedAt = null },
    apply(snapshot) { if (!snapshot || (this.runId && snapshot.id && snapshot.id !== this.runId)) return false; this.runId = snapshot.id || this.runId; this.status = snapshot.status || this.status; this.finalAnswer = snapshot.final_answer ?? this.finalAnswer; this.terminationReason = snapshot.termination_reason || ''; this.iteration = snapshot.iteration || 0; if (!this.startedAt && snapshot.created_at) this.startedAt = Date.parse(snapshot.created_at); return true },
    async submit(conversationId, task, client = apiClient) {
      const value = task.trim()
      if (this.isActive || this.loading || !value) return null
      this.runId = ''; this.finalAnswer = ''; this.terminationReason = ''; this.iteration = 0; this.changes = []
      this.loading = true; this.error = ''; this.pendingTask = value; this.startedAt = Date.now(); this.status = 'queued'
      try { const run = await client.runTask(conversationId, value); this.apply(run); return run }
      catch (error) { this.error = error.message; this.pendingTask = ''; this.startedAt = null; this.status = 'idle'; return null }
      finally { this.loading = false }
    },
    async refresh(client = apiClient) { if (!this.runId) return; try { this.apply(await client.getRun(this.runId)) } catch (error) { this.error = error.message } },
    async loadChanges(runId = this.runId, client = apiClient) { if (!runId) return []; try { this.changes = await client.getChanges(runId); return this.changes } catch (error) { this.error = error.message; return [] } },
    async cancel(client = apiClient) { if (!this.runId) return false; try { this.apply(await client.cancelRun(this.runId)); return true } catch (error) { this.error = error.message; return false } },
    applyEvent(event) { if (event?.run_id !== this.runId) return false; if (event.event_type === 'state.changed') this.status = event.payload.current; if (event.event_type === 'task.completed') this.status = 'completed'; if (event.event_type === 'task.failed') this.status = 'failed'; if (event.event_type === 'task.cancelled') this.status = 'cancelled'; return true },
  },
})
