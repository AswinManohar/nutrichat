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
  isLoading: boolean;
  setUser: (user: UserSession | null) => void;
  setToken: (token: string | null) => void;
  initialize: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoading: true,

  setUser: (user) => set({ user }),
  setToken: (token) => set({ token }),

  initialize: async () => {
    set({ isLoading: true })

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
    try {
      await supabase.auth.signOut()
    } catch (error) {
      console.error('Sign out error', error)
    } finally {
      set({ user: null, token: null, isLoading: false })
    }
  },
}))
