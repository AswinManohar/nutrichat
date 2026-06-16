import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ChatMessage } from '../../stores/mealStore'
import { ConfirmationCard } from './ConfirmationCard'
import { MascotSprite } from '../mascot/MascotSprite'

const MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="text-muted">{children}</em>,
  ul: ({ children }) => <ul className="my-1.5 ml-4 list-disc space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 ml-4 list-decimal space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="leading-snug">{children}</li>,
  h1: ({ children }) => <h4 className="font-display text-[15px] font-bold mt-2 mb-1">{children}</h4>,
  h2: ({ children }) => <h4 className="font-display text-[15px] font-bold mt-2 mb-1">{children}</h4>,
  h3: ({ children }) => <h3 className="font-display text-[14px] font-bold mt-2 mb-1">{children}</h3>,
  h4: ({ children }) => <h4 className="font-display text-[14px] font-bold mt-2 mb-1">{children}</h4>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-sage underline">
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="bg-sand-border/60 rounded px-1 py-0.5 text-[13px]">{children}</code>
  ),
}

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
      <div
        className="card-sand rounded-2xl overflow-hidden flex items-end justify-center"
        style={{ width: 80, height: 96, padding: '8px' }}
      >
        <MascotSprite size={14} variant="jump" />
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
                {isUser ? (
                  <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                ) : (
                  <div className="text-[14px] leading-relaxed text-ink-soft">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                      {hasCard ? 'Here is what I found — confirm, edit, or cancel.' : msg.text}
                    </ReactMarkdown>
                  </div>
                )}
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
