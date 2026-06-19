import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMealStore } from '../stores/mealStore'
import { useDashboard, useLogMeal, useDeleteMealLog, usePendingNudge, useAckPendingNudge } from '../api/hooks'
import type { MealCategory } from '../api/types'
import { useResizablePanel } from '../hooks/use-resizable-panel'
import { ChatThread } from '../components/chat/ChatThread'
import { ChatInput } from '../components/chat/ChatInput'
import { DashboardPanel } from '../components/dashboard/DashboardPanel'
import { Trash2, ChevronDown, ChevronUp } from 'lucide-react'

const UNDO_WINDOW_S = 25

export function ChatPage() {
  const {
    messages,
    conversationId,
    addMessage,
    updateLastAgentMessage,
    setConversationId,
    clearMessages,
  } = useMealStore()
  const { data: totals } = useDashboard()
  const logMealMutation = useLogMeal()
  const deleteMealLogMutation = useDeleteMealLog()
  const [mobileTotalsOpen, setMobileTotalsOpen] = useState(false)
  const [undoMealId, setUndoMealId] = useState<string | null>(null)
  const [undoSecondsLeft, setUndoSecondsLeft] = useState(UNDO_WINDOW_S)
  const undoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { width: dashboardWidth, onPointerDown: onResizerPointerDown } = useResizablePanel()
  const { data: pendingNudge } = usePendingNudge()
  const ackNudgeMutation = useAckPendingNudge()
  const location = useLocation()
  const navigate = useNavigate()
  const loggedFromNavRef = useRef(false)

  useEffect(() => {
    if (!pendingNudge?.summary_text || conversationId !== null) return
    addMessage({ sender: 'agent', text: pendingNudge.summary_text })
    ackNudgeMutation.mutate()
    // Only fire once per pending summary; ack makes subsequent fetches return null.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingNudge?.summary_text])

  const startUndoWindow = useCallback((mealId: string) => {
    if (undoTimerRef.current) clearInterval(undoTimerRef.current)
    setUndoMealId(mealId)
    setUndoSecondsLeft(UNDO_WINDOW_S)
    undoTimerRef.current = setInterval(() => {
      setUndoSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(undoTimerRef.current!)
          setUndoMealId(null)
          return UNDO_WINDOW_S
        }
        return s - 1
      })
    }, 1000)
  }, [])

  const dismissUndo = useCallback(() => {
    if (undoTimerRef.current) clearInterval(undoTimerRef.current)
    setUndoMealId(null)
    setUndoSecondsLeft(UNDO_WINDOW_S)
  }, [])

  const handleUndo = useCallback(() => {
    if (!undoMealId) return
    dismissUndo()
    deleteMealLogMutation.mutate(undoMealId, {
      onSuccess: () => addMessage({ sender: 'agent', text: 'Done — meal removed.' }),
      onError: () => addMessage({ sender: 'agent', text: "Couldn't undo — check your connection and try again." }),
    })
  }, [undoMealId, deleteMealLogMutation, dismissUndo, addMessage])

  const handleSend = (text: string, imageB64?: string | null, mealType?: MealCategory) => {
    addMessage({
      sender: 'user',
      text: text || (imageB64 ? 'Uploaded an image' : ''),
      imageB64: imageB64 || undefined,
    })

    let activeThreadId = conversationId
    if (!activeThreadId) {
      activeThreadId = crypto.randomUUID()
      setConversationId(activeThreadId)
    }

    logMealMutation.mutate(
      {
        user_input: text,
        conversation_id: activeThreadId,
        image_b64: imageB64 || null,
        meal_type: mealType ?? null,
      },
      {
        onSuccess: (data) => {
          addMessage({
            sender: 'agent',
            text: data.message,
            paused: data.paused,
            items: data.items,
          })
          // Not paused → meal logged/cancelled/coaching answer. New thread next time.
          if (!data.paused) {
            setConversationId(null)
            if (data.meal_id) startUndoWindow(data.meal_id)
          }
        },
        onError: (err) => {
          addMessage({
            sender: 'agent',
            text: "Couldn't reach the server — check your connection and try again.",
          })
          setConversationId(null)
        },
      }
    )
  }

  // All food items removed from the confirmation card → drop the card silently.
  // No backend call: resetting conversationId orphans the paused thread, so the
  // next message starts a fresh one. (Stable store actions; safe as a callback.)
  const handleDismissCard = useCallback(() => {
    updateLastAgentMessage({ paused: false, items: [], text: 'Discarded — nothing logged.' })
    setConversationId(null)
  }, [updateLastAgentMessage, setConversationId])

  // "Break into ingredients" → resume the paused thread with action=decompose.
  // No user bubble; the re-presented card replaces the message in place.
  const handleDecompose = () => {
    if (!conversationId) return
    logMealMutation.mutate(
      { user_input: 'break into ingredients', conversation_id: conversationId, action: 'decompose' },
      {
        onSuccess: (data) => {
          addMessage({
            sender: 'agent',
            text: data.message,
            paused: data.paused,
            items: data.items,
          })
          if (!data.paused) setConversationId(null)
        },
        onError: () => {
          addMessage({ sender: 'agent', text: "Couldn't break this down — try again." })
        },
      }
    )
  }

  // "Log as single item" → resume the paused thread with action=combine.
  // Collapses auto-decomposed ingredients back to their source dish.
  const handleCombine = () => {
    if (!conversationId) return
    logMealMutation.mutate(
      { user_input: 'log as single item', conversation_id: conversationId, action: 'combine' },
      {
        onSuccess: (data) => {
          addMessage({
            sender: 'agent',
            text: data.message,
            paused: data.paused,
            items: data.items,
          })
          if (!data.paused) setConversationId(null)
        },
        onError: () => {
          addMessage({ sender: 'agent', text: "Couldn't combine — try again." })
        },
      }
    )
  }

  // Explicit "Log" from the My Meals page navigates here with the meal name;
  // send it once so the backend auto-detects the saved meal and prefills.
  useEffect(() => {
    const name = (location.state as { logMeal?: string } | null)?.logMeal
    if (name && !loggedFromNavRef.current) {
      loggedFromNavRef.current = true
      navigate('.', { replace: true, state: null })
      handleSend(name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  const handleClearChat = () => {
    if (window.confirm('Start fresh? Your current conversation will be cleared.')) {
      clearMessages()
    }
  }

  return (
    <div className="flex-1 flex flex-col md:flex-row h-screen overflow-hidden bg-surface">
      {/* Chat column */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        {/* Header */}
        <header className="px-5 md:px-6 h-16 flex items-center justify-between glass-header sticky top-0 z-10 border-b border-sand-border">
          <div>
            <h1 className="font-display text-lg text-sage-deep leading-tight">Næring</h1>
            <p className="text-[11px] text-muted">Log meals or ask about your nutrition</p>
          </div>
          <button
            onClick={handleClearChat}
            disabled={messages.length === 0}
            className="press flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium text-muted hover:text-danger hover:bg-container disabled:opacity-30"
          >
            <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
            New chat
          </button>
        </header>

        {/* Mobile totals strip */}
        <div className="md:hidden border-b border-sand-border bg-surface z-10">
          <button
            onClick={() => setMobileTotalsOpen(!mobileTotalsOpen)}
            className="w-full px-5 py-2.5 flex items-center justify-between"
          >
            <span className="label-caps">Today</span>
            <span className="flex items-center gap-2 text-[13px] font-semibold text-sage-deep">
              {Math.round(totals?.kcal || 0)} kcal
              {mobileTotalsOpen ? (
                <ChevronUp className="w-3.5 h-3.5 text-muted" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5 text-muted" />
              )}
            </span>
          </button>
          {mobileTotalsOpen && (
            <div className="px-5 pb-3 grid grid-cols-3 gap-2 rise-in">
              {[
                { label: 'Protein', value: `${Math.round(totals?.protein_g || 0)}g` },
                { label: 'Fiber', value: `${Math.round(totals?.fiber_g || 0)}g` },
                { label: 'Meals', value: `${totals?.n_meals || 0}` },
              ].map((s) => (
                <div key={s.label} className="card-sand px-2 py-2 text-center">
                  <span className="label-caps block text-[9px]">{s.label}</span>
                  <span className="text-[13px] font-semibold text-ink-soft">{s.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <ChatThread
          messages={messages}
          onAction={(text, mealType) => handleSend(text, null, mealType)}
          onDismissCard={handleDismissCard}
          onDecompose={handleDecompose}
          onCombine={handleCombine}
          isLoading={logMealMutation.isPending}
        />

        {undoMealId && (
          <div className="px-4 pb-2 flex justify-center">
            <div className="flex items-center gap-2.5 bg-ink text-paper rounded-full px-4 py-2 text-[13px] shadow-md rise-in">
              <span className="text-paper/60">Meal logged</span>
              <span className="text-paper/30">·</span>
              <button
                type="button"
                onClick={handleUndo}
                className="font-semibold underline underline-offset-2 hover:text-sage-soft"
              >
                Undo
              </button>
              <span className="text-paper/40 tabular-nums w-5 text-right">{undoSecondsLeft}s</span>
            </div>
          </div>
        )}

        <ChatInput onSend={handleSend} isLoading={logMealMutation.isPending} />
      </div>

      {/* Drag handle (desktop) */}
      <div
        onPointerDown={onResizerPointerDown}
        className="hidden md:block w-1.5 flex-shrink-0 cursor-col-resize group relative z-10"
        title="Drag to resize"
      >
        <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-sand-border group-hover:bg-sage group-active:bg-sage transition-colors" />
      </div>

      {/* Dashboard column (desktop) */}
      <div
        className="hidden md:block h-full overflow-hidden flex-shrink-0 bg-surface"
        style={{ width: dashboardWidth }}
      >
        <DashboardPanel />
      </div>
    </div>
  )
}
