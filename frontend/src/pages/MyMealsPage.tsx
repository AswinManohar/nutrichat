import { useState } from 'react'
import { BookMarked, Trash2, Plus, ChevronDown, Check, SlidersHorizontal } from 'lucide-react'
import { useMyMeals, useDeleteMeal, useLogMyMeal } from '../api/hooks'
import type { MealCategory, MyMealSummary } from '../api/types'
import { MEAL_CATEGORIES } from '../api/types'
import { CATEGORY_LABELS } from '../components/chat/meal-categories'
import { MyMealCustomizer } from '../components/chat/MyMealCustomizer'

function MealRow({ meal }: { meal: MyMealSummary }) {
  const deleteMeal = useDeleteMeal()
  const logMeal = useLogMyMeal(meal.id)
  const [logMenuOpen, setLogMenuOpen] = useState(false)
  const [customizing, setCustomizing] = useState(false)
  const [justLogged, setJustLogged] = useState(false)

  const quickLog = (cat: MealCategory) => {
    setLogMenuOpen(false)
    logMeal.mutate({ meal_type: cat }, { onSuccess: () => setJustLogged(true) })
  }

  return (
    <div className="card-sand p-4 flex flex-col">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-medium text-ink truncate">{meal.name}</h3>
          <p className="text-[12px] text-muted mt-0.5">
            {Math.round(meal.kcal)} kcal · {Math.round(meal.protein_g)}g protein ·{' '}
            {Math.round(meal.fiber_g)}g fiber · {meal.n_ingredients} ingredient
            {meal.n_ingredients === 1 ? '' : 's'}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Customize toggle */}
          <button
            type="button"
            onClick={() => setCustomizing((c) => !c)}
            aria-expanded={customizing}
            className={`press cursor-pointer flex items-center gap-1.5 px-3 py-2 rounded-full text-[13px] font-medium border border-sand-border ${
              customizing ? 'text-sage-deep border-sage' : 'text-ink hover:border-sage'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Customize
          </button>

          {/* Quick-log → meal-type dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setJustLogged(false)
                setLogMenuOpen((o) => !o)
              }}
              disabled={logMeal.isPending}
              aria-haspopup="listbox"
              aria-expanded={logMenuOpen}
              className="press cursor-pointer flex items-center gap-1.5 px-3.5 py-2 rounded-full text-[13px] font-medium text-white bg-sage hover:bg-sage-deep disabled:opacity-50"
            >
              {justLogged ? <Check className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {justLogged ? 'Logged' : 'Log'}
              {!justLogged && <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {logMenuOpen && (
              <div
                role="listbox"
                className="absolute right-0 top-full mt-1.5 w-40 bg-paper border border-sand-border rounded-xl shadow-lg z-30 max-h-44 overflow-y-auto rise-in"
              >
                {MEAL_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    role="option"
                    aria-selected={false}
                    onClick={() => quickLog(cat)}
                    className="cursor-pointer w-full text-left px-3.5 py-2.5 text-[13px] text-ink-soft hover:bg-sand transition-colors"
                  >
                    {CATEGORY_LABELS[cat]}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => deleteMeal.mutate(meal.id)}
            disabled={deleteMeal.isPending}
            aria-label={`Delete ${meal.name}`}
            className="press cursor-pointer w-9 h-9 rounded-full flex items-center justify-center text-muted hover:text-danger hover:bg-container disabled:opacity-50"
          >
            <Trash2 className="w-4 h-4" strokeWidth={1.75} />
          </button>
        </div>
      </div>

      {logMeal.isError && !customizing && (
        <span className="text-[11px] text-danger mt-2">Could not log — try again.</span>
      )}

      {customizing && (
        <MyMealCustomizer
          mealId={meal.id}
          onLogged={() => {
            setCustomizing(false)
            setJustLogged(true)
          }}
        />
      )}
    </div>
  )
}

export function MyMealsPage() {
  const { data: meals, isLoading } = useMyMeals()

  return (
    <div className="flex-1 overflow-y-auto bg-surface p-4 md:p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="flex items-center gap-3 border-b border-sand-border pb-5">
          <div className="w-9 h-9 rounded-xl bg-container border border-sand-border text-sage-deep flex items-center justify-center">
            <BookMarked className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-display font-bold text-xl text-ink">My Meals</h1>
            <p className="text-xs text-muted">
              Saved meals — log one in a tap, or customize the portion first.
            </p>
          </div>
        </div>

        {isLoading ? (
          <p className="text-[13px] text-muted">Loading…</p>
        ) : !meals || meals.length === 0 ? (
          <div className="card-sand p-6 text-center">
            <p className="text-[13px] text-muted">
              No saved meals yet. Log a meal, then tap{' '}
              <span className="font-medium text-ink">Save to My Meals</span> on the
              confirmation card.
            </p>
          </div>
        ) : (
          <div className="space-y-3 rise-stagger">
            {meals.map((meal) => (
              <div key={meal.id} style={{ '--i': 0 } as React.CSSProperties}>
                <MealRow meal={meal} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
