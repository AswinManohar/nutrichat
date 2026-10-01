import type { MealItem } from '@/api/types'

/** Macro fields that scale linearly with weight. null means "unknown", not zero. */
const SCALED_KEYS = ['kcal', 'protein_g', 'carbs_g', 'fat_g', 'fiber_g'] as const

export type MacroKey = (typeof SCALED_KEYS)[number]

/** Minimal row shape needed for scaling and totals. */
export type MacroRow = { qty_g: number } & {
  [K in MacroKey]?: number | null
}

export interface MacroTotals {
  kcal: number
  protein_g: number
  carbs_g: number
  fat_g: number
  fiber_g: number
}

/**
 * Scale an item's macros proportionally to a new gram weight.
 *
 * Macros refer to `item.qty_g`; the result has `qty_g = qtyG`. A null macro
 * stays null (unknown is not zero).
 */
export function scaleItem(item: MealItem, qtyG: number): MealItem {
  const factor = item.qty_g > 0 ? qtyG / item.qty_g : 0
  const out: MealItem = { ...item, qty_g: qtyG }
  for (const key of SCALED_KEYS) {
    const v = item[key] as number | null | undefined
    ;(out as unknown as Record<string, number | null | undefined>)[key] =
      v == null ? (v as null | undefined) : v * factor
  }
  return out
}

/** Sum macros over rows, counting null/undefined as 0. */
export function totals(rows: readonly MacroRow[]): MacroTotals {
  const sum: MacroTotals = { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 }
  for (const row of rows) {
    for (const key of SCALED_KEYS) sum[key] += row[key] ?? 0
  }
  return sum
}

/** True when the text is a positive finite number of grams. */
export function isValidGrams(value: string): boolean {
  const n = Number(value)
  return value.trim() !== '' && Number.isFinite(n) && n > 0
}

/**
 * True when the final rows differ from the snapshot enough to change a saved
 * recipe: different count, a different food at the same position (fdc_id or
 * food_name), or a gram change of 1 g or more. Portion and meal type are
 * deliberately not inputs (FR-012).
 */
export function hasRecipeChanges(
  snapshot: readonly MealItem[],
  final: readonly { item: MealItem; qtyG: number }[],
): boolean {
  if (snapshot.length !== final.length) return true
  return final.some(({ item, qtyG }, i) => {
    const before = snapshot[i]
    return (
      item.fdc_id !== before.fdc_id ||
      item.food_name !== before.food_name ||
      Math.abs(qtyG - before.qty_g) >= 1
    )
  })
}
