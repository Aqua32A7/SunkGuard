import React, { useEffect, useState } from 'react'
import { sunkGuardApi } from '../services/api'

interface ConnectivityState {
  state: 'ONLINE' | 'DISCONNECTED' | 'RECONNECTING'
  is_online: boolean
  simulated_outage: boolean
  outage_elapsed_seconds: number
  total_outages: number
  total_outage_seconds: number
  frozen_workflows: number
  offline_queued: number
}

interface ConnectivityBannerProps {
  onStateChange?: () => void
}

export const ConnectivityBanner: React.FC<ConnectivityBannerProps> = ({ onStateChange }) => {
  const [conn, setConn] = useState<ConnectivityState>({
    state: 'ONLINE',
    is_online: true,
    simulated_outage: false,
    outage_elapsed_seconds: 0,
    total_outages: 0,
    total_outage_seconds: 0,
    frozen_workflows: 0,
    offline_queued: 0,
  })
  const [isLoading, setIsLoading] = useState(false)
  const [outageTimer, setOutageTimer] = useState(0)

  const fetchStatus = async () => {
    try {
      const data = await sunkGuardApi.getConnectivity()
      setConn(data)
      if (data.state === 'DISCONNECTED') {
        setOutageTimer(Math.round(data.outage_elapsed_seconds))
      }
    } catch {}
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 1500)
    return () => clearInterval(interval)
  }, [])

  // Local tick for outage duration
  useEffect(() => {
    if (conn.state === 'DISCONNECTED') {
      const timer = setInterval(() => {
        setOutageTimer((prev) => prev + 1)
      }, 1000)
      return () => clearInterval(timer)
    }
  }, [conn.state])

  const handleSimulateOutage = async () => {
    setIsLoading(true)
    try {
      await sunkGuardApi.simulateOutage(60)
      await fetchStatus()
      if (onStateChange) onStateChange()
    } finally {
      setIsLoading(false)
    }
  }

  const handleRestore = async () => {
    setIsLoading(true)
    try {
      await sunkGuardApi.restoreConnectivity()
      await fetchStatus()
      if (onStateChange) onStateChange()
    } finally {
      setIsLoading(false)
    }
  }

  const formatSeconds = (sec: number) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  if (conn.state === 'DISCONNECTED') {
    return (
      <div className="connectivity-banner offline-active" style={{
        background: 'linear-gradient(90deg, rgba(245, 158, 11, 0.18) 0%, rgba(220, 38, 38, 0.15) 100%)',
        border: '1px solid rgba(245, 158, 11, 0.5)',
        borderRadius: '10px',
        padding: '12px 18px',
        margin: '0 0 18px 0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '12px',
        animation: 'pulse-glow 2s infinite ease-in-out'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
          <span style={{
            background: '#d97706',
            color: '#fff',
            padding: '4px 10px',
            borderRadius: '6px',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#fff', animation: 'blink 1s infinite' }} />
            ⚡ OFFLINE MODE · LOCAL SAFE MODE
          </span>

          <span style={{ color: '#fef3c7', fontSize: '13px', fontWeight: 600 }}>
            Outage duration: <strong style={{ color: '#f59e0b', fontFamily: 'monospace' }}>{formatSeconds(outageTimer)}</strong>
          </span>

          <span style={{ color: '#cbd5e1', fontSize: '13px', borderLeft: '1px solid rgba(255,255,255,0.15)', paddingLeft: '12px' }}>
            🛡️ Sunk-Cost Vault: <strong style={{ color: '#38bdf8' }}>{conn.frozen_workflows} agent(s) frozen</strong> · <strong style={{ color: '#a78bfa' }}>{conn.offline_queued} queued in WAL</strong>
          </span>

          <span style={{ color: '#94a3b8', fontSize: '12px' }}>
            (Halted patience clocks · 0 tokens wasted · Local tool steps executing)
          </span>
        </div>

        <button
          onClick={handleRestore}
          disabled={isLoading}
          style={{
            background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            padding: '7px 14px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            boxShadow: '0 2px 6px rgba(16, 185, 129, 0.4)',
            transition: 'all 0.2s',
          }}
        >
          {isLoading ? 'Reconnecting...' : '🔄 Restore Connection Now'}
        </button>
      </div>
    )
  }

  if (conn.state === 'RECONNECTING') {
    return (
      <div className="connectivity-banner reconciling-active" style={{
        background: 'linear-gradient(90deg, rgba(59, 130, 246, 0.18) 0%, rgba(147, 51, 234, 0.15) 100%)',
        border: '1px solid rgba(59, 130, 246, 0.4)',
        borderRadius: '10px',
        padding: '12px 18px',
        margin: '0 0 18px 0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{
            background: '#2563eb',
            color: '#fff',
            padding: '4px 10px',
            borderRadius: '6px',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.05em'
          }}>
            🔄 RECONNECTING
          </span>
          <span style={{ color: '#93c5fd', fontSize: '13px', fontWeight: 500 }}>
            Re-synchronizing offline WAL journal · Unfreezing agents in SunkGuard priority order with 0 token waste...
          </span>
        </div>
      </div>
    )
  }

  // ONLINE STATE
  return (
    <div className="connectivity-banner online-active" style={{
      background: 'rgba(15, 23, 42, 0.65)',
      border: '1px solid rgba(34, 197, 94, 0.25)',
      borderRadius: '10px',
      padding: '8px 16px',
      margin: '0 0 16px 0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: '10px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          background: '#22c55e',
          boxShadow: '0 0 8px #22c55e',
          display: 'inline-block'
        }} />
        <span style={{ color: '#86efac', fontSize: '12px', fontWeight: 600, letterSpacing: '0.03em' }}>
          LIVE CONNECTIVITY
        </span>
        <span style={{ color: '#64748b', fontSize: '12px' }}>·</span>
        <span style={{ color: '#94a3b8', fontSize: '12px' }}>
          Upstream Gemini 3.5 API Active · Offline Resilience Subsystem Ready
        </span>
        {conn.total_outages > 0 && (
          <span style={{ color: '#cbd5e1', fontSize: '11px', background: 'rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '4px' }}>
            {conn.total_outages} outage(s) survived ({Math.round(conn.total_outage_seconds)}s total) · 100% token preservation
          </span>
        )}
      </div>

      <button
        onClick={handleSimulateOutage}
        disabled={isLoading}
        title="Simulate a 60-second internet outage to test offline admission, grace freezing, and automatic recovery"
        style={{
          background: 'rgba(245, 158, 11, 0.15)',
          color: '#fbbf24',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          borderRadius: '6px',
          padding: '5px 12px',
          fontSize: '11px',
          fontWeight: 600,
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          transition: 'all 0.2s',
        }}
      >
        ⚡ Simulate 60s Outage
      </button>
    </div>
  )
}
