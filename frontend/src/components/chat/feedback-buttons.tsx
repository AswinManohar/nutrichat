import { useState } from 'react'

import { ThumbsDown, ThumbsUp } from 'lucide-react'

import { useCoachingFeedback } from '../../hooks/use-coaching-feedback'

interface FeedbackButtonsProps {
  responseId: string
}

type FeedbackState = 'idle' | 'submitting' | 'up' | 'down'

const ERROR_TEXT = "Couldn't send feedback. Try again."

/**
 * Thumbs up / down under a coaching reply. Up posts immediately. Down posts
 * immediately, then offers a one-line optional comment that posts again with
 * the same rating. Once rated, both buttons stay disabled.
 */
export function FeedbackButtons({ responseId }: FeedbackButtonsProps) {
  const feedback = useCoachingFeedback()
  const [state, setState] = useState<FeedbackState>('idle')
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const [sentComment, setSentComment] = useState(false)
  const [sendingComment, setSendingComment] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rated = state === 'up' || state === 'down'
  const busy = state === 'submitting' || sendingComment

  const rate = async (rating: 'up' | 'down') => {
    setState('submitting')
    setError(null)
    try {
      await feedback.mutateAsync({ responseId, rating })
      setState(rating)
      setShowComment(rating === 'down')
    } catch {
      setState('idle')
      setError(ERROR_TEXT)
    }
  }

  const sendComment = async () => {
    // A second click (or Enter) while the first request is still in flight
    // would post the same comment twice.
    if (busy) return
    const trimmed = comment.trim()
    if (!trimmed) {
      setShowComment(false)
      return
    }
    setError(null)
    setSendingComment(true)
    try {
      await feedback.mutateAsync({ responseId, rating: 'down', comment: trimmed })
      setShowComment(false)
      setSentComment(true)
    } catch {
      setError(ERROR_TEXT)
    } finally {
      setSendingComment(false)
    }
  }

  const iconClass = (active: boolean) =>
    `press rounded-full p-1.5 border transition-colors disabled:cursor-default ${
      active
        ? 'bg-container border-sage text-sage-deep'
        : 'border-transparent text-muted hover:text-ink hover:border-sand-border disabled:opacity-60'
    }`

  return (
    <div className="ml-7 flex flex-col gap-1.5">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Helpful"
          onClick={() => rate('up')}
          disabled={rated || busy}
          className={iconClass(state === 'up')}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label="Not helpful"
          onClick={() => rate('down')}
          disabled={rated || busy}
          className={iconClass(state === 'down')}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
        </button>
        {sentComment && <span className="text-[12px] text-muted">Thanks for the feedback.</span>}
        {error && (
          <span role="alert" className="text-[12px] text-red-600">
            {error}
          </span>
        )}
      </div>
      {showComment && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={comment}
            maxLength={500}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void sendComment()
            }}
            placeholder="What was off? (optional)"
            className="flex-1 bg-sand border border-sand-border rounded-full px-3 py-1.5 text-[13px] text-ink placeholder:text-muted/70 focus:outline-none focus:border-sage"
          />
          <button
            type="button"
            onClick={() => void sendComment()}
            disabled={busy}
            className="press text-[13px] font-medium text-sage-deep px-2.5 py-1.5 rounded-full border border-sand-border hover:border-sage disabled:opacity-60 disabled:cursor-default"
          >
            Send
          </button>
        </div>
      )}
    </div>
  )
}
