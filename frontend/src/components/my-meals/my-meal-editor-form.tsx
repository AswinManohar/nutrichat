import { useState } from 'react'

import { isErrorCode } from '@/api/client'
import { useUpdateMeal } from '@/api/hooks'
import type { MyMealDetail } from '@/api/types'
import { useMealEditorState } from '@/hooks/use-meal-editor-state'

import { MyMealEditorRow } from './my-meal-editor-row'

interface MyMealEditorFormProps {
  detail: MyMealDetail
  onSaved: () => void
  onCancel: () => void
  /** The server's newer version, after a meal_changed conflict */
  onConflict: (current: MyMealDetail) => void
}

/** Editable name, ingredient rows, live totals and Save/Cancel for one meal. */
export function MyMealEditorForm({
  detail,
  onSaved,
  onCancel,
  onConflict,
}: MyMealEditorFormProps) {
  const state = useMealEditorState(detail)
  const update = useUpdateMeal()
  const [nameTaken, setNameTaken] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = () => {
    const body = state.buildRequest()
    if (!body) return
    setNameTaken(false)
    setError(null)
    update.mutate(
      { id: detail.id, body },
      {
        onSuccess: onSaved,
        onError: (err) => {
          if (isErrorCode(err.detail, 'meal_changed')) {
            onConflict((err.detail as { current: MyMealDetail }).current)
          } else if (isErrorCode(err.detail, 'name_taken')) {
            setNameTaken(true)
          } else {
            setError(err.message || 'Could not save changes.')
          }
        },
      },
    )
  }

  return (
    <div className="mt-3 pt-3 border-t border-sand-border flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <input
          value={state.name}
          onChange={(e) => {
            setNameTaken(false)
            state.setName(e.target.value)
          }}
          aria-label="Meal name"
          aria-invalid={nameTaken}
          className="bg-container rounded-xl px-3 py-2 text-[14px] font-medium text-ink focus:outline-none"
        />
        {nameTaken && (
          <span role="alert" className="text-[11px] text-danger">
            You already have a meal with that name.
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2">
        {state.rows.map((row, i) =>
          row.removed ? null : (
            <MyMealEditorRow
              key={`${row.item.fdc_id}-${i}`}
              item={row.item}
              value={row.qty}
              onChange={(v) => state.setQty(i, v)}
              onRemove={() => state.remove(i)}
              isLastKept={state.keptCount === 1}
            />
          ),
        )}
      </div>
      <p className="text-[12px] text-muted" data-testid="editor-totals">
        {Math.round(state.sum.kcal)} kcal · {Math.round(state.sum.protein_g)}g protein ·{' '}
        {Math.round(state.sum.fiber_g)}g fiber
      </p>
      {error && (
        <div role="alert" className="flex items-center gap-2 text-[12px] text-danger">
          <span>{error}</span>
          <button type="button" onClick={save} className="underline cursor-pointer">
            Retry
          </button>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="press cursor-pointer px-3.5 py-2 rounded-full text-[13px] font-medium text-ink border border-sand-border"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!state.canSave || update.isPending}
          className="press cursor-pointer px-3.5 py-2 rounded-full text-[13px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {update.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}
