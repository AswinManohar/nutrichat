import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMealStore } from '../stores/mealStore'
import { useDashboard, useDeleteMealLog, usePendingNudge, useAckPendingNudge, useGoals } from '../api/hooks'
import type { MealCategory } from '../api/types'
import { ChatThread } from '../components/chat/ChatThread'
import { ChatInput } from '../components/chat/ChatInput'
import { ChatTodayPanel } from '../components/dashboard/ChatTodayPanel'

const UNDO_WINDOW_S = 30

export function ChatPage() {
  const {
    messages,
    conversationId,
    isProcessing,
    confirmError,
    lastLoggedMealId,
    addMessage,
    setConversationId,
    clearMessages,
    logToApi,
    logItemsDirect,
    discardCard,
    cancelCard,
    consumeLastLoggedMealId,
  } = useMealStore()
  const { data: totals } = useDashboard()
  const { data: goals } = useGoals()
  const deleteMealLogMutation = useDeleteMealLog()
  const [undoMealId, setUndoMealId] = useState<string | null>(null)
  const [undoSecondsLeft, setUndoSecondsLeft] = useState(UNDO_WINDOW_S)
  const undoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
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

  // Pick up the meal_id left by logToApi even if the user navigated away mid-flight.
  useEffect(() => {
    if (!lastLoggedMealId) return
    const id = consumeLastLoggedMealId()
    if (id) startUndoWindow(id)
  }, [lastLoggedMealId, consumeLastLoggedMealId, startUndoWindow])

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

    logToApi({
      user_input: text,
      conversation_id: activeThreadId,
      image_b64: imageB64 || null,
      meal_type: mealType ?? null,
    })
  }

  // All food items removed from the confirmation card → drop the card silently.
  // Stamps the card discarded and orphans the paused thread (no backend call),
  // so the next message starts a fresh one.
  const handleDismissCard = useCallback(() => {
    discardCard()
  }, [discardCard])

  const handleDecompose = () => {
    if (!conversationId) return
    logToApi({ user_input: 'break into ingredients', conversation_id: conversationId, action: 'decompose' })
  }

  const handleCombine = () => {
    if (!conversationId) return
    logToApi({ user_input: 'log as single item', conversation_id: conversationId, action: 'combine' })
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
    <div className="flex h-screen overflow-hidden bg-surface">
      {/* Chat column */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative min-w-0">
        {/* Header */}
        <header className="px-5 h-14 flex items-center justify-between border-b border-sand-border flex-shrink-0 bg-surface">
          <div className="flex items-baseline gap-2">
            <span className="font-display text-[17px] font-bold text-ink leading-tight">Today</span>
            <span className="text-[13px] text-muted">
              {'· '}
              {new Intl.DateTimeFormat('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
              }).format(new Date())}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {totals && (
              <span className="text-[13px] font-medium text-sage-deep border border-sage-deep/40 rounded-full px-3 py-1 tabular-nums">
                {Math.round(totals.kcal).toLocaleString()} / {(goals?.kcal_goal ?? 2000).toLocaleString()} kcal
              </span>
            )}
            <button
              onClick={handleClearChat}
              disabled={messages.length === 0}
              className="press text-[12px] font-medium text-muted/60 hover:text-danger disabled:opacity-30 transition-colors"
              title="New chat"
            >
              New chat
            </button>
          </div>
        </header>

        <ChatThread
          messages={messages}
          onAction={(text, mealType) => handleSend(text, null, mealType)}
          onConfirmLog={logItemsDirect}
          onCancel={cancelCard}
          onDismissCard={handleDismissCard}
          onDecompose={handleDecompose}
          onCombine={handleCombine}
          isLoading={isProcessing}
          confirmError={confirmError}
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

        <ChatInput onSend={handleSend} isLoading={isProcessing} />
      </div>

      {/* Right panel (desktop only) */}
      <div className="hidden md:block w-[320px] flex-shrink-0 h-full border-l border-sand-border overflow-hidden bg-surface">
        <ChatTodayPanel />
      </div>
    </div>
  )
}
