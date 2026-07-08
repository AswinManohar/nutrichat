import { create } from 'zustand'
import { apiClient } from '../api/client'
import { queryClient } from '../api/queryClient'
import type {
  LogItemInput,
  LogMealRequest,
  LogMealResponse,
  LogMyMealResponse,
  MealCategory,
  MealItem,
} from '../api/types'

export interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
  paused?: boolean;
  items?: MealItem[];
  imageB64?: string;
  // Set once the card's turn concludes — flips it from an interactive card to
  // a collapsed one-line summary ('logged') or a muted discard line.
  resolved?: 'logged' | 'discarded';
  resolvedLabel?: string;
  resolvedKcal?: number;
}

/** Stamp the most recent still-interactive card as resolved (collapses it). */
function stampResolvedCard(
  messages: ChatMessage[],
  kind: 'logged' | 'discarded',
  explicit?: { label: string; kcal: number },
): ChatMessage[] {
  const msgs = [...messages]
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    const m = msgs[i]
    if (m.sender === 'agent' && m.items?.length && m.paused && !m.resolved) {
      if (kind === 'discarded') {
        // Keep items — ChatThread only renders a collapsed card when items
        // exist; the discarded variant shows no names/kcal anyway.
        msgs[i] = { ...m, paused: false, resolved: 'discarded' }
        break
      }
      const label =
        explicit?.label ??
        [...new Set(m.items.map((it) => it.source_dish || it.food_name))].join(', ')
      const kcal = explicit?.kcal ?? Math.round(m.items.reduce((a, it) => a + it.kcal, 0))
      msgs[i] = {
        ...m,
        paused: false,
        resolved: 'logged',
        resolvedLabel: label,
        resolvedKcal: kcal,
      }
      break
    }
  }
  return msgs
}

interface MealStoreState {
  messages: ChatMessage[];
  conversationId: string | null;
  isProcessing: boolean;
  // Set to the meal_id on a successful log; cleared by calling consumeLastLoggedMealId().
  lastLoggedMealId: string | null;

  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => ChatMessage;
  updateLastAgentMessage: (updates: Partial<ChatMessage>) => void;
  setConversationId: (id: string | null) => void;
  clearMessages: () => void;
  // Fires the /meals/log request and handles the response in the store so the
  // result is never lost when the user navigates away from ChatPage mid-flight.
  logToApi: (payload: LogMealRequest) => Promise<void>;
  // Logs the confirmation card's final item set directly (no LLM) — used after
  // local removals / quantity edits.
  logItemsDirect: (
    items: LogItemInput[],
    mealType: MealCategory,
    portion: number,
  ) => Promise<void>;
  // Returns and clears lastLoggedMealId atomically (for the undo timer).
  consumeLastLoggedMealId: () => string | null;
  // Silently discards the active confirmation card (no backend call) — used
  // when the user removes every item from the card.
  discardCard: () => void;
  // Discards the active card, then fire-and-forgets a "cancel" to the paused
  // graph thread so its checkpoint closes cleanly. No bubbles either way.
  cancelCard: () => void;
}

export const useMealStore = create<MealStoreState>((set, get) => ({
  messages: [],
  conversationId: null,
  isProcessing: false,
  lastLoggedMealId: null,

  addMessage: (msg) => {
    const newMsg: ChatMessage = {
      ...msg,
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
    }
    set((state) => ({ messages: [...state.messages, newMsg] }))
    return newMsg
  },

  updateLastAgentMessage: (updates) => {
    set((state) => {
      const reversed = [...state.messages].reverse()
      const lastAgentIdx = reversed.findIndex((m) => m.sender === 'agent')
      if (lastAgentIdx !== -1) {
        const actualIdx = state.messages.length - 1 - lastAgentIdx
        const updatedMessages = [...state.messages]
        updatedMessages[actualIdx] = { ...updatedMessages[actualIdx], ...updates }
        return { messages: updatedMessages }
      }
      return {}
    })
  },

  setConversationId: (id) => set({ conversationId: id }),

  clearMessages: () => set({ messages: [], conversationId: null }),

  logToApi: async (payload) => {
    set({ isProcessing: true })
    try {
      const data: LogMealResponse = await apiClient.post<LogMealResponse>('/meals/log', payload)
      get().addMessage({
        sender: 'agent',
        text: data.message,
        paused: data.paused,
        items: data.items,
      })
      if (!data.paused) {
        set({ conversationId: null })
        if (data.meal_id) {
          set((state) => ({ messages: stampResolvedCard(state.messages, 'logged') }))
          set({ lastLoggedMealId: data.meal_id })
        }
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'today'] })
      }
    } catch {
      get().addMessage({
        sender: 'agent',
        text: "Couldn't reach the server — check your connection and try again.",
      })
      set({ conversationId: null })
    } finally {
      set({ isProcessing: false })
    }
  },

  logItemsDirect: async (items, mealType, portion) => {
    set({ isProcessing: true })
    try {
      const data = await apiClient.post<LogMyMealResponse>('/meals/log-items', {
        meal_type: mealType,
        portion,
        items,
      })
      const label = [
        ...new Set(items.map((it) => it.source_dish || it.food_name)),
      ].join(', ')
      // Collapse the source card to a logged summary, then post the reply.
      set((state) => ({
        messages: stampResolvedCard(state.messages, 'logged', {
          label,
          kcal: Math.round(data.kcal),
        }),
      }))
      get().addMessage({ sender: 'agent', text: data.message })
      set({ conversationId: null, lastLoggedMealId: data.meal_id })
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'today'] })
    } catch {
      get().addMessage({
        sender: 'agent',
        text: "Couldn't log that — check your connection and try again.",
      })
    } finally {
      set({ isProcessing: false })
    }
  },

  consumeLastLoggedMealId: () => {
    const id = get().lastLoggedMealId
    set({ lastLoggedMealId: null })
    return id
  },

  discardCard: () => {
    set((state) => ({ messages: stampResolvedCard(state.messages, 'discarded') }))
    set({ conversationId: null })
  },

  cancelCard: () => {
    // Capture the thread id before discardCard clears it — the fire-and-forget
    // "cancel" needs it to reach the paused graph's cancel node.
    const conversationId = get().conversationId
    get().discardCard()
    if (conversationId) {
      apiClient
        .post('/meals/log', { user_input: 'cancel', conversation_id: conversationId })
        .catch(() => {
          // Worst case: an orphaned thread, already an accepted pattern. Swallow.
        })
    }
  },
}))
