// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { MealItem } from '@/api/types'
import { hasRecipeChanges } from '@/lib/meal-math'

const mutate = vi.fn()

vi.mock('@/api/hooks', () => ({
  useUpdateMeal: () => ({ mutate, isPending: false }),
}))

const { UpdateSavedMealOffer } = await import('./update-saved-meal-offer')

const item = (qty: number): MealItem =>
  ({
    food_name: 'Rice',
    qty_g: qty,
    confidence: 1,
    kcal: 100,
    protein_g: 2,
    carbs_g: 20,
    fat_g: 1,
    fiber_g: 1,
    fdc_id: 1,
    candidates: [],
    source: 'USDA',
    estimated: false,
  }) as MealItem

const savedMeal = { id: 'm1', name: 'Lunch bowl', updated_at: '2026-01-01T00:00:00.000000Z' }
const rows = [{ ...item(100), target_qty_g: 150 }]

describe('UpdateSavedMealOffer', () => {
  beforeEach(() => mutate.mockReset())
  afterEach(cleanup)

  it('is offered after a gram change and not after a portion-only change', () => {
    // The card renders the offer only when hasRecipeChanges is true; portion is
    // not an input, so a portion-only change (same grams) yields false.
    const snapshot = [item(100)]
    expect(hasRecipeChanges(snapshot, [{ item: snapshot[0], qtyG: 150 }])).toBe(true)
    expect(hasRecipeChanges(snapshot, [{ item: snapshot[0], qtyG: 100 }])).toBe(false)

    render(<UpdateSavedMealOffer savedMeal={savedMeal} items={rows} />)
    expect(screen.getByText('Update ‘Lunch bowl’ in My Meals?')).toBeTruthy()
  })

  it('Update sends a PUT body with expected_updated_at', () => {
    render(<UpdateSavedMealOffer savedMeal={savedMeal} items={rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Update' }))
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate.mock.calls[0][0]).toEqual({
      id: 'm1',
      body: {
        name: 'Lunch bowl',
        expected_updated_at: savedMeal.updated_at,
        ingredients: rows,
      },
    })
  })

  it('Not now sends nothing and hides the offer', () => {
    const onDone = vi.fn()
    render(<UpdateSavedMealOffer savedMeal={savedMeal} items={rows} onDone={onDone} />)
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(mutate).not.toHaveBeenCalled()
    expect(screen.queryByText(/in My Meals\?/)).toBeNull()
    expect(onDone).toHaveBeenCalled()
  })

  it('shows the conflict copy on meal_changed and Retry on other errors', () => {
    render(<UpdateSavedMealOffer savedMeal={savedMeal} items={rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Update' }))
    const opts = mutate.mock.calls[0][1] as { onError: (e: Error) => void }
    act(() => opts.onError(new ApiError('x', 500)))
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    const opts2 = mutate.mock.calls[1][1] as { onError: (e: Error) => void }
    act(() => opts2.onError(new ApiError('x', 409, { code: 'meal_changed' })))
    expect(screen.getByText('This meal changed since — open My Meals to edit.')).toBeTruthy()
  })
})
