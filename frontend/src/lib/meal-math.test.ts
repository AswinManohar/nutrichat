import { describe, expect, it } from 'vitest'

import type { MealItem } from '@/api/types'

import { hasRecipeChanges, isValidGrams, scaleItem, totals } from './meal-math'

const base = {
  food_name: 'Rice',
  qty_g: 200,
  confidence: 1,
  kcal: 260,
  protein_g: 5,
  carbs_g: 56,
  fat_g: 1,
  fiber_g: 2,
  fdc_id: 1,
  candidates: [],
  source: 'USDA',
  estimated: false,
} as MealItem

describe('scaleItem', () => {
  it('scales macros proportionally and sets qty_g', () => {
    const out = scaleItem(base, 100)
    expect(out.qty_g).toBe(100)
    expect(out.kcal).toBe(130)
    expect(out.protein_g).toBe(2.5)
    expect(out.fiber_g).toBe(1)
  })

  it('keeps null as null', () => {
    const out = scaleItem({ ...base, fiber_g: null as unknown as number }, 400)
    expect(out.fiber_g).toBeNull()
    expect(out.kcal).toBe(520)
  })

  it('does not mutate the input', () => {
    scaleItem(base, 50)
    expect(base.kcal).toBe(260)
  })
})

describe('totals', () => {
  it('sums macros and counts null as 0', () => {
    const t = totals([base, { ...base, kcal: 40, fiber_g: null as unknown as number }])
    expect(t.kcal).toBe(300)
    expect(t.fiber_g).toBe(2)
    expect(t.carbs_g).toBe(112)
  })

  it('returns zeros for no rows', () => {
    expect(totals([])).toEqual({
      kcal: 0,
      protein_g: 0,
      carbs_g: 0,
      fat_g: 0,
      fiber_g: 0,
    })
  })
})

describe('isValidGrams', () => {
  it('accepts positive finite numbers only', () => {
    expect(isValidGrams('150')).toBe(true)
    expect(isValidGrams('0.5')).toBe(true)
    for (const bad of ['', '  ', '0', '-3', 'abc', 'Infinity']) {
      expect(isValidGrams(bad)).toBe(false)
    }
  })
})

describe('hasRecipeChanges', () => {
  const snap = [base, { ...base, food_name: 'Chicken', fdc_id: 2, qty_g: 100 }]
  const same = snap.map((item) => ({ item, qtyG: item.qty_g }))

  it('is false for identical rows', () => {
    expect(hasRecipeChanges(snap, same)).toBe(false)
  })
  it('is true when the count differs', () => {
    expect(hasRecipeChanges(snap, same.slice(0, 1))).toBe(true)
    expect(hasRecipeChanges(snap, [...same, same[0]])).toBe(true)
  })
  it('is true for a different fdc_id at the same position', () => {
    const final = [{ item: { ...base, fdc_id: 9 }, qtyG: 200 }, same[1]]
    expect(hasRecipeChanges(snap, final)).toBe(true)
  })
  it('is true for the same fdc_id with a different name', () => {
    const final = [{ item: { ...base, food_name: 'Brown rice' }, qtyG: 200 }, same[1]]
    expect(hasRecipeChanges(snap, final)).toBe(true)
  })
  it('is false for a 0.5 g difference', () => {
    expect(hasRecipeChanges(snap, [{ item: base, qtyG: 200.5 }, same[1]])).toBe(false)
  })
  it('is true for a 1.0 g difference', () => {
    expect(hasRecipeChanges(snap, [{ item: base, qtyG: 201 }, same[1]])).toBe(true)
    expect(hasRecipeChanges(snap, [{ item: base, qtyG: 199 }, same[1]])).toBe(true)
  })
})
