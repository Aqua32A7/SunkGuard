import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Activity, AlertTriangle, BarChart3, Bell, Bot, ChevronDown, CircleHelp, Clock3, Database, Gauge, GitBranch, Layers3, LayoutDashboard, LogOut, Menu, Play, ShieldCheck, SlidersHorizontal, Sparkles, Workflow as WorkflowIcon, X } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ActivityEvent, AuthUser, Metric, PolicyMode, Reservation, Resource, Workflow } from './domain/types'
import { authApi, sunkGuardApi } from './services/api'
import { ActivityPage, AnalyticsPage, PoliciesPage, ReservationsPage, ResourcesPage, WorkflowsPage } from './pages/OperationsPages'
import { ConnectivityBanner } from './components/ConnectivityBanner'
import { LandingPage } from './components/LandingPage'
import './App.css'
import './polish.css'

const navItems = [
  { label: 'Overview', path: '/', icon: LayoutDashboard }, { label: 'Workflows', path: '/workflows', icon: WorkflowIcon },
  { label: 'Resources', path: '/resources', icon: Gauge }, { label: 'Reservations', path: '/reservations', icon: Layers3 },
  { label: 'Analytics / Experiments', path: '/analytics', icon: BarChart3 }, { label: 'Activity', path: '/activity', icon: Activity },
  { label: 'Policies', path: '/policies', icon: SlidersHorizontal },
]

type Overview = Awaited<ReturnType<typeof sunkGuardApi.getOverview>>

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [policyMode, setPolicyMode] = useState<PolicyMode>('Medium')
  const [demoAction, setDemoAction] = useState('')
  const [demoPhase, setDemoPhase] = useState(0)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [backendConnected, setBackendConnected] = useState<boolean>(false)

  // Authentication states (Donut Challenge 02)
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [authChecked, setAuthChecked] = useState<boolean>(false)

  const refreshOverview = () => {
    void sunkGuardApi.getOverview().then((data) => {
      setOverview(data)
      setBackendConnected(sunkGuardApi.isBackendConnected() ?? false)
    }).catch(() => setLoadError(true))
  }

  useEffect(() => {
    // Validate existing session token from SQLite database
    void authApi.getCurrentUser().then((res) => {
      if (res.authenticated && res.user) {
        setCurrentUser(res.user)
      } else {
        setCurrentUser(null)
      }
      setAuthChecked(true)
    })
    refreshOverview()
  }, [])
  useEffect(() => {
    if (demoPhase === 0) return
    const timer = window.setTimeout(async () => {
      if (demoPhase < 7) {
        const res = await sunkGuardApi.demoStep()
        setDemoPhase(res.phase)
        refreshOverview()
      } else {
        setDemoPhase(0)
      }
    }, 1100)
    return () => window.clearTimeout(timer)
  }, [demoPhase])

  const demoMessages = [
    'Step 1/7 · Workflow A is 82% complete with $42.80 work-at-risk.',
    'Step 2/7 · Workflow B is 14% complete and contending for Gemini capacity.',
    'Step 3/7 · SunkGuard protects A: HARD reservation committed for its remaining chain.',
    'Step 4/7 · Workflow B waits while aging raises its effective priority.',
    'Step 5/7 · Workflow A completes its protected steps.',
    'Step 6/7 · A reservation releases automatically; Gemini capacity is available.',
    'Step 7/7 · Workflow B is admitted. Demo sequence complete.',
  ]
  const demoNotice = demoPhase > 0 ? demoMessages[demoPhase - 1] : demoAction

  const runDemo = async () => {
    setDemoAction('')
    const res = await sunkGuardApi.demoStep()
    setDemoPhase(res.phase)
    refreshOverview()
  }

  const runMismatch = async () => {
    setDemoPhase(0)
    const res = await sunkGuardApi.demoMismatch()
    setDemoAction(res.notice)
    refreshOverview()
  }

  const handlePolicyChange = async (mode: PolicyMode) => {
    setPolicyMode(mode)
    await sunkGuardApi.setPolicyMode(mode)
    refreshOverview()
  }

  const handleLogout = async () => {
    await authApi.logout()
    setCurrentUser(null)
  }

  if (!authChecked) {
    return (
      <div className="loading-screen">
        <Sparkles size={18} /> Initializing SunkGuard Security...
      </div>
    )
  }

  // Challenge 02: Route Guard - Landing Page with OTP Login
  if (!currentUser) {
    return (
      <LandingPage
        onLoginSuccess={(user) => {
          setCurrentUser(user)
          refreshOverview()
        }}
      />
    )
  }

  if (loadError) return <div className="state-screen error-state"><AlertTriangle size={22} /><strong>Controller state unavailable</strong><span>The demo data service could not load. Refresh to retry the local frontend state.</span></div>
  if (!overview) return <div className="loading-screen"><Sparkles size={18} /> Loading controller state...</div>
  return <BrowserRouter>
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'is-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><ShieldCheck size={18} /></div><div><strong>SunkGuard</strong><span>Agent control plane</span></div><button className="icon-button sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"><X size={18} /></button></div>
        <div className="workspace-switcher"><div className="workspace-avatar">SG</div><div><strong>Demo workspace</strong><span>Simulation environment</span></div><ChevronDown size={15} /></div>
        <nav className="nav-list">{navItems.map(({ label, path, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} onClick={() => setSidebarOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon size={17} /><span>{label}</span>{label === 'Activity' && <span className="nav-dot" />}</NavLink>)}</nav>
        <div className="sidebar-footer"><div className="system-health"><span className={`status-dot ${backendConnected ? 'connected' : 'warning'}`} /> <span>{backendConnected ? 'Controller online' : 'Mock engine'}</span><span className="health-pulse" /></div><div className="sidebar-links"><CircleHelp size={15} /> Help center <span>⌘ /</span></div><div className="sidebar-links"><SlidersHorizontal size={15} /> Workspace settings</div></div>
      </aside>
      {sidebarOpen && <button className="mobile-overlay" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
      <main className="main-shell">
        <Topbar
          onOpenNavigation={() => setSidebarOpen(true)}
          backendConnected={backendConnected}
          isStaticDemo={sunkGuardApi.isStaticDemoMode()}
          onToggleStaticDemo={() => {
            const next = !sunkGuardApi.isStaticDemoMode()
            sunkGuardApi.setStaticDemoMode(next)
            refreshOverview()
          }}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
        <div style={{ maxWidth: '1280px', margin: '14px auto 0', padding: '0 20px' }}>
          <ConnectivityBanner onStateChange={refreshOverview} />
        </div>
        <Routes>
          <Route path="/" element={<OverviewPage {...overview} policyMode={policyMode} setPolicyMode={handlePolicyChange} onRunDemo={runDemo} demoNotice={demoNotice} />} />
          <Route path="/workflows" element={<WorkflowsPage data={overview} onRunDemo={runDemo} onWrongPrediction={runMismatch} demoNotice={demoNotice} />} />
          <Route path="/resources" element={<ResourcesPage data={overview} />} />
          <Route path="/reservations" element={<ReservationsPage data={overview} />} />
          <Route path="/analytics" element={<AnalyticsPage experiment={overview.experiment} />} />
          <Route path="/activity" element={<ActivityPage events={overview.events} />} />
          <Route path="/policies" element={<PoliciesPage policy={overview.policy} mode={policyMode} onChange={handlePolicyChange} />} />
        </Routes>
      </main>
    </div>
  </BrowserRouter>
}

function Topbar({
  onOpenNavigation,
  backendConnected,
  isStaticDemo,
  onToggleStaticDemo,
  currentUser,
  onLogout,
}: {
  onOpenNavigation: () => void
  backendConnected: boolean
  isStaticDemo: boolean
  onToggleStaticDemo: () => void
  currentUser: AuthUser | null
  onLogout: () => void
}) {
  const location = useLocation()
  const current = navItems.find((item) => item.path === location.pathname)?.label ?? 'Overview'
  return <header className="topbar">
    <button className="icon-button menu-button" onClick={onOpenNavigation} aria-label="Open navigation"><Menu size={20} /></button>
    <div className="breadcrumbs"><span>Control plane</span><span>/</span><strong>{current}</strong></div>
    <div className="topbar-actions">
      <button
        className={`button ${isStaticDemo ? 'primary' : 'secondary'}`}
        style={{ padding: '4px 10px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '5px' }}
        onClick={onToggleStaticDemo}
        title="Toggle static demo mode reading eval/results/*.json and demo/traces/*.json"
      >
        <Database size={13} /> {isStaticDemo ? 'Static Demo (eval + traces)' : 'Live API Mode'}
      </button>
      <div className="live-indicator"><span className={`status-dot ${backendConnected ? 'connected' : 'warning'}`} /> {backendConnected ? 'Backend: Connected' : 'Demo Mode'}</div>
      <button className="icon-button" aria-label="Notifications"><Bell size={18} /><i /></button>
      
      {currentUser ? (
        <div className="user-profile-badge">
          <div className="user-profile-avatar">
            {currentUser.name.slice(0, 2).toUpperCase()}
          </div>
          <div className="user-profile-details">
            <span className="user-profile-name">{currentUser.name}</span>
            <span className="user-profile-role">{currentUser.role}</span>
          </div>
          <button className="logout-btn" onClick={onLogout} title="Sign Out">
            <LogOut size={13} />
            <span>Sign out</span>
          </button>
        </div>
      ) : (
        <div className="user-avatar">SG</div>
      )}
    </div>
  </header>
}

function OverviewPage({ metrics, workflows, resources, reservations, prediction, events, experiment, policy, policyMode, setPolicyMode, onRunDemo, demoNotice }: Overview & { policyMode: PolicyMode; setPolicyMode: (mode: PolicyMode) => void; onRunDemo: () => void; demoNotice?: string }) {
  return <div className="page-container">
    <section className="page-heading"><div><div className="eyebrow"><span className="status-dot" /> SunkGuard control plane <span className="eyebrow-divider">/</span> <span>Demo data · Seed 1042</span></div><h1>Protecting work in progress.</h1><p>One view of the agents, resources, and reservations keeping your most valuable work moving.</p></div><div className="heading-actions"><button className="button secondary" onClick={onRunDemo}><Play size={15} /> Run demo scenario</button><button className="button primary"><Sparkles size={15} /> New workflow</button></div></section>
    {demoNotice && <div className="demo-notice"><Sparkles size={14} /> {demoNotice}</div>}
    <section className="metric-grid">{metrics.filter((metric) => ['Wasted tokens', 'Late-stage failures', 'Resource utilization', 'Jain fairness index'].includes(metric.label)).map((metric) => <MetricCard key={metric.label} metric={metric} />)}</section>
    <div className="content-grid two-thirds"><section className="panel workflow-panel"><PanelHeader title="Workflow control" subtitle="Live view of concurrent agent work" action="View all workflows" /><div className="scenario-callout"><div className="scenario-icon"><ShieldCheck size={17} /></div><div><strong>Protection scenario active</strong><span>Workflow A is 82% complete. SunkGuard reserved its remaining chain before admitting newer work.</span></div><span className="scenario-tag">80% vs 10%</span></div><div className="workflow-list">{workflows.map((workflow) => <WorkflowRow key={workflow.id} workflow={workflow} />)}</div></section><section className="panel protection-panel"><PanelHeader title="Why this was protected" subtitle="Decision record · wf-092" action="Details" /><div className="decision-hero"><div className="decision-icon"><ShieldCheck size={22} /></div><div><strong>Customer insight brief</strong><span>Hard reservation committed</span></div><span className="status-badge hard">HARD</span></div><div className="decision-stats"><DecisionStat label="Work-at-risk" value="$42.80" /><DecisionStat label="Failure risk" value="38% → 6%" /><DecisionStat label="Protection value" value="4.84" /><DecisionStat label="Predicted demand" value="16k tokens" /></div><div className="formula-box"><span>protection value</span><strong>work-at-risk × Δ failure probability ÷ capacity</strong><small>42.80 × 0.32 ÷ 2.83 = 4.84</small></div><div className="decision-footer"><span><span className="status-dot" /> Decision inputs measured</span><span>confidence 0.92</span></div></section></div>
    <div className="content-grid equal"><section className="panel"><PanelHeader title="Shared resources" subtitle="Used capacity vs. future reservations" action="Manage resources" /><div className="resource-list">{resources.map((resource) => <ResourceRow key={resource.id} resource={resource} />)}</div></section><section className="panel chain-panel"><PanelHeader title="Remaining chain" subtitle={`${prediction.workflowName} · predicted path`} action="Open workflow" /><div className="chain-meta"><span><span className="status-dot" /> Prediction confidence</span><strong>{Math.round(prediction.pathConfidence * 100)}%</strong><span className="chain-demand">{prediction.remainingTokens} remaining</span></div><div className="chain-flow">{prediction.nodes.map((node, index) => <div className="chain-step" key={`${node.label}-${index}`}><div className={`chain-node ${node.state}`}><span>{node.label}</span><small>{node.detail}</small>{node.state !== 'complete' && <em>{Math.round(node.confidence * 100)}%</em>}</div>{index < prediction.nodes.length - 1 && <div className="chain-arrow" />}</div>)}</div><div className="chain-note"><GitBranch size={15} /> Full remaining chain reserved atomically to avoid partial-lock deadlocks.</div></section></div>
    <div className="content-grid two-thirds"><section className="panel reservation-panel"><PanelHeader title="Active reservations" subtitle="Capacity held for future steps" action="View reservations" /><div className="reservation-table"><div className="table-head"><span>Workflow</span><span>Resource / amount</span><span>Type</span><span>TTL</span><span>Value</span></div>{reservations.map((reservation) => <ReservationRow key={reservation.id} reservation={reservation} />)}</div></section><section className="panel policy-panel"><PanelHeader title="Controller policy" subtitle="Protection and fairness balance" action="Configure" /><div className="policy-toggle">{(['Light', 'Medium', 'Aggressive'] as PolicyMode[]).map((mode) => <button key={mode} className={policyMode === mode ? 'selected' : ''} onClick={() => setPolicyMode(mode)}>{mode}</button>)}</div><div className="policy-description"><span className="policy-dot" /><div><strong>{policyMode} protection</strong><p>{policyMode === 'Aggressive' ? 'Reserve deeper into the predicted chain.' : policyMode === 'Light' ? 'Protect only the next high-confidence step.' : 'Balance late-stage protection with fresh work.'}</p></div></div><div className="policy-meters"><Meter label="Reservation ceiling" value={`${policy.reservationCeiling}%`} percent={policy.reservationCeiling} /><Meter label="Aging rate" value={policy.agingRate.toFixed(2)} percent={58} /><Meter label="Hard threshold" value={`${Math.round(policy.confidenceThreshold * 100)}%`} percent={policy.confidenceThreshold * 100} /></div></section></div>
    <div className="content-grid equal"><section className="panel activity-panel"><PanelHeader title="Live activity" subtitle="Controller event stream" action="Open activity" /><div className="activity-list">{events.map((event) => <ActivityRow key={event.id} event={event} />)}</div></section><section className="panel experiment-panel"><PanelHeader title="Thesis experiment" subtitle={`${experiment.name} · ${experiment.status}`} action="Open analytics" /><div className="experiment-chart"><div className="chart-legend"><span><i className="legend-baseline" /> Baseline</span><span><i className="legend-sunkguard" /> With progress weighting</span></div><ResponsiveContainer width="100%" height={148}><BarChart data={experiment.points} barGap={8} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}><CartesianGrid vertical={false} stroke="#e6e9ef" /><XAxis dataKey="label" tick={{ fill: '#7c8493', fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#9ba3b0', fontSize: 10 }} axisLine={false} tickLine={false} unit="%" /><Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e2e5eb' }} /><Bar dataKey="baseline" fill="#cbd1dc" radius={[4, 4, 0, 0]} /><Bar dataKey="sunkguard" fill="#2a6ff0" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div><div className="experiment-foot"><strong>Lower is better</strong><span>Same seeded workload · simulated only</span></div></section></div>
    <div className="footer-note"><Database size={14} /> Demo values are simulated. Connect the controller API to replace this view with live state.</div>
  </div>
}

function MetricCard({ metric }: { metric: Metric }) { const Icon = metric.label === 'Active workflows' ? WorkflowIcon : metric.label === 'Wasted tokens' ? Layers3 : metric.label === 'Late-stage failures' ? ShieldCheck : metric.label === 'Resource utilization' ? Gauge : metric.label === 'Jain fairness index' ? GitBranch : Bot; return <article className={`metric-card ${metric.tone}`}><div className="metric-card-top"><div className="metric-icon"><Icon size={16} /></div><span className={`trend ${metric.direction}`}>{metric.direction === 'up' ? '↗' : metric.direction === 'down' ? '↘' : '•'} {metric.change}</span></div><span className="metric-label">{metric.label}</span><strong>{metric.value}</strong><span className="metric-helper">{metric.helper}</span></article> }
function PanelHeader({ title, subtitle, action }: { title: string; subtitle: string; action: string }) { return <div className="panel-header"><div><h2>{title}</h2><span>{subtitle}</span></div><button className="text-button">{action} <span>→</span></button></div> }
function WorkflowRow({ workflow }: { workflow: Workflow }) { const isPaused = workflow.status === 'OFFLINE_PAUSED'; const isOfflineQueued = workflow.status === 'QUEUED_OFFLINE'; return <div className={`workflow-row ${workflow.progress > 75 ? 'priority-row' : ''} ${isPaused ? 'offline-paused-row' : ''}`}><div className="workflow-id"><div className="agent-avatar"><Bot size={16} /></div><div><strong>{workflow.name}</strong><span>{workflow.id} · {workflow.agentType}</span></div></div><div className="workflow-progress"><div className="progress-label"><span>{workflow.progress}% complete</span><span style={{ color: isPaused ? '#f59e0b' : isOfflineQueued ? '#a855f7' : undefined }}>{isPaused ? '⚡ Paused (Offline)' : isOfflineQueued ? '📦 Queued (WAL)' : workflow.status === 'RUNNING' ? 'Running' : 'Queued'}</span></div><div className="progress-track"><span style={{ width: `${workflow.progress}%`, background: isPaused ? '#f59e0b' : undefined }} /></div></div><div className="workflow-step"><span>{workflow.currentStep}</span><small>{workflow.resourceNeed}</small></div><div className="workflow-confidence"><strong>{Math.round(workflow.predictionConfidence * 100)}%</strong><span>confidence</span></div><div className="workflow-risk"><strong>${workflow.workAtRisk.toFixed(2)}</strong><span>at risk</span></div><span className={`status-badge ${isPaused ? 'soft' : isOfflineQueued ? 'none' : workflow.reservationType.toLowerCase()}`}>{isPaused ? '🛡️ PAUSED' : isOfflineQueued ? 'OFFLINE' : workflow.reservationType}</span></div> }
function ResourceRow({ resource }: { resource: Resource }) { const total = resource.used + resource.reserved + resource.available; return <div className="resource-row"><div className="resource-title"><div className="resource-icon"><Database size={15} /></div><div><strong>{resource.name}</strong><span>{resource.type} · {resource.capacity}</span></div><span className={`resource-trend ${resource.trend > 0 ? 'up' : 'down'}`}>{resource.trend > 0 ? '↗' : '↘'} {Math.abs(resource.trend)}%</span></div><div className="resource-bar"><span className="used-bar" style={{ width: `${resource.used / total * 100}%` }} /><span className="reserved-bar" style={{ width: `${resource.reserved / total * 100}%` }} /></div><div className="resource-legend"><span><i className="used-key" /> Used <b>{resource.used}%</b></span><span><i className="reserved-key" /> Reserved <b>{resource.reserved}%</b></span><span><i className="available-key" /> Available <b>{resource.available}%</b></span></div></div> }
function ReservationRow({ reservation }: { reservation: Reservation }) { return <div className="reservation-row"><div><strong>{reservation.workflowName}</strong><span>{reservation.workflowId}</span></div><div><strong>{reservation.resource}</strong><span>{reservation.amount} · {Math.round(reservation.confidence * 100)}% confidence</span></div><span className={`status-badge ${reservation.type.toLowerCase()}`}>{reservation.type}</span><span className={reservation.status === 'EXPIRING' ? 'ttl warning' : 'ttl'}><Clock3 size={13} /> {reservation.expiresIn}</span><strong className="protection-value">{reservation.protectionValue.toFixed(2)}</strong></div> }
function ActivityRow({ event }: { event: ActivityEvent }) { const Icon = event.type === 'success' ? ShieldCheck : event.type === 'warning' ? Clock3 : event.type === 'danger' ? X : Sparkles; return <div className="activity-row"><div className={`activity-icon ${event.type}`}><Icon size={14} /></div><div><strong>{event.title}</strong><span>{event.detail}</span></div><time>{event.timestamp}</time></div> }
function DecisionStat({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div> }
function Meter({ label, value, percent }: { label: string; value: string; percent: number }) { return <div className="meter"><div><span>{label}</span><strong>{value}</strong></div><div className="meter-track"><span style={{ width: `${percent}%` }} /></div></div> }
export default App
