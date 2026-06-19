import { useState } from 'react'
import { ChevronDown, UtensilsCrossed } from 'lucide-react'
import { MEAL_CATEGORIES, type MealCategory } from '../../api/types'
import { CATEGORY_LABELS } from './meal-categories'

interface MealTypePickerProps {
  value: MealCategory
  onChange: (cat: MealCategory) => void
}

/** Shared meal-category dropdown used by the confirmation card and My Meals. */
export function MealTypePicker({ value, onChange }: MealTypePickerProps) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="press cursor-pointer flex items-center gap-1.5 bg-container rounded-full pl-3 pr-2 py-1 text-[13px] font-medium text-ink hover:bg-container-high"
      >
        <UtensilsCrossed className="w-3.5 h-3.5 text-sage-deep" />
        {CATEGORY_LABELS[value]}
        <ChevronDown className="w-3.5 h-3.5 text-muted" />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1.5 w-40 bg-paper border border-sand-border rounded-xl shadow-lg z-30 max-h-44 overflow-y-auto rise-in"
        >
          {MEAL_CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              role="option"
              aria-selected={value === cat}
              onClick={() => {
                onChange(cat)
                setOpen(false)
              }}
              className={`cursor-pointer w-full text-left px-3.5 py-2.5 text-[13px] hover:bg-sand transition-colors ${
                value === cat ? 'text-sage-deep font-medium' : 'text-ink-soft'
              }`}
            >
              {CATEGORY_LABELS[cat]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
