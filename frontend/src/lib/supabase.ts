import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://placeholder-project.supabase.co'
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || 'placeholder-anon-key'

// Create a Supabase client. If credentials are placeholders, Supabase operations will fail,
// but the app can still run in DEV_BYPASS_AUTH mode.
export const supabase = createClient(supabaseUrl, supabaseAnonKey)
