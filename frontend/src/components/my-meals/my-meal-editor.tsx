import { useState } from 'react'

import { useMyMeal } from '@/api/hooks'
import type { MyMealDetail } from '@/api/types'

import { MyMealEditorForm } from './my-meal-editor-form'

interface MyMealEditorProps {
  mealId: string
  onClose: () => void
}

/** Inline editor for a saved meal's name, ingredient grams and ingredient list. */
export function MyMealEditor({ mealId, onClose }: MyMealEditorProps) {
  const { data, isLoading, isError } = useMyMeal(mealId, true)
  // Set after a meal_changed conflict: the server's newer version replaces local edits.
  const [latest, setLatest] = useState<MyMealDetail | null>(null)

  if (isError) {
    return <p className="text-[12px] text-danger px-1 py-2">Couldn’t load ingredients.</p>
  }
  const detail = latest ?? data
  if (isLoading || !detail) {
    return <p className="text-[12px] text-muted px-1 py-2">Loading…</p>
  }

  return (
    <>
      {latest && (
        <p role="status" className="text-[12px] text-muted mt-3">
          This meal changed on another device. Showing the latest version.
        </p>
      )}
      <MyMealEditorForm
        key={detail.updated_at}
        detail={detail}
        onSaved={onClose}
        onCancel={onClose}
        onConflict={setLatest}
      />
    </>
  )
}
