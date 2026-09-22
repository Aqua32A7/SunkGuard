/**
 * Supabase Authentication Controller for SunkGuard Donut Challenge 02.
 *
 * Implements:
 * 1. Official Supabase email OTP generation: supabase.auth.signInWithOtp()
 * 2. Official Supabase OTP verification: supabase.auth.verifyOtp()
 * 3. Session persistence & onAuthStateChange listener
 * 4. Dual-mode support (Supabase live cloud + local fallback if unconfigured)
 */

import { supabase, isSupabaseConfigured } from './supabaseClient'
import type { AuthUser } from '../domain/types'

export interface OtpRequestResult {
  success: boolean
  message: string
  error?: string
  provider: 'supabase' | 'local_dev'
  dev_otp?: string
  retry_after_seconds?: number
}

export interface OtpVerifyResult {
  success: boolean
  message: string
  user?: AuthUser
  token?: string
  error?: string
  remaining_attempts?: number
}

export const supabaseAuth = {
  isConfigured(): boolean {
    return isSupabaseConfigured()
  },

  /**
   * Dispatches a 6-digit verification code to the user's email via Supabase.
   */
  async requestOtp(email: string): Promise<OtpRequestResult> {
    const cleanEmail = email.trim().toLowerCase()
    if (!cleanEmail || !cleanEmail.includes('@')) {
      return {
        success: false,
        message: 'Please provide a valid email address.',
        error: 'INVALID_EMAIL',
        provider: isSupabaseConfigured() ? 'supabase' : 'local_dev',
      }
    }

    if (isSupabaseConfigured()) {
      try {
        const { error } = await supabase.auth.signInWithOtp({
          email: cleanEmail,
          options: {
            shouldCreateUser: true,
          },
        })

        if (error) {
          return {
            success: false,
            message: error.message || 'Supabase failed to send verification code.',
            error: error.code || 'SUPABASE_OTP_FAILED',
            provider: 'supabase',
          }
        }

        return {
          success: true,
          message: `Verification code sent to ${cleanEmail} via Supabase.`,
          provider: 'supabase',
        }
      } catch (err: any) {
        return {
          success: false,
          message: err?.message || 'Network error communicating with Supabase.',
          error: 'NETWORK_ERROR',
          provider: 'supabase',
        }
      }
    }

    // Local evaluation fallback if Supabase credentials are not yet set in .env
    try {
      const res = await fetch('/api/auth/otp/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: cleanEmail }),
      })
      const data = await res.json()
      if (!res.ok) {
        return {
          success: false,
          message: data.detail?.message || 'Failed to generate verification code.',
          error: data.detail?.error || 'REQUEST_FAILED',
          retry_after_seconds: data.detail?.retry_after_seconds,
          provider: 'local_dev',
        }
      }
      return {
        success: true,
        message: `Verification code sent to ${cleanEmail}.`,
        provider: 'local_dev',
        dev_otp: data.dev_otp,
      }
    } catch (err: any) {
      return {
        success: false,
        message: err?.message || 'Network error requesting verification code.',
        error: 'NETWORK_ERROR',
        provider: 'local_dev',
      }
    }
  },

  /**
   * Verifies the 6-digit OTP code with Supabase and establishes an authenticated session.
   */
  async verifyOtp(email: string, otpToken: string): Promise<OtpVerifyResult> {
    const cleanEmail = email.trim().toLowerCase()
    const cleanToken = otpToken.trim()

    if (isSupabaseConfigured()) {
      try {
        const { data, error } = await supabase.auth.verifyOtp({
          email: cleanEmail,
          token: cleanToken,
          type: 'email',
        })

        if (error) {
          return {
            success: false,
            message: error.message || 'Invalid or expired passcode.',
            error: error.code || 'INVALID_OTP',
          }
        }

        if (!data.session || !data.user) {
          return {
            success: false,
            message: 'Authentication failed. Please request a new code.',
            error: 'NO_SESSION',
          }
        }

        const authUser: AuthUser = {
          id: data.user.id,
          email: data.user.email || cleanEmail,
          name:
            data.user.user_metadata?.name ||
            cleanEmail.split('@')[0].replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
          role: data.user.user_metadata?.role || 'Control Plane Engineer',
          lastLoginAt: Date.now() / 1000,
        }

        return {
          success: true,
          message: 'Authenticated successfully with Supabase!',
          user: authUser,
          token: data.session.access_token,
        }
      } catch (err: any) {
        return {
          success: false,
          message: err?.message || 'Network error verifying Supabase passcode.',
          error: 'NETWORK_ERROR',
        }
      }
    }

    // Local evaluation fallback
    try {
      const res = await fetch('/api/auth/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: cleanEmail, otp: cleanToken }),
      })
      const data = await res.json()
      if (!res.ok) {
        return {
          success: false,
          message: data.detail?.message || 'Invalid passcode.',
          error: data.detail?.error || 'INVALID_OTP',
          remaining_attempts: data.detail?.remaining_attempts,
        }
      }
      return {
        success: true,
        message: 'Authenticated successfully!',
        user: data.user,
        token: data.token,
      }
    } catch (err: any) {
      return {
        success: false,
        message: err?.message || 'Network error verifying code.',
        error: 'NETWORK_ERROR',
      }
    }
  },

  /**
   * Retrieves current authenticated user from active Supabase session.
   */
  async getCurrentUser(): Promise<{ authenticated: boolean; user?: AuthUser; token?: string }> {
    if (isSupabaseConfigured()) {
      try {
        const { data: { session } } = await supabase.auth.getSession()
        if (session && session.user) {
          const authUser: AuthUser = {
            id: session.user.id,
            email: session.user.email || '',
            name:
              session.user.user_metadata?.name ||
              (session.user.email ? session.user.email.split('@')[0].replace(/\b\w/g, (c) => c.toUpperCase()) : 'Engineer'),
            role: session.user.user_metadata?.role || 'Control Plane Engineer',
            lastLoginAt: Date.now() / 1000,
          }
          return { authenticated: true, user: authUser, token: session.access_token }
        }
        return { authenticated: false }
      } catch {
        return { authenticated: false }
      }
    }

    // Local fallback: checks local token via /api/auth/me
    const token = localStorage.getItem('sunkguard_auth_token')
    if (!token) return { authenticated: false }
    try {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return { authenticated: false }
      const data = await res.json()
      return { authenticated: true, user: data.user, token }
    } catch {
      return { authenticated: false }
    }
  },

  /**
   * Subscribes to Supabase Auth state changes (SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED).
   */
  onAuthStateChange(callback: (event: string, user: AuthUser | null) => void) {
    if (isSupabaseConfigured()) {
      const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
        if (session?.user) {
          const authUser: AuthUser = {
            id: session.user.id,
            email: session.user.email || '',
            name:
              session.user.user_metadata?.name ||
              (session.user.email ? session.user.email.split('@')[0].replace(/\b\w/g, (c) => c.toUpperCase()) : 'Engineer'),
            role: session.user.user_metadata?.role || 'Control Plane Engineer',
            lastLoginAt: Date.now() / 1000,
          }
          callback(event, authUser)
        } else {
          callback(event, null)
        }
      })
      return () => subscription.unsubscribe()
    }
    return () => {}
  },

  /**
   * Terminates active session.
   */
  async logout(): Promise<void> {
    if (isSupabaseConfigured()) {
      try {
        await supabase.auth.signOut()
      } catch {}
    }
    try {
      const token = localStorage.getItem('sunkguard_auth_token')
      if (token) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
      }
    } catch {}
    localStorage.removeItem('sunkguard_auth_token')
    localStorage.removeItem('sunkguard_supabase_auth_token')
  },
}
