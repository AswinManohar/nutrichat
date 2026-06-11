import { useState } from 'react'
import { useMealStore } from '../stores/mealStore'
import { useDashboard, useLogMeal } from '../api/hooks'
import { ChatThread } from '../components/chat/ChatThread'
import { ChatInput } from '../components/chat/ChatInput'
import { DashboardPanel } from '../components/dashboard/DashboardPanel'
import { Trash2, ChevronDown, ChevronUp } from 'lucide-react'

export function ChatPage() {
  const { messages, conversationId, addMessage, setConversationId, clearMessages } = useMealStore()
  const { data: totals } = useDashboard()
  const logMealMutation = useLogMeal()
  const [mobileTotalsOpen, setMobileTotalsOpen] = useState(false)

  const handleSend = (text: string, imageB64?: string | null) => {
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
          }
        },
        onError: (err) => {
          addMessage({
            sender: 'agent',
            text: `Connection error: ${err.message}. Make sure the backend is running, then try again.`,
          })
          setConversationId(null)
        },
      }
    )
  }

  const handleClearChat = () => {
    if (window.confirm('Start a new conversation? This resets your active meal logging thread.')) {
      clearMessages()
    }
  }

  return (
    <div className="flex-1 flex flex-col md:flex-row h-screen overflow-hidden bg-surface">
      {/* Chat column */}
      <div className="flex-1 flex flex-col h-full md:border-r md:border-sand-border overflow-hidden relative">
        {/* Header */}
        <header className="px-5 md:px-6 h-16 flex items-center justify-between glass-header sticky top-0 z-10 border-b border-sand-border">
          <div>
            <h1 className="font-display text-lg text-sage-deep leading-tight">Næring</h1>
            <p className="text-[11px] text-muted">Log meals or ask about your nutrition</p>
          </div>
          <button
            onClick={handleClearChat}
            disabled={messages.length === 0}
            className="press w-9 h-9 rounded-full text-muted hover:text-danger hover:bg-container flex items-center justify-center disabled:opacity-30"
            title="Clear chat thread"
          >
            <Trash2 className="w-4 h-4" strokeWidth={1.75} />
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

        <ChatThread messages={messages} onAction={handleSend} isLoading={logMealMutation.isPending} />
        <ChatInput onSend={handleSend} isLoading={logMealMutation.isPending} />
      </div>

      {/* Dashboard column (desktop) */}
      <div className="hidden md:block w-96 h-full overflow-hidden flex-shrink-0 bg-surface">
        <DashboardPanel />
      </div>
    </div>
  )
}
