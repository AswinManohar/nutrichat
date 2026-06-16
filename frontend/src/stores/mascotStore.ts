// frontend/src/stores/mascotStore.ts
import { create } from 'zustand'

function loadEnabled(): boolean {
  try {
    return localStorage.getItem('nutrichat-mascot-enabled') !== 'false'
  } catch {
    return true
  }
}

interface MascotState {
  enabled: boolean
  setEnabled: (v: boolean) => void
}

export const useMascotStore = create<MascotState>((set) => ({
  enabled: loadEnabled(),
  setEnabled: (enabled) => {
    try {
      localStorage.setItem('nutrichat-mascot-enabled', String(enabled))
    } catch {}
    set({ enabled })
  },
}))
