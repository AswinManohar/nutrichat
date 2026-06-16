import { create } from 'zustand'

function loadEnabled(): boolean {
  try {
    return localStorage.getItem('nutrichat-mascot-enabled') !== 'false'
  } catch (error: unknown) {
    console.error('Failed to load mascot preference:', error)
    return true
  }
}

interface MascotState {
  enabled: boolean
  setEnabled: (enabled: boolean) => void
}

export const useMascotStore = create<MascotState>((set) => ({
  enabled: loadEnabled(),
  setEnabled: (enabled: boolean) => {
    try {
      localStorage.setItem('nutrichat-mascot-enabled', String(enabled))
    } catch (error: unknown) {
      console.error('Failed to save mascot preference:', error)
    }
    set({ enabled })
  },
}))
