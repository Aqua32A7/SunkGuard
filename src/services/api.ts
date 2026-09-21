import { events, experiment, metrics, policy, prediction, reservations, resources, workflows } from '../data/mockData'
import type { PolicyMode, Workflow } from '../domain/types'

let _isBackendConnected: boolean | null = null

export interface ControllerApi {
  getOverview: () => Promise<{
    events: typeof events
    experiment: typeof experiment
    metrics: typeof metrics
    policy: typeof policy
    prediction: typeof prediction
    reservations: typeof reservations
    resources: typeof resources
    workflows: typeof workflows
  }>
  startWorkflow: (workflow: Workflow) => Promise<{ workflowId: string; accepted: boolean }>
  requestStep: (workflowId: string, step: string) => Promise<{ workflowId: string; step: string; decision: 'queued' | 'granted' }>
  completeStep: (workflowId: string, step: string, usage: { tokens: number }) => Promise<{ workflowId: string; step: string; recorded: boolean }>
  getResourceState: () => Promise<typeof resources>
  getReservationState: () => Promise<typeof reservations>
  getMetrics: () => Promise<typeof metrics>
  getPolicyState: () => Promise<typeof policy>
  setPolicyMode: (mode: PolicyMode) => Promise<{ mode: PolicyMode; applied: boolean }>
  demoStep: () => Promise<{ phase: number; notice: string }>
  demoReset: (seed?: number) => Promise<{ reset: boolean; seed?: number }>
  demoMismatch: () => Promise<{ notice: string; success: boolean }>
  isBackendConnected: () => boolean | null
}

export const sunkGuardApi: ControllerApi = {
  isBackendConnected() {
    return _isBackendConnected
  },

  async getOverview() {
    try {
      const res = await fetch('/api/overview')
      if (res.ok) {
        const data = await res.json()
        _isBackendConnected = true
        return data
      }
      throw new Error(`HTTP ${res.status}`)
    } catch {
      _isBackendConnected = false
      return { events, experiment, metrics, policy, prediction, reservations, resources, workflows }
    }
  },

  async startWorkflow(workflow) {
    try {
      const res = await fetch('/api/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: workflow.id,
          name: workflow.name,
          agentType: workflow.agentType,
          resourceNeed: workflow.resourceNeed,
        }),
      })
      if (res.ok) return await res.json()
    } catch {}
    return { workflowId: workflow.id, accepted: true }
  },

  async requestStep(workflowId, step) {
    try {
      const res = await fetch(`/api/workflows/${workflowId}/steps/request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step }),
      })
      if (res.ok) return await res.json()
    } catch {}
    return { workflowId, step, decision: 'queued' }
  },

  async completeStep(workflowId, step, usage) {
    try {
      const res = await fetch(`/api/workflows/${workflowId}/steps/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step, usage }),
      })
      if (res.ok) return await res.json()
    } catch {}
    return { workflowId, step, recorded: true }
  },

  async getResourceState() {
    try {
      const res = await fetch('/api/resources')
      if (res.ok) return await res.json()
    } catch {}
    return resources
  },

  async getReservationState() {
    try {
      const res = await fetch('/api/reservations')
      if (res.ok) return await res.json()
    } catch {}
    return reservations
  },

  async getMetrics() {
    try {
      const res = await fetch('/api/metrics')
      if (res.ok) return await res.json()
    } catch {}
    return metrics
  },

  async getPolicyState() {
    try {
      const res = await fetch('/api/policy')
      if (res.ok) return await res.json()
    } catch {}
    return policy
  },

  async setPolicyMode(mode) {
    try {
      const res = await fetch('/api/policy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      })
      if (res.ok) return await res.json()
    } catch {}
    return { mode, applied: true }
  },

  async demoStep() {
    try {
      const res = await fetch('/api/demo/step', { method: 'POST' })
      if (res.ok) return await res.json()
    } catch {}
    return { phase: 1, notice: 'Simulated step' }
  },

  async demoReset(seed) {
    try {
      const res = await fetch('/api/demo/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seed }),
      })
      if (res.ok) return await res.json()
    } catch {}
    return { reset: true, seed }
  },

  async demoMismatch() {
    try {
      const res = await fetch('/api/demo/mismatch', { method: 'POST' })
      if (res.ok) return await res.json()
    } catch {}
    return {
      notice: 'Mismatch injected · predicted Gemini → actual Python tool → stale reservation released → re-planning → new reservation.',
      success: true,
    }
  },
}