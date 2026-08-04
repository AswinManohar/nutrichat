import { create } from 'zustand'
import { supabase } from '../lib/supabase'

interface UserSession {
  id: string;
  email: string;
  name?: string;
}

interface AuthState {
  user: UserSession | null;
  token: string | null;
  isBypassed: boolean;
  debugUserId: string;
  isLoading: boolean;
  setUser: (user: UserSession | null) => void;
  setToken: (token: string | null) => void;
  initialize: () => Promise<void>;
  signOut: () => Promise<void>;
  enableBypass: (userId?: string) => void;
  disableBypass: () => void;
}

// Default developer ID for testing/bypassing auth
const DEFAULT_DEBUG_USER_ID = '00000000-0000-0000-0000-000000000000'

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: null,
  isBypassed: localStorage.getItem('auth_bypass') === 'true',
  debugUserId: localStorage.getItem('debug_user_id') || DEFAULT_DEBUG_USER_ID,
  isLoading: true,

  setUser: (user) => set({ user }),
  setToken: (token) => set({ token }),

  initialize: async () => {
    set({ isLoading: true })
    
    // Check if bypass is active
    if (get().isBypassed) {
      set({
        user: {
          id: get().debugUserId,
          email: 'developer@mealsy.local',
          name: 'Developer Mode',
        },
        token: 'dev-bypass-token',
        isLoading: false,
      })
      return
    }

    try {
      // Check current session from Supabase
      const { data: { session } } = await supabase.auth.getSession()
      if (session) {
        set({
          user: {
            id: session.user.id,
            email: session.user.email || '',
            name: session.user.user_metadata?.full_name || '',
          },
          token: session.access_token,
        })
      }
    } catch (error) {
      console.warn('Supabase auth initialization failed, check your connection/config.', error)
    } finally {
      set({ isLoading: false })
    }

    // Subscribe to auth state updates
    supabase.auth.onAuthStateChange((_event, session) => {
      if (get().isBypassed) return // Skip if bypassed

      if (session) {
        set({
          user: {
            id: session.user.id,
            email: session.user.email || '',
            name: session.user.user_metadata?.full_name || '',
          },
          token: session.access_token,
        })
      } else {
        set({ user: null, token: null })
      }
    })
  },

  signOut: async () => {
    set({ isLoading: true })
    if (get().isBypassed) {
      localStorage.removeItem('auth_bypass')
      set({
        user: null,
        token: null,
        isBypassed: false,
        isLoading: false,
      })
      return
    }

    try {
      await supabase.auth.signOut()
    } catch (error) {
      console.error('Sign out error', error)
    } finally {
      set({ user: null, token: null, isLoading: false })
    }
  },

  enableBypass: (userId) => {
    const targetId = userId || DEFAULT_DEBUG_USER_ID
    localStorage.setItem('auth_bypass', 'true')
    localStorage.setItem('debug_user_id', targetId)
    set({
      isBypassed: true,
      debugUserId: targetId,
      token: 'dev-bypass-token',
      user: {
        id: targetId,
        email: 'developer@mealsy.local',
        name: 'Developer Mode',
      },
    })
  },

  disableBypass: () => {
    localStorage.removeItem('auth_bypass')
    set({
      isBypassed: false,
      user: null,
      token: null,
    })
    get().initialize()
  },
}))
