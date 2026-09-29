import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://placeholder-project.supabase.co'
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || 'placeholder-anon-key'

// Create a Supabase client. If credentials are placeholders, Supabase
// operations (including authentication) will fail.
export const supabase = createClient(supabaseUrl, supabaseAnonKey)
