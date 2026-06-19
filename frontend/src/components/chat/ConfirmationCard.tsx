import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { MealCategory, MealItem } from '../../api/types'
import { useSaveMeal } from '../../api/hooks'
import { ChevronDown, Plus, Minus, X, UtensilsCrossed, Sparkles, Bookmark, Check } from 'lucide-react'
import { MealTypePicker } from './MealTypePicker'
import { defaultMealCategory } from './meal-categories'

interface ConfirmationCardProps {
  items: MealItem[]
  onAction: (text: string, mealType?: MealCategory) => void
  onDismiss: () => void
  onDecompose: () => void
  onCombine: () => void
  isLoading: boolean
}

const PORTION_STEPS = [0.5, 1, 1.5, 2]

const LOW_CONFIDENCE = 0.6

interface ItemGroup {
  dish: string | null // source_dish; null = a standalone atomic item
  indices: number[] // original indices into the flat `items` array
}

/** Group consecutive items by source_dish, preserving first-seen order. */
function groupByDish(items: MealItem[]): ItemGroup[] {
  const groups: ItemGroup[] = []
  const pos = new Map<string, number>()
  items.forEach((item, i) => {
    const dish = item.source_dish ?? null
    if (dish === null) {
      groups.push({ dish: null, indices: [i] })
      return
    }
    const at = pos.get(dish)
    if (at === undefined) {
      pos.set(dish, groups.length)
      groups.push({ dish, indices: [i] })
    } else {
      groups[at].indices.push(i)
    }
  })
  return groups
}

/**
 * Editable confirmation card for the paused meal-logging graph.
 * Quantity edits, candidate switches, and removals are sent back as
 * plain-text corrections — the backend re-resolves and re-presents.
 */
export function ConfirmationCard({
  items,
  onAction,
  onDismiss,
  onDecompose,
  onCombine,
  isLoading,
}: ConfirmationCardProps) {
  const [qtys, setQtys] = useState<number[]>(() => items.map((i) => i.qty_g))
  const [openCandidates, setOpenCandidates] = useState<number | null>(null)
  const [swaps, setSwaps] = useState<Record<number, string>>({})
  const [removed, setRemoved] = useState<Set<number>>(new Set())
  const [prevItems, setPrevItems] = useState(items)
  const [mealType, setMealType] = useState<MealCategory>(() => defaultMealCategory())
  const [portion, setPortion] = useState(1)
  const [mealName, setMealName] = useState('')
  const [openDish, setOpenDish] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [addName, setAddName] = useState('')
  const [addGrams, setAddGrams] = useState('')
  const dismissedRef = useRef(false)
  const saveMeal = useSaveMeal()

  const closeDish = () => {
    setOpenDish(null)
    setAddOpen(false)
    setAddName('')
    setAddGrams('')
  }

  // Add a not-yet-listed ingredient to the open dish via the correction path.
  // The backend nests it under the dish (source_dish) and re-presents the card.
  const addIngredient = () => {
    const name = addName.trim()
    const grams = Math.round(Number(addGrams))
    if (!name || !grams || grams <= 0 || openDish === null) return
    onAction(`add ${grams}g ${name} to ${openDish}`, mealType)
    closeDish()
  }

  // Every visible item removed → drop the card from the chat (no backend call).
  // Computed before any early return so the hook below is unconditional.
  const allRemoved = items.length > 0 && removed.size >= items.length

  useEffect(() => {
    if (allRemoved && !dismissedRef.current) {
      dismissedRef.current = true
      onDismiss()
    }
  }, [allRemoved, onDismiss])

  // A new card arrived → allow onDismiss to fire again for it.
  useEffect(() => {
    dismissedRef.current = false
  }, [items])

  // Reset edits when a new card arrives (React "adjust state during render")
  if (prevItems !== items) {
    setPrevItems(items)
    setQtys(items.map((i) => i.qty_g))
    setSwaps({})
    setRemoved(new Set())
    setPortion(1)
    setMealName('')
    setOpenDish(null)
    setAddOpen(false)
    setAddName('')
    setAddGrams('')
    return null
  }

  if (qtys.length !== items.length) return null
  if (allRemoved) return null

  const visibleIndices = items.map((_, i) => i).filter((i) => !removed.has(i))

  // Composite dish groups that still have at least one visible ingredient.
  // One dish → drop the per-row "Break into ingredients" and keep only the
  // bottom button (which opens that dish's popup); 2+ → per-row buttons.
  const visibleDishGroups = groupByDish(items).filter(
    (g) => g.dish !== null && g.indices.some((i) => !removed.has(i))
  )
  const soleDish = visibleDishGroups.length === 1 ? visibleDishGroups[0].dish : null

  // Live totals scale linearly with qty edits × the portion multiplier.
  const scaled = items.map((item, i) => {
    const scale = (qtys[i] * portion) / item.qty_g
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
    // Effective grams fold in the portion multiplier.
    const effective = Math.round(qtys[i] * portion)
    if (effective !== Math.round(item.qty_g))
      corrections.push(`change ${item.food_name} to ${effective}g`)
  })

  const handleSaveMeal = () => {
    const name = mealName.trim()
    if (!name || saveMeal.isSuccess) return
    // Save the resolved base meal (full nutrients preserved); portion/edits
    // affect logging, not the saved template.
    saveMeal.mutate({ name, ingredients: items })
  }

  const setQty = (i: number, v: number) => {
    if (v <= 0 || Number.isNaN(v)) return
    setQtys((prev) => prev.map((q, idx) => (idx === i ? v : q)))
  }

  const removeItem = (i: number) => {
    setRemoved((prev) => new Set([...prev, i]))
    if (openCandidates === i) setOpenCandidates(null)
  }

  const renderItemRow = (i: number) => {
    const item = items[i]
    if (removed.has(i)) return null
    return (
      <div
        key={`${item.fdc_id}-${i}`}
        className="bg-paper rounded-xl border border-sand-border p-3.5 flex flex-col gap-2"
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
  }

  return (
    <div className="w-full max-w-xl card-sand p-4 md:p-5 flex flex-col gap-3 mt-1 rise-in">
      <div className="flex items-center justify-between pb-2 border-b border-sand-border">
        <h3 className="label-caps !text-sage-deep">Confirm meal</h3>
        <span className="text-[11px] text-muted">
          {visibleIndices.length} item{visibleIndices.length === 1 ? '' : 's'}
        </span>
      </div>

      {/* Meal category — pre-filled from local time, tap to change */}
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-muted">Meal</span>
        <MealTypePicker value={mealType} onChange={setMealType} />
      </div>

      {/* Items — atomic rows inline; composite dishes collapsed with a per-dish popup */}
      <div className="flex flex-col gap-2.5">
        {groupByDish(items).map((group) => {
          if (group.dish === null) return renderItemRow(group.indices[0])
          const visible = group.indices.filter((i) => !removed.has(i))
          if (visible.length === 0) return null
          const sum = (key: 'kcal' | 'protein_g' | 'fiber_g') =>
            visible.reduce((acc, i) => acc + scaled[i][key], 0)
          return (
            <div
              key={`dish-${group.dish}`}
              className="bg-paper rounded-xl border border-sand-border p-3.5 flex items-center justify-between gap-2"
            >
              <div className="min-w-0 flex-1">
                <h4 className="text-[14px] font-medium text-ink leading-snug truncate">
                  {group.dish}
                </h4>
                <p className="text-[11px] text-muted mt-0.5">
                  {Math.round(sum('kcal'))} kcal · {sum('protein_g').toFixed(0)}g protein ·{' '}
                  {sum('fiber_g').toFixed(0)}g fiber · {visible.length} ingredient
                  {visible.length === 1 ? '' : 's'}
                </p>
              </div>
              {visibleDishGroups.length > 1 && (
                <button
                  type="button"
                  onClick={() => setOpenDish(group.dish)}
                  className="press cursor-pointer shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium text-sage-deep border border-sand-border hover:border-sage"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Break into ingredients
                </button>
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

      {/* Portion multiplier */}
      <div className="flex items-center gap-2">
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
      </div>

      {/* Primary actions — prominent, first */}
      <div className="grid grid-cols-2 gap-2.5">
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
          onClick={() =>
            onAction(corrections.length > 0 ? corrections.join(' and ') : 'yes', mealType)
          }
          disabled={isLoading}
          className="press cursor-pointer py-2.5 rounded-full text-[14px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50"
        >
          {corrections.length > 0 ? 'Apply changes' : 'Confirm & log'}
        </button>
      </div>

      {/* Secondary actions — below the fold, unobtrusive */}
      <div className="flex flex-col gap-2 pt-1 border-t border-sand-border">
        {/* Save to My Meals */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={mealName}
            onChange={(e) => setMealName(e.target.value)}
            placeholder="Save this meal for later…"
            disabled={saveMeal.isSuccess}
            className="flex-1 bg-paper border border-sand-border rounded-full px-3.5 py-2 text-[13px] text-ink focus:outline-none focus:ring-1 focus:ring-sage/30 disabled:opacity-60"
          />
          <button
            type="button"
            onClick={handleSaveMeal}
            disabled={!mealName.trim() || saveMeal.isPending || saveMeal.isSuccess}
            className="press cursor-pointer shrink-0 flex items-center gap-1.5 px-3.5 py-2 rounded-full text-[13px] font-medium text-ink-soft border border-sand-border hover:border-sage hover:text-sage-deep disabled:opacity-50"
          >
            {saveMeal.isSuccess ? (
              <>
                <Check className="w-3.5 h-3.5" /> Saved
              </>
            ) : (
              <>
                <Bookmark className="w-3.5 h-3.5" /> Save
              </>
            )}
          </button>
        </div>
        {saveMeal.isError && (
          <span className="text-[11px] text-danger">
            {saveMeal.error?.status === 409
              ? 'You already have a meal with that name.'
              : 'Could not save — try again.'}
          </span>
        )}

        {/* Break / Combine — text-weight, only when relevant */}
        {(visibleDishGroups.length < 2 || items.some((i) => i.source_dish)) && (
          <div className="flex items-center gap-3 flex-wrap">
            {visibleDishGroups.length < 2 && (
              <button
                type="button"
                onClick={soleDish ? () => setOpenDish(soleDish) : onDecompose}
                disabled={isLoading}
                className="press cursor-pointer flex items-center gap-1 text-[12px] font-medium text-sage-deep hover:underline disabled:opacity-50"
              >
                <Sparkles className="w-3 h-3" />
                Break into ingredients
              </button>
            )}
            {items.some((i) => i.source_dish) && (
              <button
                type="button"
                onClick={onCombine}
                disabled={isLoading}
                className="press cursor-pointer flex items-center gap-1 text-[12px] font-medium text-muted hover:text-ink-soft hover:underline disabled:opacity-50"
              >
                <UtensilsCrossed className="w-3 h-3" />
                Log as single item
              </button>
            )}
          </div>
        )}
      </div>

      {openDish !== null &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
            onClick={closeDish}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="w-full max-w-md card-sand p-4 md:p-5 flex flex-col gap-3 rise-in max-h-[80vh]"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Pinned header — dish name stays in place */}
              <div className="shrink-0 flex items-center justify-between pb-2 border-b border-sand-border">
                <h3 className="label-caps !text-sage-deep truncate">{openDish}</h3>
                <button
                  type="button"
                  onClick={closeDish}
                  aria-label="Close"
                  className="press cursor-pointer w-7 h-7 rounded-full flex items-center justify-center text-muted hover:text-ink hover:bg-container"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              {/* Only the ingredients scroll */}
              <div className="flex-1 overflow-y-auto flex flex-col gap-2.5 -mr-1 pr-1">
                {groupByDish(items)
                  .find((g) => g.dish === openDish)
                  ?.indices.map((i) => renderItemRow(i))}
              </div>

              {/* Add an ingredient missing from the breakdown */}
              <div className="shrink-0">
                {addOpen ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      autoFocus
                      value={addName}
                      onChange={(e) => setAddName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addIngredient()}
                      placeholder="Ingredient (e.g. cashews)"
                      className="flex-1 min-w-0 bg-paper border border-sand-border rounded-full px-3.5 py-2 text-[13px] text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                    />
                    <input
                      type="number"
                      value={addGrams}
                      onChange={(e) => setAddGrams(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addIngredient()}
                      placeholder="g"
                      className="w-16 bg-paper border border-sand-border rounded-full px-3 py-2 text-[13px] text-center text-ink focus:outline-none focus:ring-1 focus:ring-sage/30 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
                    />
                    <button
                      type="button"
                      onClick={addIngredient}
                      disabled={isLoading || !addName.trim() || !Number(addGrams)}
                      className="press cursor-pointer shrink-0 px-3.5 py-2 rounded-full text-[13px] font-medium text-white bg-sage-deep hover:bg-sage disabled:opacity-50"
                    >
                      Add
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setAddOpen(true)}
                    className="press cursor-pointer flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium text-sage-deep border border-dashed border-sand-border hover:border-sage"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add ingredient
                  </button>
                )}
              </div>

              {/* Pinned footer — apply edits made in this popup */}
              <button
                type="button"
                onClick={() => {
                  if (corrections.length > 0)
                    onAction(corrections.join(' and '), mealType)
                  closeDish()
                }}
                disabled={isLoading}
                className="shrink-0 press cursor-pointer py-2.5 rounded-full text-[14px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50"
              >
                {corrections.length > 0 ? 'Apply changes' : 'Done'}
              </button>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
