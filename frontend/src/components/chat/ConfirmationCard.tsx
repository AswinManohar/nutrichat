import { useEffect, useRef, useState } from 'react'
import type { MealItem } from '../../api/types'
import { ChevronDown, Plus, Minus, X } from 'lucide-react'

interface ConfirmationCardProps {
  items: MealItem[]
  onAction: (text: string) => void
  onDismiss: () => void
  isLoading: boolean
}

const LOW_CONFIDENCE = 0.6

/**
 * Editable confirmation card for the paused meal-logging graph.
 * Quantity edits, candidate switches, and removals are sent back as
 * plain-text corrections — the backend re-resolves and re-presents.
 */
export function ConfirmationCard({ items, onAction, onDismiss, isLoading }: ConfirmationCardProps) {
  const [qtys, setQtys] = useState<number[]>(() => items.map((i) => i.qty_g))
  const [openCandidates, setOpenCandidates] = useState<number | null>(null)
  const [swaps, setSwaps] = useState<Record<number, string>>({})
  const [removed, setRemoved] = useState<Set<number>>(new Set())
  const [prevItems, setPrevItems] = useState(items)
  const dismissedRef = useRef(false)

  // Every visible item removed → drop the card from the chat (no backend call).
  // Computed before any early return so the hook below is unconditional.
  const allRemoved = items.length > 0 && removed.size >= items.length

  useEffect(() => {
    if (allRemoved && !dismissedRef.current) {
      dismissedRef.current = true
      onDismiss()
    }
  }, [allRemoved, onDismiss])

  // Reset edits when a new card arrives (React "adjust state during render")
  if (prevItems !== items) {
    setPrevItems(items)
    setQtys(items.map((i) => i.qty_g))
    setSwaps({})
    setRemoved(new Set())
    dismissedRef.current = false
    return null
  }

  if (qtys.length !== items.length) return null
  if (allRemoved) return null

  const visibleIndices = items.map((_, i) => i).filter((i) => !removed.has(i))

  // Live totals scale linearly with qty edits (nutrients are per-gram linear)
  const scaled = items.map((item, i) => {
    const scale = qtys[i] / item.qty_g
    return {
      kcal: item.kcal * scale,
      protein_g: item.protein_g * scale,
      carbs_g: item.carbs_g * scale,
      fat_g: item.fat_g * scale,
      fiber_g: item.fiber_g * scale,
    }
  })
  const total = (key: keyof (typeof scaled)[0]) =>
    visibleIndices.reduce((acc, i) => acc + scaled[i][key], 0)

  const corrections: string[] = []
  removed.forEach((i) => corrections.push(`remove ${items[i].food_name}`))
  items.forEach((item, i) => {
    if (removed.has(i)) return
    if (swaps[i]) corrections.push(`use ${swaps[i]} instead of ${item.food_name}`)
    if (Math.round(qtys[i]) !== Math.round(item.qty_g))
      corrections.push(`change ${item.food_name} to ${Math.round(qtys[i])}g`)
  })

  const setQty = (i: number, v: number) => {
    if (v <= 0 || Number.isNaN(v)) return
    setQtys((prev) => prev.map((q, idx) => (idx === i ? v : q)))
  }

  const removeItem = (i: number) => {
    setRemoved((prev) => new Set([...prev, i]))
    if (openCandidates === i) setOpenCandidates(null)
  }

  return (
    <div className="w-full max-w-xl card-sand p-4 md:p-5 flex flex-col gap-3 mt-1 rise-in">
      <div className="flex items-center justify-between pb-2 border-b border-sand-border">
        <h3 className="label-caps !text-sage-deep">Confirm meal</h3>
        <span className="text-[11px] text-muted">
          {visibleIndices.length} item{visibleIndices.length === 1 ? '' : 's'}
        </span>
      </div>

      {/* Items */}
      <div className="flex flex-col gap-2.5">
        {items.map((item, i) => {
          if (removed.has(i)) return null
          return (
            <div
              key={`${item.fdc_id}-${i}`}
              className="bg-paper rounded-xl border-l-4 border border-sand-border border-l-sage p-3.5 flex flex-col gap-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <h4 className="text-[14px] font-medium text-ink leading-snug truncate">
                    {swaps[i] ?? item.food_name}
                  </h4>
                  <p className="text-[11px] text-muted mt-0.5">
                    {Math.round(scaled[i].kcal)} kcal · {scaled[i].protein_g.toFixed(0)}g protein ·{' '}
                    {scaled[i].fiber_g.toFixed(0)}g fiber
                    {item.confidence < LOW_CONFIDENCE && !swaps[i] && !item.estimated && (
                      <span className="ml-1.5 text-warn font-semibold">· check match</span>
                    )}
                    {(item.estimated || item.source === 'LLM_ESTIMATE') && (
                      <span className="ml-1.5 text-muted font-semibold">
                        · ≈ estimated (not in USDA)
                      </span>
                    )}
                  </p>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  {/* Quantity stepper */}
                  <div className="flex items-center gap-1 bg-container rounded-full px-1 py-0.5">
                    <button
                      type="button"
                      onClick={() => setQty(i, Math.max(5, Math.round(qtys[i]) - 25))}
                      className="press cursor-pointer w-6 h-6 rounded-full flex items-center justify-center text-muted hover:text-ink"
                    >
                      <Minus className="w-3 h-3" />
                    </button>
                    <input
                      type="number"
                      value={Math.round(qtys[i])}
                      onChange={(e) => setQty(i, Number(e.target.value))}
                      className="w-12 bg-transparent text-center text-[13px] font-semibold text-ink focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
                    />
                    <span className="text-[11px] text-muted pr-1">g</span>
                    <button
                      type="button"
                      onClick={() => setQty(i, Math.round(qtys[i]) + 25)}
                      className="press cursor-pointer w-6 h-6 rounded-full flex items-center justify-center text-muted hover:text-ink"
                    >
                      <Plus className="w-3 h-3" />
                    </button>
                  </div>

                  {/* Remove item */}
                  <button
                    type="button"
                    onClick={() => removeItem(i)}
                    aria-label={`Remove ${swaps[i] ?? item.food_name}`}
                    className="press cursor-pointer w-6 h-6 rounded-full flex items-center justify-center text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Candidate switcher */}
              {item.candidates.length > 1 && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setOpenCandidates(openCandidates === i ? null : i)}
                    className="press cursor-pointer flex items-center gap-1 text-[11px] font-medium text-sage-deep hover:underline"
                  >
                    Not the right food? <ChevronDown className="w-3 h-3" />
                  </button>
                  {openCandidates === i && (
                    <div className="absolute left-0 right-0 mt-1.5 bg-paper border border-sand-border rounded-xl shadow-lg z-20 max-h-44 overflow-y-auto rise-in">
                      {item.candidates.map((cand) => (
                        <button
                          key={cand}
                          type="button"
                          onClick={() => {
                            setSwaps((prev) =>
                              cand === item.food_name
                                ? Object.fromEntries(
                                    Object.entries(prev).filter(([k]) => Number(k) !== i)
                                  )
                                : { ...prev, [i]: cand }
                            )
                            setOpenCandidates(null)
                          }}
                          className={`cursor-pointer w-full text-left px-3.5 py-2.5 text-[13px] hover:bg-sand transition-colors ${
                            (swaps[i] ?? item.food_name) === cand
                              ? 'text-sage-deep font-medium'
                              : 'text-ink-soft'
                          }`}
                        >
                          {cand}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Totals */}
      <div className="grid grid-cols-5 text-center bg-container rounded-xl py-2.5">
        {[
          { label: 'kcal', value: Math.round(total('kcal')).toString() },
          { label: 'protein', value: `${total('protein_g').toFixed(0)}g` },
          { label: 'carbs', value: `${total('carbs_g').toFixed(0)}g` },
          { label: 'fat', value: `${total('fat_g').toFixed(0)}g` },
          { label: 'fiber', value: `${total('fiber_g').toFixed(0)}g` },
        ].map((t) => (
          <div key={t.label}>
            <span className="label-caps block text-[9px]">{t.label}</span>
            <span className="text-[13px] font-semibold text-ink">{t.value}</span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="grid grid-cols-2 gap-2.5 pt-1">
        <button
          type="button"
          onClick={() => onAction('cancel')}
          disabled={isLoading}
          className="press cursor-pointer py-2.5 rounded-full text-[14px] font-medium text-muted border border-sand-border hover:text-danger hover:border-danger/30 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => onAction(corrections.length > 0 ? corrections.join(' and ') : 'yes')}
          disabled={isLoading}
          className="press cursor-pointer py-2.5 rounded-full text-[14px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50"
        >
          {corrections.length > 0 ? 'Apply changes' : 'Confirm & log'}
        </button>
      </div>
    </div>
  )
}
