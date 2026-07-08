import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ChatMessage } from '../../stores/mealStore'
import type { LogItemInput, MealCategory } from '../../api/types'
import { Check } from 'lucide-react'
import { ConfirmationCard } from './ConfirmationCard'
import { MascotSprite } from '../mascot/MascotSprite'
import { MascotGreeting } from '../mascot/MascotGreeting'

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
  onAction: (text: string, mealType?: MealCategory) => void
  onConfirmLog: (items: LogItemInput[], mealType: MealCategory, portion: number) => void
  onCancel: () => void
  onDismissCard: () => void
  onDecompose: () => void
  onCombine: () => void
  isLoading: boolean
}

/** Compact one-line stand-in for a confirmation card whose turn has ended. */
function CollapsedCard({ msg }: { msg: ChatMessage }) {
  if (msg.resolved === 'discarded') {
    // Cancelled / all-items-removed card — no check icon, no names/kcal.
    return (
      <div className="self-start flex items-center gap-2 text-[12px] text-muted/70 italic rise-in">
        <span className="truncate max-w-[60vw] md:max-w-md">Discarded — nothing logged.</span>
      </div>
    )
  }
  const names =
    msg.resolvedLabel ??
    [...new Set((msg.items ?? []).map((i) => i.source_dish || i.food_name))].join(', ')
  const kcal =
    msg.resolvedKcal ?? Math.round((msg.items ?? []).reduce((a, i) => a + i.kcal, 0))

  // Superseded card: the user moved on without ever confirming, so nothing was
  // logged. Stamp it "Not logged" with muted, struck-through text so it can't
  // be mistaken for a logged meal's summary.
  if (msg.resolved !== 'logged') {
    return (
      <div className="self-start flex items-center gap-2 text-[12px] text-muted/70 rise-in">
        <span className="flex-shrink-0 rounded-full border border-sand-border bg-sand px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted">
          Not logged
        </span>
        <span className="truncate max-w-[55vw] md:max-w-md line-through decoration-muted/40">
          {names}
          {kcal > 0 ? ` · ${kcal.toLocaleString()} kcal` : ''}
        </span>
      </div>
    )
  }

  // Logged — keep the confirmed look with the sage check.
  return (
    <div className="self-start flex items-center gap-2 text-[12px] text-muted rise-in">
      <span className="flex items-center justify-center w-4 h-4 rounded-full bg-sage/15 text-sage-deep">
        <Check className="w-2.5 h-2.5" strokeWidth={3} />
      </span>
      <span className="truncate max-w-[60vw] md:max-w-md">
        Logged: <span className="text-ink-soft font-medium">{names}</span>
        {kcal > 0 ? ` · ${kcal.toLocaleString()} kcal` : ''}
      </span>
    </div>
  )
}

const SUGGESTIONS = [
  { label: 'Eggs & toast', text: 'breakfast was 2 scrambled eggs and a slice of whole wheat toast' },
  { label: 'Chicken salad', text: 'lunch was a grilled chicken salad with vinaigrette' },
  { label: 'How much protein?', text: 'how much protein have I had today?' },
  { label: 'What to eat tonight?', text: 'what should I eat for dinner to hit my fiber goal?' },
]

function TypingIndicator() {
  return (
    <div className="self-start rise-in pl-1">
      <MascotSprite size={14} variant="jump" />
    </div>
  )
}

export function ChatThread({
  messages,
  onAction,
  onConfirmLog,
  onCancel,
  onDismissCard,
  onDecompose,
  onCombine,
  isLoading,
}: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 flex flex-col gap-5 scroll-smooth">
      {messages.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center max-w-md mx-auto gap-6 rise-stagger">
          <MascotGreeting show={messages.length === 0} />
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
          <p className="text-[11px] text-muted/60" style={{ '--i': 2 } as React.CSSProperties}>
            Describe a meal to log it, or ask anything about your nutrition.
          </p>
        </div>
      ) : (
        messages.map((msg, idx) => {
          const isUser = msg.sender === 'user'
          const hasItems = !isUser && !!msg.items && msg.items.length > 0
          const isLast = idx === messages.length - 1
          // A card is only interactive while it's the live turn: paused, last,
          // and not yet logged. Otherwise it collapses to a one-line summary,
          // so a stale card can't fire edits into a closed conversation.
          const interactive = hasItems && !!msg.paused && isLast && !msg.resolved
          if (hasItems && !interactive) {
            return <CollapsedCard key={msg.id} msg={msg} />
          }
          const hasCard = interactive
          return (
            <div
              key={msg.id}
              className={`rise-in flex flex-col gap-1.5 max-w-[88%] md:max-w-[75%] ${
                isUser ? 'self-end items-end' : 'self-start items-start'
              }`}
            >
              <div className={isUser ? '' : 'flex items-start gap-2.5 w-full'}>
                {!isUser && (
                  <div className="w-5 h-5 rounded-full bg-sage-forest flex-shrink-0 mt-1" aria-hidden="true" />
                )}
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
              </div>

              {hasCard && (
                <ConfirmationCard
                  items={msg.items!}
                  onAction={onAction}
                  onConfirmLog={onConfirmLog}
                  onCancel={onCancel}
                  onDismiss={onDismissCard}
                  onDecompose={onDecompose}
                  onCombine={onCombine}
                  isLoading={isLoading}
                />
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
