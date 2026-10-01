import { useState } from 'react'

import type { MealItem, MyMealDetail, UpdateMealRequest } from '@/api/types'
import { isValidGrams, scaleItem, totals, type MacroTotals } from '@/lib/meal-math'

export interface EditorRow {
  item: MealItem
  /** Raw gram text, so invalid input can be shown while typing */
  qty: string
  removed: boolean
}

export interface MealEditorState {
  name: string
  rows: EditorRow[]
  /** Totals over kept rows, scaled to the edited grams */
  sum: MacroTotals
  keptCount: number
  isDirty: boolean
  canSave: boolean
  setName: (name: string) => void
  setQty: (index: number, qty: string) => void
  remove: (index: number) => void
  /** Build the PUT body, or null when the form is not saveable. */
  buildRequest: () => UpdateMealRequest | null
}

/** Local edit state for one saved meal, seeded from `detail`. */
export function useMealEditorState(detail: MyMealDetail): MealEditorState {
  const [name, setName] = useState(detail.name)
  const [rows, setRows] = useState<EditorRow[]>(() =>
    detail.ingredients.map((item) => ({ item, qty: String(item.qty_g), removed: false })),
  )

  const kept = rows.filter((r) => !r.removed)
  const sum = totals(
    kept.filter((r) => isValidGrams(r.qty)).map((r) => scaleItem(r.item, Number(r.qty))),
  )
  const trimmed = name.trim()
  const isDirty =
    trimmed !== detail.name.trim() ||
    rows.some((r) => r.removed || (isValidGrams(r.qty) ? Number(r.qty) !== r.item.qty_g : true))
  const canSave =
    isDirty &&
    /[\p{L}\p{N}]/u.test(trimmed) &&
    kept.length > 0 &&
    kept.every((r) => isValidGrams(r.qty))

  const update = (index: number, patch: Partial<EditorRow>) =>
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)))

  return {
    name,
    rows,
    sum,
    keptCount: kept.length,
    isDirty,
    canSave,
    setName,
    setQty: (index, qty) => update(index, { qty }),
    remove: (index) => {
      if (kept.length > 1) update(index, { removed: true })
    },
    buildRequest: () =>
      canSave
        ? {
            name: trimmed,
            expected_updated_at: detail.updated_at,
            ingredients: kept.map((r) => ({ ...r.item, target_qty_g: Number(r.qty) })),
          }
        : null,
  }
}
