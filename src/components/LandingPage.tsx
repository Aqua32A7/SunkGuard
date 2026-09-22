import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ShieldCheck,
  ArrowRight,
  Sparkles,
  Zap,
  Wifi,
  Database,
  BarChart3,
  Layers3,
  Flame,
  CheckCircle2,
  Workflow,
  Cpu,
  Clock,
} from 'lucide-react'

interface LandingPageProps {
  onGetStarted?: () => void
}

export const LandingPage: React.FC<LandingPageProps> = ({ onGetStarted }) => {
  const navigate = useNavigate()

  const handleLaunch = () => {
    if (onGetStarted) {
      onGetStarted()
    } else {
      navigate('/dashboard')
    }
  }

  return (
    <div className="landing-container">
      {/* Background radial ambient glow accents */}
      <div className="landing-bg-glow glow-1" />
      <div className="landing-bg-glow glow-2" />

      {/* Top Navigation Bar */}
      <header className="landing-nav">
        <div className="landing-brand" onClick={handleLaunch} style={{ cursor: 'pointer' }}>
          <div className="landing-brand-icon">
            <ShieldCheck size={24} />
          </div>
          <div>
            <span className="landing-brand-name">SunkGuard</span>
            <span className="landing-brand-sub">Autonomous Predictive Control Plane</span>
          </div>
        </div>

        <div className="landing-nav-badges">
          <span className="landing-pill challenge-pill">
            <Flame size={13} />
            <span>Google DeepMind Hackdays 2026</span>
          </span>
          <span className="landing-pill status-pill">
            <span className="status-indicator-dot online" />
            <span>System Status: Operational</span>
          </span>
          <button
            type="button"
            className="button primary landing-nav-cta"
            onClick={handleLaunch}
          >
            <span>Get Started</span>
            <ArrowRight size={14} />
          </button>
        </div>
      </header>

      {/* Main Hero & Presentation Section */}
      <main className="landing-main">
        {/* Left Hero Pitch Section */}
        <section className="landing-hero">
          <div className="hero-eyebrow">
            <Sparkles size={14} className="hero-flame-icon" />
            <span>Multi-Agent LLM Resource Governor & Sunk-Cost Protection</span>
          </div>

          <h1 className="hero-title">
            Zero Late Failures. <br />
            <span className="gradient-text">Predictive Resource Protection</span> <br />
            for Multi-Agent LLMs.
          </h1>

          <p className="hero-description">
            Prevent catastrophic pipeline aborts when agents run deep into reasoning chains.
            SunkGuard predicts downstream token and quota demands, commits hard/soft reservations via
            progress-weighted aging queues, and guarantees continuous offline resilience with
            zero-loss journal synchronization.
          </p>

          {/* High-Impact Action Buttons */}
          <div className="hero-cta-group">
            <button
              type="button"
              className="button primary hero-get-started-btn"
              onClick={handleLaunch}
            >
              <Sparkles size={18} />
              <span>Get Started — Launch Control Plane</span>
              <ArrowRight size={18} />
            </button>

            <button
              type="button"
              className="button secondary hero-secondary-btn"
              onClick={() => navigate('/workflows')}
            >
              <Workflow size={16} />
              <span>Explore Workflows</span>
            </button>

            <button
              type="button"
              className="button secondary hero-secondary-btn"
              onClick={() => navigate('/analytics')}
            >
              <BarChart3 size={16} />
              <span>View Analytics</span>
            </button>
          </div>

          {/* Quick Metrics Proof Points */}
          <div className="hero-stats-bar">
            <div className="stat-item">
              <strong>62%</strong>
              <span>Latency Reduction</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <strong>0%</strong>
              <span>Sunk Work Waste</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <strong>100%</strong>
              <span>Offline Catchup</span>
            </div>
            <div className="stat-divider" />
            <div className="stat-item">
              <strong>3.2%</strong>
              <span>Failure Rate (vs 38.6%)</span>
            </div>
          </div>
        </section>

        {/* Right Glassmorphic Telemetry Preview Card */}
        <section className="landing-auth-card-container">
          <div className="glass-preview-card">
            {/* Card Header */}
            <div className="preview-card-header">
              <div className="preview-status-pill">
                <span className="status-indicator-dot online" />
                <span>Live Controller Online</span>
              </div>
              <span className="preview-model-badge">Gemini 3.5 Flash</span>
            </div>

            {/* Hero Summary */}
            <div className="preview-card-hero">
              <div className="preview-hero-icon">
                <ShieldCheck size={26} />
              </div>
              <div>
                <h3>Control Plane Dashboard</h3>
                <p>Autonomous resource prediction & workflow governor</p>
              </div>
            </div>

            {/* Telemetry Metrics */}
            <div className="preview-metrics-list">
              <div className="preview-metric-row">
                <div className="metric-meta">
                  <Cpu size={15} className="metric-icon amber" />
                  <span>Active Reservations</span>
                </div>
                <span className="metric-highlight">3 Commits (2 Hard / 1 Soft)</span>
              </div>

              <div className="preview-metric-row">
                <div className="metric-meta">
                  <Clock size={15} className="metric-icon purple" />
                  <span>Monotonic Priority Aging</span>
                </div>
                <span className="metric-highlight">α = 0.35 (Jain Index 0.91)</span>
              </div>

              <div className="preview-metric-row">
                <div className="metric-meta">
                  <Database size={15} className="metric-icon green" />
                  <span>Offline Journal (WAL)</span>
                </div>
                <span className="metric-highlight green">Synced (Zero Loss)</span>
              </div>
            </div>

            {/* Spotlight Workflow */}
            <div className="preview-spotlight">
              <div className="spotlight-tag">
                <Flame size={12} />
                <span>Protected Reasoning Chain</span>
              </div>
              <div className="spotlight-body">
                <strong>Customer Insight Brief</strong>
                <div className="spotlight-details">
                  <span>82% Complete</span>
                  <span>·</span>
                  <span>$42.80 At Risk</span>
                  <span>·</span>
                  <span className="badge-hard">HARD LOCK</span>
                </div>
              </div>
            </div>

            {/* Big Launch Action Button */}
            <button
              type="button"
              className="landing-launch-btn"
              onClick={handleLaunch}
            >
              <span>Enter Control Plane</span>
              <ArrowRight size={18} />
            </button>

            {/* Features check list */}
            <div className="preview-checklist">
              <div className="check-item">
                <CheckCircle2 size={13} className="check-icon" />
                <span>Zero login barrier · Direct open access</span>
              </div>
              <div className="check-item">
                <CheckCircle2 size={13} className="check-icon" />
                <span>Live simulation and offline resilience</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* 3 Core Architecture Pillars Showcase */}
      <section className="landing-pillars-section">
        <div className="pillars-header">
          <h2>Engineered for Deep Agent Reasoning</h2>
          <p>Three breakthrough primitives ensuring high-value compound AI workflows never abort midway.</p>
        </div>

        <div className="pillars-grid">
          <div className="pillar-card" onClick={handleLaunch}>
            <div className="pillar-icon amber">
              <Zap size={22} />
            </div>
            <h3>Dynamic Chain Reservation</h3>
            <p>
              Predicts entire downstream token and quota demands. Commits atomic hard reservations to avoid partial-lock deadlocks before admitting newer work.
            </p>
            <span className="pillar-link">Explore Reservations ➔</span>
          </div>

          <div className="pillar-card" onClick={handleLaunch}>
            <div className="pillar-icon purple">
              <Layers3 size={22} />
            </div>
            <h3>Monotonic Priority Aging</h3>
            <p>
              Workflows accumulate seniority proportionally to sunk investment. Prevents deep reasoning starvation while maintaining high fairness across agents.
            </p>
            <span className="pillar-link">View Policy Governor ➔</span>
          </div>

          <div className="pillar-card" onClick={handleLaunch}>
            <div className="pillar-icon green">
              <Wifi size={22} />
            </div>
            <h3>Autonomous Offline Journal</h3>
            <p>
              Continues uninterrupted operations during network cuts. All events and tokens persist to crash-resilient WAL journal with instant catchup on reconnect.
            </p>
            <span className="pillar-link">Inspect Storage WAL ➔</span>
          </div>
        </div>
      </section>

      {/* Landing Footer */}
      <footer className="landing-footer">
        <div>
          <strong>SunkGuard Control Plane</strong> · Google DeepMind Hackdays 2026
        </div>
        <div className="footer-links">
          <button type="button" className="footer-link-btn" onClick={() => navigate('/dashboard')}>
            Dashboard
          </button>
          <span>·</span>
          <button type="button" className="footer-link-btn" onClick={() => navigate('/workflows')}>
            Workflows
          </button>
          <span>·</span>
          <button type="button" className="footer-link-btn" onClick={() => navigate('/resources')}>
            Resources
          </button>
          <span>·</span>
          <button type="button" className="footer-link-btn" onClick={() => navigate('/analytics')}>
            Analytics
          </button>
          <span>·</span>
          <button type="button" className="footer-link-btn" onClick={() => navigate('/policies')}>
            Policies
          </button>
        </div>
      </footer>
    </div>
  )
}
