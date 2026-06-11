import { create } from 'zustand'
import type { MealItem } from '../api/types'

export interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
  paused?: boolean;
  items?: MealItem[];
  imageB64?: string; // stored to display in the bubble if desired
}

interface MealStoreState {
  messages: ChatMessage[];
  conversationId: string | null;
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => ChatMessage;
  updateLastAgentMessage: (updates: Partial<ChatMessage>) => void;
  setConversationId: (id: string | null) => void;
  clearMessages: () => void;
}

export const useMealStore = create<MealStoreState>((set) => ({
  messages: [],
  conversationId: null,

  addMessage: (msg) => {
    const newMsg: ChatMessage = {
      ...msg,
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
    }
    set((state) => ({
      messages: [...state.messages, newMsg],
    }))
    return newMsg
  },

  updateLastAgentMessage: (updates) => {
    set((state) => {
      const reversed = [...state.messages].reverse()
      const lastAgentIdx = reversed.findIndex((m) => m.sender === 'agent')
      if (lastAgentIdx !== -1) {
        const actualIdx = state.messages.length - 1 - lastAgentIdx
        const updatedMessages = [...state.messages]
        updatedMessages[actualIdx] = {
          ...updatedMessages[actualIdx],
          ...updates,
        }
        return { messages: updatedMessages }
      }
      return {}
    })
  },

  setConversationId: (id) => set({ conversationId: id }),

  clearMessages: () => set({ messages: [], conversationId: null }),
}))
