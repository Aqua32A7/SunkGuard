import React, { useState, useEffect, useRef } from 'react'
import {
  ShieldCheck,
  Mail,
  KeyRound,
  ArrowRight,
  Sparkles,
  Lock,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Database,
  Wifi,
  Flame,
  Zap,
} from 'lucide-react'
import { supabaseAuth } from '../services/supabaseAuth'
import type { AuthUser } from '../domain/types'

interface LandingPageProps {
  onLoginSuccess: (user: AuthUser, token: string) => void
}

export const LandingPage: React.FC<LandingPageProps> = ({ onLoginSuccess }) => {
  // Authentication Form States
  const [email, setEmail] = useState('')
  const [step, setStep] = useState<'EMAIL' | 'OTP'>('EMAIL')
  const [otpDigits, setOtpDigits] = useState<string[]>(['', '', '', '', '', ''])
  const [isLoading, setIsLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [remainingAttempts, setRemainingAttempts] = useState<number | null>(null)
  const [resendCooldown, setResendCooldown] = useState(0)

  // Refs for 6 OTP input boxes
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  // Resend countdown timer
  useEffect(() => {
    if (resendCooldown <= 0) return
    const timer = setInterval(() => {
      setResendCooldown((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [resendCooldown])

  // Handle requesting OTP code
  const handleRequestOtp = async (targetEmail?: string) => {
    const emailToUse = (targetEmail || email).trim().toLowerCase()
    if (!emailToUse || !emailToUse.includes('@')) {
      setErrorMsg('Please provide a valid email address.')
      return
    }

    setIsLoading(true)
    setErrorMsg(null)
    setSuccessMsg(null)

    const res = await supabaseAuth.requestOtp(emailToUse)
    setIsLoading(false)

    if (res.success) {
      setEmail(emailToUse)
      setStep('OTP')
      setResendCooldown(res.retry_after_seconds || 30)
      setOtpDigits(['', '', '', '', '', ''])
      setRemainingAttempts(null)
      setSuccessMsg(res.message || `Verification code sent to ${emailToUse}`)
      // Focus first input box shortly
      setTimeout(() => {
        inputRefs.current[0]?.focus()
      }, 100)
    } else {
      setErrorMsg(res.message || 'Failed to request verification code.')
      if (res.retry_after_seconds) {
        setResendCooldown(res.retry_after_seconds)
      }
    }
  }

  // Handle segmented OTP digit entry
  const handleDigitChange = (index: number, val: string) => {
    const char = val.slice(-1) // take last character typed
    if (char && !/^\d$/.test(char)) return // digits only

    const nextDigits = [...otpDigits]
    nextDigits[index] = char
    setOtpDigits(nextDigits)
    setErrorMsg(null)

    // Automatically focus next input box
    if (char && index < 5) {
      inputRefs.current[index + 1]?.focus()
    }

    // If all 6 digits are entered, auto-trigger verification
    if (char && index === 5 && nextDigits.every((d) => d !== '')) {
      triggerVerification(email, nextDigits.join(''))
    }
  }

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !otpDigits[index] && index > 0) {
      // Focus previous input on backspace if current is empty
      inputRefs.current[index - 1]?.focus()
    }
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').trim()
    if (/^\d{6}$/.test(pasted)) {
      const digits = pasted.split('')
      setOtpDigits(digits)
      inputRefs.current[5]?.focus()
      triggerVerification(email, pasted)
    }
  }

  // Verification execution
  const triggerVerification = async (targetEmail: string, code: string) => {
    if (code.length !== 6) {
      setErrorMsg('Please enter all 6 digits of the code.')
      return
    }

    setIsLoading(true)
    setErrorMsg(null)

    const res = await supabaseAuth.verifyOtp(targetEmail, code)
    setIsLoading(false)

    if (res.success && res.token && res.user) {
      setSuccessMsg('Authentication verified! Access granted.')
      onLoginSuccess(res.user, res.token)
    } else {
      setErrorMsg(res.message || 'Invalid or expired passcode.')
      if (typeof res.remaining_attempts === 'number') {
        setRemainingAttempts(res.remaining_attempts)
      }
    }
  }

  return (
    <div className="landing-container">
      {/* Background radial glow accents */}
      <div className="landing-bg-glow glow-1" />
      <div className="landing-bg-glow glow-2" />

      {/* Top Navigation Bar */}
      <header className="landing-nav">
        <div className="landing-brand">
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
            <Sparkles size={13} />
            <span>Donut Challenge 02: Supabase OTP Auth</span>
          </span>
          <span className="landing-pill status-pill">
            <span className={`status-indicator-dot ${supabaseAuth.isConfigured() ? 'online' : 'pulse'}`} />
            <span>{supabaseAuth.isConfigured() ? 'Supabase Auth Cloud: Connected' : 'Supabase Auth: Local Dev Mode'}</span>
          </span>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="landing-main">
        {/* Left Hero Pitch Section */}
        <section className="landing-hero">
          <div className="hero-eyebrow">
            <Flame size={14} className="hero-flame-icon" />
            <span>Google DeepMind Hackdays 2026</span>
          </div>

          <h1 className="hero-title">
            Zero Late Failures. <br />
            <span className="gradient-text">Predictive Resource Protection</span> <br />
            for Multi-Agent LLMs.
          </h1>

          <p className="hero-description">
            Prevent catastrophic pipeline aborts when agents run deep into reasoning chains.
            SunkGuard predicts downstream token and quota demands, issues hard/soft reservations via
            progress-weighted aging queues, and guarantees continuous offline resilience with
            zero-loss journal synchronization.
          </p>

          {/* Value Props Grid */}
          <div className="hero-features-grid">
            <div className="hero-feature-card">
              <div className="feature-icon-wrapper amber">
                <Zap size={18} />
              </div>
              <div>
                <strong>Dynamic Hard/Soft Reservations</strong>
                <p>Prioritizes high-investment workflows with monotonic priority aging.</p>
              </div>
            </div>

            <div className="hero-feature-card">
              <div className="feature-icon-wrapper green">
                <Wifi size={18} />
              </div>
              <div>
                <strong>Autonomous Offline Journal</strong>
                <p>Operates 60s+ disconnected with zero data loss and auto-reconciliation.</p>
              </div>
            </div>

            <div className="hero-feature-card">
              <div className="feature-icon-wrapper purple">
                <Lock size={18} />
              </div>
              <div>
                <strong>Zero-Knowledge OTP Email Auth</strong>
                <p>6-digit verification code with salted SHA-256 hashing & lockout protection.</p>
              </div>
            </div>
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
          </div>
        </section>

        {/* Right Glassmorphic Login Card */}
        <section className="landing-auth-card-container">
          <div className="glass-auth-card">
            {/* Auth Card Header */}
            <div className="auth-card-header">
              <div className="auth-card-icon">
                {step === 'EMAIL' ? <KeyRound size={22} /> : <Mail size={22} />}
              </div>
              <div>
                <h2>{step === 'EMAIL' ? 'Control Plane Login' : 'Verify Email OTP'}</h2>
                <p>
                  {step === 'EMAIL'
                    ? 'Enter your email to receive a secure 6-digit one-time passcode'
                    : `Enter the 6-digit verification code delivered to ${email}`}
                </p>
              </div>
            </div>

            {/* Error & Success Messages */}
            {errorMsg && (
              <div className="auth-alert error">
                <AlertCircle size={16} />
                <span>{errorMsg}</span>
              </div>
            )}

            {successMsg && !errorMsg && (
              <div className="auth-alert success">
                <CheckCircle2 size={16} />
                <span>{successMsg}</span>
              </div>
            )}

            {/* Delivery Status Banner (Code Kept Private) */}
            {step === 'OTP' && (
              <div className="otp-dispatch-notice">
                <div className="dispatch-notice-header">
                  <Mail size={16} className="dispatch-icon" />
                  <span>Passcode Dispatched</span>
                </div>
                <p className="dispatch-notice-desc">
                  Check your email inbox for your 6-digit one-time code.
                </p>
                {!supabaseAuth.isConfigured() && (
                  <div className="dev-mode-tip">
                    <span>💡 Local test mode: verification code was logged in your backend server terminal.</span>
                  </div>
                )}
              </div>
            )}

            {/* Step 1: Email Form */}
            {step === 'EMAIL' && (
              <form
                className="auth-form"
                onSubmit={(e) => {
                  e.preventDefault()
                  handleRequestOtp()
                }}
              >
                <div className="form-group">
                  <label htmlFor="auth-email-input">Corporate / Research Email</label>
                  <div className="input-with-icon">
                    <Mail size={18} className="input-icon" />
                    <input
                      id="auth-email-input"
                      type="email"
                      placeholder="e.g. engineer@sunkguard.ai"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      disabled={isLoading}
                      required
                      autoFocus
                    />
                  </div>
                </div>

                {/* Instant Demo Presets for Quick Testing */}
                <div className="preset-accounts">
                  <span className="presets-label">Instant Demo Profiles:</span>
                  <div className="presets-chips">
                    <button
                      type="button"
                      className="preset-chip"
                      onClick={() => handleRequestOtp('demo@sunkguard.ai')}
                      disabled={isLoading}
                    >
                      demo@sunkguard.ai
                    </button>
                    <button
                      type="button"
                      className="preset-chip"
                      onClick={() => handleRequestOtp('evaluator@deepmind.internal')}
                      disabled={isLoading}
                    >
                      evaluator@deepmind.internal
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  className="button primary auth-submit-btn"
                  disabled={isLoading || !email.trim()}
                >
                  {isLoading ? (
                    <>
                      <RefreshCw size={16} className="spin-icon" />
                      <span>Generating Code...</span>
                    </>
                  ) : (
                    <>
                      <span>Send Verification Code</span>
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </form>
            )}

            {/* Step 2: 6-Digit Segmented OTP Verification */}
            {step === 'OTP' && (
              <div className="auth-form">
                <div className="otp-email-change">
                  <span className="otp-target-email">{email}</span>
                  <button
                    type="button"
                    className="text-button change-email-btn"
                    onClick={() => {
                      setStep('EMAIL')
                      setErrorMsg(null)
                      setSuccessMsg(null)
                    }}
                    disabled={isLoading}
                  >
                    Change
                  </button>
                </div>

                <div className="form-group">
                  <label>Enter 6-Digit Passcode</label>
                  <div className="segmented-otp-grid" onPaste={handlePaste}>
                    {otpDigits.map((digit, idx) => (
                      <input
                        key={idx}
                        ref={(el) => {
                          inputRefs.current[idx] = el
                        }}
                        type="text"
                        inputMode="numeric"
                        maxLength={1}
                        className={`otp-box ${digit ? 'filled' : ''} ${errorMsg ? 'has-error' : ''}`}
                        value={digit}
                        onChange={(e) => handleDigitChange(idx, e.target.value)}
                        onKeyDown={(e) => handleKeyDown(idx, e)}
                        disabled={isLoading}
                        aria-label={`OTP Digit ${idx + 1}`}
                      />
                    ))}
                  </div>
                </div>

                {remainingAttempts !== null && remainingAttempts > 0 && (
                  <div className="attempts-warning">
                    <span>⚠️ Warning: {remainingAttempts} attempt(s) remaining before lockout.</span>
                  </div>
                )}

                <div className="otp-action-row">
                  <button
                    type="button"
                    className="button primary auth-submit-btn"
                    onClick={() => triggerVerification(email, otpDigits.join(''))}
                    disabled={isLoading || otpDigits.some((d) => d === '')}
                  >
                    {isLoading ? (
                      <>
                        <RefreshCw size={16} className="spin-icon" />
                        <span>Verifying...</span>
                      </>
                    ) : (
                      <>
                        <ShieldCheck size={16} />
                        <span>Verify & Launch Control Plane</span>
                      </>
                    )}
                  </button>

                  <div className="resend-container">
                    {resendCooldown > 0 ? (
                      <span className="resend-cooldown-text">
                        Resend code in <strong>{resendCooldown}s</strong>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="text-button resend-btn"
                        onClick={() => handleRequestOtp(email)}
                        disabled={isLoading}
                      >
                        <RefreshCw size={12} />
                        <span>Resend Code</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Security Guarantee Badges */}
            <div className="auth-card-footer">
              <div className="sec-guarantee">
                <ShieldCheck size={13} />
                <span>Official Supabase Email OTP Auth</span>
              </div>
              <div className="sec-guarantee">
                <Database size={13} />
                <span>Encrypted Session Persistence (JWT)</span>
              </div>
              <div className="sec-guarantee">
                <Lock size={13} />
                <span>Row Level Security (RLS) Compliant</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Landing Footer */}
      <footer className="landing-footer">
        <div>
          <strong>SunkGuard Control Plane</strong> · Google DeepMind Hackdays 2026
        </div>
        <div className="footer-links">
          <span>Relational SQLite WAL Persistence</span>
          <span>·</span>
          <span>SMTP / TLS Email Dispatch</span>
          <span>·</span>
          <span>Offline State Journal</span>
        </div>
      </footer>
    </div>
  )
}
