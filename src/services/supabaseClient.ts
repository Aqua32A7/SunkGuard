import { createClient, type SupabaseClient } from '@supabase/supabase-js'

// Environment variables for Supabase (configured in .env as VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY)
const rawUrl = (import.meta.env.VITE_SUPABASE_URL || '').trim()
const rawKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim()

export const isSupabaseConfigured = (): boolean => {
  return Boolean(
    rawUrl &&
    rawKey &&
    !rawUrl.includes('your-project') &&
    !rawKey.includes('your-anon')
  )
}

// Initialize official Supabase client with standard session persistence
export const supabase: SupabaseClient = createClient(
  rawUrl || 'https://placeholder.supabase.co',
  rawKey || 'placeholder-anon-key',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: 'sunkguard_supabase_auth_token',
    },
  }
)
