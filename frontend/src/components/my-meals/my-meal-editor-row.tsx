import { X } from 'lucide-react'

import type { MealItem } from '@/api/types'

interface MyMealEditorRowProps {
  item: MealItem
  /** Raw text of the gram input (kept as a string so invalid input can show) */
  value: string
  onChange: (value: string) => void
  onRemove: () => void
  /** True when this is the last kept row (a meal needs at least one ingredient) */
  isLastKept: boolean
}

/** True when the text is a positive finite number of grams. */
export function isValidGrams(value: string): boolean {
  const n = Number(value)
  return value.trim() !== '' && Number.isFinite(n) && n > 0
}

/** One editable ingredient row: name, estimate badge, gram input, remove. */
export function MyMealEditorRow({
  item,
  value,
  onChange,
  onRemove,
  isLastKept,
}: MyMealEditorRowProps) {
  const invalid = !isValidGrams(value)
  const errorId = `qty-error-${item.fdc_id}-${item.food_name}`
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] text-ink truncate min-w-0 flex-1">
          {item.food_name}
          {item.estimated && (
            <span className="ml-2 text-[10px] uppercase text-muted">Estimate</span>
          )}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          <div className="flex items-center gap-1 bg-container rounded-full px-2 py-0.5">
            <input
              type="number"
              min={1}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              aria-label={`Grams of ${item.food_name}`}
              aria-invalid={invalid}
              aria-describedby={invalid ? errorId : undefined}
              className="w-14 bg-transparent text-center text-[13px] font-semibold text-ink focus:outline-none"
            />
            <span className="text-[11px] text-muted">g</span>
          </div>
          <button
            type="button"
            onClick={onRemove}
            disabled={isLastKept}
            aria-label={`Remove ${item.food_name}`}
            className="press cursor-pointer w-6 h-6 rounded-full flex items-center justify-center text-muted hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {invalid && (
        <span id={errorId} role="alert" className="text-[11px] text-danger">
          Enter a weight above 0.
        </span>
      )}
    </div>
  )
}
