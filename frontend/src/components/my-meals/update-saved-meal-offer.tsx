import { useState } from 'react'

import { isErrorCode } from '@/api/client'
import { useUpdateMeal } from '@/api/hooks'
import type { MealItem, SavedMealRef } from '@/api/types'

interface UpdateSavedMealOfferProps {
  savedMeal: SavedMealRef
  /** Final rows at 1x (portion excluded), each with target_qty_g set. */
  items: MealItem[]
  onDone?: () => void
}

/** Offer to write a customized log back to the saved meal it came from. */
export function UpdateSavedMealOffer({ savedMeal, items, onDone }: UpdateSavedMealOfferProps) {
  const update = useUpdateMeal()
  const [state, setState] = useState<'offer' | 'updated' | 'conflict' | 'error' | 'hidden'>(
    'offer',
  )

  if (state === 'hidden') return null

  const submit = () => {
    update.mutate(
      {
        id: savedMeal.id,
        body: {
          name: savedMeal.name,
          expected_updated_at: savedMeal.updated_at,
          ingredients: items,
        },
      },
      {
        onSuccess: () => {
          setState('updated')
          onDone?.()
        },
        onError: (err) =>
          setState(
            isErrorCode((err as { detail?: unknown }).detail, 'meal_changed')
              ? 'conflict'
              : 'error',
          ),
      },
    )
  }

  const hide = () => {
    setState('hidden')
    onDone?.()
  }

  if (state === 'updated') {
    return <p className="text-[12px] text-ink-muted">Updated ‘{savedMeal.name}’ in My Meals.</p>
  }
  if (state === 'conflict') {
    return (
      <p role="alert" className="text-[12px] text-danger">
        This meal changed since — open My Meals to edit.
      </p>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px]">
      <span>Update ‘{savedMeal.name}’ in My Meals?</span>
      <button type="button" onClick={submit} disabled={update.isPending} className="font-semibold">
        {state === 'error' ? 'Retry' : 'Update'}
      </button>
      <button type="button" onClick={hide} disabled={update.isPending}>
        Not now
      </button>
      {state === 'error' && (
        <span role="alert" className="text-danger">
          Couldn’t update.
        </span>
      )}
    </div>
  )
}
