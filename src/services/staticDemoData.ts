// Static Demo Data Provider
// Directly loads committed evaluation results from eval/results/*.json
// and recorded live agent execution traces from demo/traces/*.json.

import type { ActivityEvent, Experiment, Metric, Policy, Prediction, Reservation, Resource, Workflow } from '../domain/types'

// Vite eager glob imports for eval results and recorded traces
const evalModules = import.meta.glob<{ default: any }>('../../eval/results/*.json', { eager: true })
const traceModules = import.meta.glob<{ default: any }>('../../demo/traces/*.json', { eager: true })

export interface StaticEvalDataSet {
  name: string
  raw: any
}

export interface StaticTraceRecord {
  filename: string
  trace: any
}

export const staticEvalResults: Record<string, any> = {}
for (const [path, mod] of Object.entries(evalModules)) {
  const filename = path.split('/').pop() ?? path
  staticEvalResults[filename] = mod.default || mod
}

export const staticTraces: Record<string, any> = {}
for (const [path, mod] of Object.entries(traceModules)) {
  const filename = path.split('/').pop() ?? path
  staticTraces[filename] = mod.default || mod
}

// Construct dynamic static demo state derived from gate3_ablation_results.json and traces
const gate3 = staticEvalResults['gate3_ablation_results.json']
const trace1 = staticTraces['trace_01.json']
const trace2 = staticTraces['trace_02.json']
const trace3 = staticTraces['trace_03.json']
const calib = staticTraces['calibration_summary.json']

// Build static experiment model from gate3 results (load 0.50)
export function getStaticExperiment(): Experiment {
  if (!gate3 || !gate3.load_results || !gate3.load_results['0.5']) {
    return {
      name: 'Gate 3 Multi-Load Ablation (Static Frozen)',
      status: 'Seeds 151–250 · Frozen Gate 3',
      points: [
        { label: 'Wasted tokens', baseline: 3.07, sunkguard: 0.51 },
        { label: 'Late failures', baseline: 2.69, sunkguard: 0.94 },
      ],
      ablation: [
        { label: 'Baseline', wastedTokens: 3.07, lateFailures: 2.69, fairness: 0.98, waitTime: 0.11 },
        { label: 'FIFO', wastedTokens: 1.88, lateFailures: 2.21, fairness: 0.97, waitTime: 0.13 },
        { label: 'Aging-Only', wastedTokens: 1.96, lateFailures: 2.29, fairness: 0.98, waitTime: 0.13 },
        { label: 'Progress-Only', wastedTokens: 0.84, lateFailures: 0.99, fairness: 0.97, waitTime: 0.16 },
        { label: 'Admission-Only', wastedTokens: 0.43, lateFailures: 0.72, fairness: 0.97, waitTime: 0.16 },
        { label: 'Pred-Rsv', wastedTokens: 0.66, lateFailures: 0.81, fairness: 0.97, waitTime: 0.19 },
        { label: 'Full SunkGuard', wastedTokens: 0.51, lateFailures: 0.94, fairness: 0.97, waitTime: 0.21 },
      ],
      metrics: [
        { label: 'Wasted-token ratio', value: '0.51%', baseline: '3.07%', direction: 'benefit' },
        { label: 'Late failure rate', value: '0.94%', baseline: '2.69%', direction: 'benefit' },
        { label: 'Completed runs', value: '55.46', baseline: '56.87', direction: 'cost' },
        { label: 'New-work wait', value: '0.21t (0.21s)', baseline: '0.11t (0.11s)', direction: 'cost' },
        { label: 'Jain fairness', value: '0.968', baseline: '0.977', direction: 'cost' },
        { label: 'Predictor hit rate', value: '96.2%', baseline: 'n/a', direction: 'benefit' },
      ],
    }
  }

  const l05 = gate3.load_results['0.5']
  const base = l05['Baseline']
  const full = l05['Full SunkGuard']
  const adm = l05['Admission-Only']
  const prog = l05['Progress-Only']
  const fifo = l05['FIFO']

  return {
    name: 'Gate 3 Multi-Load Ablation (Static Frozen)',
    status: 'Seeds 151–250 · Bit-identical frozen eval',
    points: [
      { label: 'Wasted tokens', baseline: Number((base.wasted_token_ratio.mean * 100).toFixed(2)), sunkguard: Number((full.wasted_token_ratio.mean * 100).toFixed(2)) },
      { label: 'Late failures', baseline: Number((base.late_failure_rate.mean * 100).toFixed(2)), sunkguard: Number((full.late_failure_rate.mean * 100).toFixed(2)) },
    ],
    ablation: [
      { label: 'Baseline', wastedTokens: Number((base.wasted_token_ratio.mean * 100).toFixed(2)), lateFailures: Number((base.late_failure_rate.mean * 100).toFixed(2)), fairness: Number(base.jain_fairness.mean.toFixed(2)), waitTime: Number(base.new_work_wait.mean_ticks.toFixed(2)) },
      { label: 'FIFO', wastedTokens: Number((fifo.wasted_token_ratio.mean * 100).toFixed(2)), lateFailures: Number((fifo.late_failure_rate.mean * 100).toFixed(2)), fairness: Number(fifo.jain_fairness.mean.toFixed(2)), waitTime: Number(fifo.new_work_wait.mean_ticks.toFixed(2)) },
      { label: 'Progress-Only', wastedTokens: Number((prog.wasted_token_ratio.mean * 100).toFixed(2)), lateFailures: Number((prog.late_failure_rate.mean * 100).toFixed(2)), fairness: Number(prog.jain_fairness.mean.toFixed(2)), waitTime: Number(prog.new_work_wait.mean_ticks.toFixed(2)) },
      { label: 'Admission-Only', wastedTokens: Number((adm.wasted_token_ratio.mean * 100).toFixed(2)), lateFailures: Number((adm.late_failure_rate.mean * 100).toFixed(2)), fairness: Number(adm.jain_fairness.mean.toFixed(2)), waitTime: Number(adm.new_work_wait.mean_ticks.toFixed(2)) },
      { label: 'Full SunkGuard', wastedTokens: Number((full.wasted_token_ratio.mean * 100).toFixed(2)), lateFailures: Number((full.late_failure_rate.mean * 100).toFixed(2)), fairness: Number(full.jain_fairness.mean.toFixed(2)), waitTime: Number(full.new_work_wait.mean_ticks.toFixed(2)) },
    ],
    metrics: [
      { label: 'Wasted-token ratio', value: `${(full.wasted_token_ratio.mean * 100).toFixed(2)}%`, baseline: `${(base.wasted_token_ratio.mean * 100).toFixed(2)}%`, direction: 'benefit' },
      { label: 'Late failure rate', value: `${(full.late_failure_rate.mean * 100).toFixed(2)}%`, baseline: `${(base.late_failure_rate.mean * 100).toFixed(2)}%`, direction: 'benefit' },
      { label: 'Completed runs', value: `${full.completed_runs.mean.toFixed(1)}`, baseline: `${base.completed_runs.mean.toFixed(1)}`, direction: 'cost' },
      { label: 'New-work wait', value: `${full.new_work_wait.mean_ticks.toFixed(2)}t (${(full.new_work_wait.mean_ticks * 0.9818).toFixed(2)}s)`, baseline: `${base.new_work_wait.mean_ticks.toFixed(2)}t (${(base.new_work_wait.mean_ticks * 0.9818).toFixed(2)}s)`, direction: 'cost' },
      { label: 'Jain fairness', value: `${full.jain_fairness.mean.toFixed(3)}`, baseline: `${base.jain_fairness.mean.toFixed(3)}`, direction: 'cost' },
      { label: 'Predictor hit rate', value: `${(full.predictor_hit_rate.mean * 100).toFixed(1)}%`, baseline: 'n/a', direction: 'benefit' },
    ],
  }
}

// Build static workflows from recorded live traces
export function getStaticWorkflows(): Workflow[] {
  const result: Workflow[] = []
  const traces = [trace1, trace2, trace3].filter(Boolean)

  traces.forEach((t, idx) => {
    const totalTokens = t.steps ? t.steps.reduce((acc: number, s: any) => acc + (s.total_tokens || 0), 0) : 0
    const completedSteps = t.steps ? t.steps.filter((s: any) => s.success).map((s: any) => s.step_name) : []
    const timeline = (t.steps || []).map((s: any) => ({
      label: s.step_name,
      detail: `${s.resource_id} · ${s.total_tokens || 0} tokens · ${s.latency_seconds ? s.latency_seconds.toFixed(2) : 0}s`,
      state: s.success ? ('complete' as const) : ('current' as const),
    }))

    result.push({
      id: t.workflow_id || `trace-wf-${idx + 1}`,
      name: t.scenario_name || `Live Gemini Workflow ${idx + 1}`,
      agentType: t.agent_type || 'Gemini Agent',
      status: t.final_status === 'COMPLETED' ? 'COMPLETED' : 'RUNNING',
      progress: t.final_progress_pct || 75,
      workAtRisk: t.work_at_risk || 0.75,
      currentStep: completedSteps[completedSteps.length - 1] || 'Executing step',
      predictionConfidence: 0.95,
      reservationType: 'HARD',
      resourceNeed: 'Gemini Pro / Flash tokens',
      updatedAt: 'Live trace replay',
      tokensSpent: `${totalTokens} tokens`,
      remainingDemand: '0 tokens',
      protectionValue: t.protection_value || 0.01,
      waitingTime: '0s',
      completedSteps,
      timeline,
      recentEventIds: [`trace-evt-${idx + 1}`],
    })
  })

  return result
}

// Build static activity events from traces
export function getStaticEvents(): ActivityEvent[] {
  const events: ActivityEvent[] = []
  const traces = [trace1, trace2, trace3].filter(Boolean)

  traces.forEach((t, idx) => {
    (t.steps || []).forEach((s: any, stepIdx: number) => {
      events.push({
        id: `trace-evt-${idx + 1}-${stepIdx + 1}`,
        type: s.success ? 'success' : 'danger',
        category: 'Execution',
        title: `${t.scenario_name || 'Workflow'}: ${s.step_name}`,
        detail: `${s.resource_id} allocated · latency ${s.latency_seconds ? s.latency_seconds.toFixed(2) : 0}s (${s.total_tokens || 0} tokens)`,
        timestamp: 'Trace record',
        workflowId: t.workflow_id,
        resource: s.resource_id === 'pro' ? 'Gemini 1.5 Pro' : 'Gemini 1.5 Flash',
        payload: s.prompt ? s.prompt.substring(0, 80) + '...' : undefined,
      })
    })
  })

  return events
}

export function getStaticOverview() {
  const experiment = getStaticExperiment()
  const workflows = getStaticWorkflows()
  const events = getStaticEvents()

  const metrics: Metric[] = [
    { label: 'Active traces', value: String(workflows.length), change: 'Loaded', direction: 'up', tone: 'blue', helper: `${workflows.length} real Gemini execution traces` },
    { label: 'Wasted tokens', value: '0.51%', change: '−83% vs base', direction: 'down', tone: 'rose', helper: 'Gate 3 load 0.50 frozen' },
    { label: 'Late failures', value: '0.94%', change: '−65% vs base', direction: 'down', tone: 'amber', helper: 'Gate 3 load 0.50 frozen' },
    { label: 'Median latency', value: calib ? `${calib.median_step_latency_seconds.toFixed(2)}s` : '2.95s', change: 'Measured', direction: 'neutral', tone: 'green', helper: `Calibrated from n=${calib ? calib.call_count : 9} calls` },
    { label: 'Jain fairness', value: '0.968', change: 'Balanced', direction: 'up', tone: 'violet', helper: 'Load 0.50' },
    { label: 'Predictor hit rate', value: '96.2%', change: 'High', direction: 'up', tone: 'blue', helper: 'Template DAG predictor' },
  ]

  const resources: Resource[] = [
    {
      id: 'pro',
      name: 'Gemini 1.5 Pro (Model)',
      type: 'Model tokens',
      capacity: '32 units / tick',
      used: 65,
      reserved: 20,
      available: 15,
      unit: 'units',
      trend: 4,
      rateLimit: '2500 tokens / call',
      currentWindow: '00:30 remaining',
      hardReservations: 4,
      softReservations: 2,
      history: [
        { label: '00:00', used: 40, reserved: 15 },
        { label: '00:01', used: 55, reserved: 20 },
        { label: '00:02', used: 65, reserved: 20 },
      ],
      futureWindows: [
        { label: 'Now', pressure: 85, reserved: '20 units' },
        { label: '+1 tick', pressure: 60, reserved: '12 units' },
      ],
    },
    {
      id: 'flash',
      name: 'Gemini 1.5 Flash (Model)',
      type: 'Model tokens',
      capacity: '64 units / tick',
      used: 45,
      reserved: 15,
      available: 40,
      unit: 'units',
      trend: -2,
      rateLimit: '1500 tokens / call',
      currentWindow: '00:30 remaining',
      hardReservations: 2,
      softReservations: 1,
      history: [
        { label: '00:00', used: 30, reserved: 10 },
        { label: '00:01', used: 40, reserved: 12 },
        { label: '00:02', used: 45, reserved: 15 },
      ],
      futureWindows: [
        { label: 'Now', pressure: 60, reserved: '15 units' },
        { label: '+1 tick', pressure: 40, reserved: '8 units' },
      ],
    },
  ]

  const reservations: Reservation[] = [
    {
      id: 'res-trace-01',
      workflowId: 'wf-007',
      workflowName: 'Market Intelligence Brief',
      resource: 'Gemini 1.5 Pro',
      amount: '3 units',
      type: 'HARD',
      confidence: 0.95,
      expiresIn: '01:30',
      protectionValue: 0.01,
      status: 'ACTIVE',
      createdAt: 'Trace replay',
      workAtRisk: '701 tokens',
      predictedDemand: 'Gemini Pro step 2',
      pFailWithout: 0.35,
      pFailWith: 0.08,
      deltaPFail: 0.27,
      normalizedCost: 1.5,
    },
  ]

  const prediction: Prediction = {
    workflowId: 'wf-007',
    workflowName: 'Market Intelligence Brief',
    nodes: [
      { label: 'Inquiry', detail: 'completed', confidence: 1.0, state: 'complete' },
      { label: 'Synthesize Pro', detail: '3 units reserved', confidence: 0.95, state: 'reserved' },
      { label: 'Review Flash', detail: 'predicted next', confidence: 0.90, state: 'predicted' },
    ],
    pathConfidence: 0.92,
    remainingTokens: '462 tokens',
  }

  const policy: Policy = {
    mode: 'Medium',
    reservationCeiling: 70,
    agingRate: 0.16,
    confidenceThreshold: 0.8,
    softThreshold: 0.5,
    predictionHorizon: 4,
    chainDepth: 'Full remaining chain',
    riskWeight: 1.4,
  }

  return {
    events,
    experiment,
    metrics,
    policy,
    prediction,
    reservations,
    resources,
    workflows,
    isStaticDemo: true,
  }
}
