// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { MealItem, MyMealDetail } from '@/api/types'

const mutate = vi.fn()
let detail: MyMealDetail

vi.mock('@/api/hooks', () => ({
  useMyMeal: () => ({ data: detail, isLoading: false, isError: false }),
  useUpdateMeal: () => ({ mutate, isPending: false }),
}))

const { MyMealEditor } = await import('./my-meal-editor')

const item = (name: string, qty: number, kcal: number): MealItem => ({
  food_name: name,
  qty_g: qty,
  confidence: 1,
  kcal,
  protein_g: 10,
  carbs_g: 10,
  fat_g: 1,
  fiber_g: 2,
  fdc_id: 1,
  candidates: [],
  source: 'USDA',
  estimated: false,
})

const makeDetail = (over: Partial<MyMealDetail> = {}): MyMealDetail => ({
  id: 'm1',
  name: 'Lunch bowl',
  kcal: 300,
  protein_g: 20,
  carbs_g: 20,
  fat_g: 2,
  fiber_g: 4,
  n_ingredients: 2,
  ingredients: [item('Rice', 100, 100), item('Chicken', 100, 200)],
  updated_at: '2026-01-01T00:00:00.000000Z',
  ...over,
} as MyMealDetail)

const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement
const grams = (food: string) => screen.getByLabelText(`Grams of ${food}`)

describe('MyMealEditor', () => {
  beforeEach(() => {
    mutate.mockReset()
    detail = makeDetail()
  })
  afterEach(cleanup)

  it('updates totals when grams change', () => {
    render(<MyMealEditor mealId="m1" onClose={vi.fn()} />)
    expect(screen.getByTestId('editor-totals').textContent).toContain('300 kcal')
    fireEvent.change(grams('Chicken'), { target: { value: '50' } })
    expect(screen.getByTestId('editor-totals').textContent).toContain('200 kcal')
  })

  it('disables remove on the last kept row', () => {
    render(<MyMealEditor mealId="m1" onClose={vi.fn()} />)
    fireEvent.click(button('Remove Rice'))
    expect(button('Remove Chicken').disabled).toBe(true)
  })

  it('saves only kept rows with target_qty_g and expected_updated_at', () => {
    render(<MyMealEditor mealId="m1" onClose={vi.fn()} />)
    expect(button('Save').disabled).toBe(true)
    fireEvent.click(button('Remove Rice'))
    fireEvent.change(grams('Chicken'), { target: { value: '150' } })
    fireEvent.change(screen.getByLabelText('Meal name'), { target: { value: '  Chicken  ' } })
    fireEvent.click(button('Save'))
    const { id, body } = mutate.mock.calls[0][0]
    expect(id).toBe('m1')
    expect(body.name).toBe('Chicken')
    expect(body.expected_updated_at).toBe('2026-01-01T00:00:00.000000Z')
    expect(body.ingredients).toHaveLength(1)
    expect(body.ingredients[0]).toMatchObject({
      food_name: 'Chicken',
      qty_g: 100,
      kcal: 200,
      target_qty_g: 150,
    })
  })

  it('cancel makes no call', () => {
    const onClose = vi.fn()
    render(<MyMealEditor mealId="m1" onClose={onClose} />)
    fireEvent.change(grams('Rice'), { target: { value: '5' } })
    fireEvent.click(button('Cancel'))
    expect(mutate).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('reloads from current on meal_changed', () => {
    const current = makeDetail({
      name: 'Server name',
      updated_at: '2026-02-02T00:00:00.000000Z',
    })
    mutate.mockImplementation((_vars, opts) =>
      opts.onError(new ApiError('conflict', 409, { code: 'meal_changed', current })),
    )
    render(<MyMealEditor mealId="m1" onClose={vi.fn()} />)
    fireEvent.change(grams('Rice'), { target: { value: '5' } })
    fireEvent.click(button('Save'))
    expect(screen.getByText(/changed on another device/)).toBeTruthy()
    expect((screen.getByLabelText('Meal name') as HTMLInputElement).value).toBe('Server name')
    expect((grams('Rice') as HTMLInputElement).value).toBe('100')
  })

  it('shows an inline error on name_taken', () => {
    mutate.mockImplementation((_vars, opts) =>
      opts.onError(new ApiError('conflict', 409, 'name_taken')),
    )
    render(<MyMealEditor mealId="m1" onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Meal name'), { target: { value: 'Dup' } })
    fireEvent.click(button('Save'))
    expect(screen.getByText(/already have a meal with that name/)).toBeTruthy()
  })
})
