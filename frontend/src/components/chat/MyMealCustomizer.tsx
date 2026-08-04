import { useState } from 'react'
import { Plus, Minus, X, Check } from 'lucide-react'
import { useMyMeal, useLogMyMeal } from '../../api/hooks'
import type { MealCategory, MealItem } from '../../api/types'
import { MealTypePicker } from './MealTypePicker'
import { defaultMealCategory } from './meal-categories'

const PORTION_STEPS = [0.5, 1, 1.5, 2]

interface MyMealCustomizerProps {
  mealId: string
  onLogged: () => void
}

type MacroKey = 'kcal' | 'protein_g' | 'fiber_g'

/** Inline editor for logging a customized portion of a saved meal. */
export function MyMealCustomizer({ mealId, onLogged }: MyMealCustomizerProps) {
  const { data, isLoading, isError } = useMyMeal(mealId, true)
  const logMeal = useLogMyMeal(mealId)
  const [qtys, setQtys] = useState<number[]>([])
  const [removed, setRemoved] = useState<Set<number>>(new Set())
  const [portion, setPortion] = useState(1)
  const [mealType, setMealType] = useState<MealCategory>(() => defaultMealCategory())
  const [prev, setPrev] = useState<typeof data>(undefined)

  // Seed gram inputs from the fetched ingredients (adjust-state-during-render).
  if (data && data !== prev) {
    setPrev(data)
    setQtys(data.ingredients.map((i) => i.qty_g))
    setRemoved(new Set())
    return null
  }

  if (isError) {
    return <p className="text-[12px] text-danger px-1 py-2">Couldn’t load ingredients.</p>
  }
  if (isLoading || !data) {
    return <p className="text-[12px] text-muted px-1 py-2">Loading…</p>
  }
  if (qtys.length !== data.ingredients.length) return null

  const items: MealItem[] = data.ingredients
  const visible = items.map((_, i) => i).filter((i) => !removed.has(i))
  const scaleOf = (i: number) => (qtys[i] * portion) / items[i].qty_g
  const total = (key: MacroKey) =>
    visible.reduce((acc, i) => acc + items[i][key] * scaleOf(i), 0)

  const setQty = (i: number, v: number) => {
    if (v <= 0 || Number.isNaN(v)) return
    setQtys((p) => p.map((q, idx) => (idx === i ? v : q)))
  }
  const remove = (i: number) => setRemoved((p) => new Set([...p, i]))

  const handleLog = () => {
    if (visible.length === 0) return
    logMeal.mutate(
      {
        meal_type: mealType,
        portion,
        ingredients: visible.map((i) => ({ index: i, qty_g: Math.round(qtys[i]) })),
      },
      { onSuccess: onLogged },
    )
  }

  return (
    <div className="mt-3 pt-3 border-t border-sand-border flex flex-col gap-3">
      {/* Ingredients */}
      <div className="flex flex-col gap-2">
        {items.map((item, i) => {
          if (removed.has(i)) return null
          return (
            <div
              key={`${item.fdc_id}-${i}`}
              className="flex items-center justify-between gap-2"
            >
              <span className="text-[13px] text-ink truncate min-w-0 flex-1">
                {item.food_name}
              </span>
              <div className="flex items-center gap-1 shrink-0">
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
                    value={qtys[i] ? Math.round(qtys[i]) : ''}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      setQtys((prev) =>
                        prev.map((q, idx) => (idx === i ? (Number.isNaN(n) ? 0 : n) : q)),
                      )
                    }}
                    onBlur={() => {
                      if (!qtys[i] || qtys[i] <= 0) setQty(i, Math.round(items[i].qty_g))
                    }}
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
                <button
                  type="button"
                  onClick={() => remove(i)}
                  aria-label={`Remove ${item.food_name}`}
                  className="press cursor-pointer w-6 h-6 rounded-full flex items-center justify-center text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Live totals */}
      <div className="grid grid-cols-3 text-center bg-container rounded-xl py-2">
        {[
          { label: 'kcal', value: Math.round(total('kcal')).toString() },
          { label: 'protein', value: `${total('protein_g').toFixed(0)}g` },
          { label: 'fiber', value: `${total('fiber_g').toFixed(0)}g` },
        ].map((t) => (
          <div key={t.label}>
            <span className="label-caps block text-[9px]">{t.label}</span>
            <span className="text-[13px] font-semibold text-ink">{t.value}</span>
          </div>
        ))}
      </div>

      {/* Portion + meal type */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted">Portion</span>
        <div className="flex items-center gap-1 bg-container rounded-full p-0.5">
          {PORTION_STEPS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPortion(p)}
              className={`cursor-pointer px-2.5 py-1 rounded-full text-[12px] font-medium transition-colors ${
                portion === p ? 'bg-sage text-white' : 'text-muted hover:text-ink'
              }`}
            >
              {p}×
            </button>
          ))}
        </div>
        <MealTypePicker value={mealType} onChange={setMealType} />
      </div>

      {logMeal.isError && (
        <span className="text-[11px] text-danger">Could not log — try again.</span>
      )}

      <button
        type="button"
        onClick={handleLog}
        disabled={logMeal.isPending || visible.length === 0}
        className="press cursor-pointer flex items-center justify-center gap-1.5 py-2 rounded-full text-[13px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50"
      >
        <Check className="w-3.5 h-3.5" />
        Log this meal
      </button>
    </div>
  )
}
