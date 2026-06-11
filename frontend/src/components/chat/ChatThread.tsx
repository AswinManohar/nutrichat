import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../../stores/mealStore'
import { ConfirmationCard } from './ConfirmationCard'

interface ChatThreadProps {
  messages: ChatMessage[]
  onAction: (text: string) => void
  isLoading: boolean
}

const SUGGESTIONS = [
  { label: 'Eggs & toast', text: 'breakfast was 2 scrambled eggs and a slice of whole wheat toast' },
  { label: 'Chicken salad', text: 'lunch was a grilled chicken salad with vinaigrette' },
  { label: 'Oatmeal & coffee', text: 'breakfast was black coffee and a bowl of oatmeal' },
  { label: 'How much protein today?', text: 'how much protein have I had today?' },
]

function TypingIndicator() {
  return (
    <div className="self-start rise-in">
      <div className="card-sand rounded-2xl px-4 py-3.5 flex items-center gap-1.5">
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '0ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '150ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}

export function ChatThread({ messages, onAction, isLoading }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 flex flex-col gap-5 scroll-smooth">
      {messages.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center max-w-md mx-auto gap-6 rise-stagger">
          <div style={{ '--i': 0 } as React.CSSProperties}>
            <h3 className="font-display text-[28px] text-sage-deep">What did you eat?</h3>
            <p className="text-[14px] text-muted mt-2 leading-relaxed">
              Describe a meal in one sentence, snap a photo, or ask about your day —
              "how much fiber so far?"
            </p>
          </div>
          <div className="flex flex-wrap gap-2 justify-center" style={{ '--i': 1 } as React.CSSProperties}>
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => onAction(s.text)}
                disabled={isLoading}
                className="press bg-sand border border-sand-border hover:border-sage text-[13px] text-ink-soft px-3.5 py-2 rounded-full disabled:opacity-50"
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        messages.map((msg) => {
          const isUser = msg.sender === 'user'
          const hasCard = !isUser && msg.paused && msg.items && msg.items.length > 0
          return (
            <div
              key={msg.id}
              className={`rise-in flex flex-col gap-1.5 max-w-[88%] md:max-w-[75%] ${
                isUser ? 'self-end items-end' : 'self-start items-start'
              }`}
            >
              <div
                className={
                  isUser
                    ? 'bg-sage text-white rounded-2xl rounded-br-md px-4 py-3'
                    : 'card-sand rounded-2xl rounded-bl-md px-4 py-3.5'
                }
              >
                {isUser && msg.imageB64 && (
                  <div className="w-48 max-w-full rounded-lg overflow-hidden mb-2.5">
                    <img
                      src={`data:image/jpeg;base64,${msg.imageB64}`}
                      alt="Submitted food"
                      className="w-full h-auto object-cover max-h-48"
                    />
                  </div>
                )}
                <p
                  className={`text-[14px] leading-relaxed whitespace-pre-wrap ${
                    isUser ? '' : 'text-ink-soft'
                  }`}
                >
                  {hasCard ? 'Here is what I found — confirm, edit, or cancel.' : msg.text}
                </p>
              </div>

              {hasCard && (
                <ConfirmationCard items={msg.items!} onAction={onAction} isLoading={isLoading} />
              )}

              <span className="text-[10px] text-muted px-1">
                {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          )
        })
      )}

      {isLoading && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  )
}
