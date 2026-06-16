import { useCategoryBreakdown } from '../../api/hooks'
import type { CategoryStat, MealCategory } from '../../api/types'

const CATEGORY_LABELS: Record<MealCategory, string> = {
  breakfast: 'Breakfast',
  brunch: 'Brunch',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snack',
}

const WINDOW_DAYS = 30

function CategoryRow({ stat }: { stat: CategoryStat }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-ink">
          {CATEGORY_LABELS[stat.meal_type]}
        </span>
        <span className="text-[11px] text-muted">
          {Math.round(stat.avg_kcal)} kcal avg · {stat.n_meals} logged
        </span>
      </div>
      {/* Share-of-calories bar */}
      <div className="h-1.5 rounded-full bg-container overflow-hidden">
        <div
          className="h-full bg-sage rounded-full transition-[width] duration-500"
          style={{ width: `${stat.share_kcal_pct}%` }}
        />
      </div>
      <div className="flex gap-3 text-[10px] text-muted">
        <span>{Math.round(stat.avg_protein_g)}g protein</span>
        <span>{Math.round(stat.avg_carbs_g)}g carbs</span>
        <span>{Math.round(stat.avg_fat_g)}g fat</span>
        <span className="ml-auto font-medium text-sage-deep">
          {stat.share_kcal_pct}% of kcal
        </span>
      </div>
    </div>
  )
}

export function MealCategoryCard() {
  const { data, isLoading } = useCategoryBreakdown(WINDOW_DAYS)

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="label-caps">Meals by category</h3>
        <span className="text-[11px] text-muted">last {WINDOW_DAYS} days</span>
      </div>

      {isLoading ? (
        <p className="text-[12px] text-muted">Loading…</p>
      ) : !data || data.length === 0 ? (
        <p className="text-[12px] text-muted">
          No meals logged yet. Categories appear once you log a few meals.
        </p>
      ) : (
        <div className="card-sand p-4 space-y-4">
          {data.map((stat) => (
            <CategoryRow key={stat.meal_type} stat={stat} />
          ))}
        </div>
      )}
    </section>
  )
}
