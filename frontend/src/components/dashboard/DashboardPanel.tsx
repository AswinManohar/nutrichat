import { useDashboard, useGoals } from '../../api/hooks'
import { MacroRings } from './MacroRings'
import { MealCategoryCard } from './MealCategoryCard'
import { NutrientCheckupCard } from './NutrientCheckupCard'
import { TrendsSection } from './TrendsSection'

const DATE_FMT = new Intl.DateTimeFormat('en-US', {
  weekday: 'long',
  month: 'short',
  day: 'numeric',
})

export function DashboardPanel() {
  const { data: totals } = useDashboard()
  const { data: goals } = useGoals()

  const kcal = totals?.kcal ?? 0
  const remaining = Math.max(0, (goals?.kcal_goal ?? 2000) - kcal)
  const streakDays = goals?.streak_days ?? 0
  const nMeals = totals?.n_meals ?? 0

  return (
    <div className="w-full h-full overflow-y-auto px-4 md:px-6 py-6 space-y-8 rise-stagger">
      {/* Daily summary header */}
      <section className="flex justify-between items-end" style={{ '--i': 0 } as React.CSSProperties}>
        <div>
          <span className="label-caps">{DATE_FMT.format(new Date()).toUpperCase()}</span>
          <h2 className="text-2xl font-semibold text-ink mt-0.5">Daily Summary</h2>
        </div>
        <div className="text-right">
          <span className="label-caps">Remaining</span>
          <p className="text-xl font-medium text-sage">{Math.round(remaining).toLocaleString()} kcal</p>
        </div>
      </section>

      {/* Rings */}
      <section style={{ '--i': 1 } as React.CSSProperties}>
        <MacroRings totals={totals} goals={goals} />
      </section>

      {/* Insight banner */}
      <section
        className="bg-sage-container text-white p-6 rounded-2xl relative overflow-hidden press"
        style={{ '--i': 2 } as React.CSSProperties}
      >
        <div className="relative z-10 space-y-1.5">
          <p className="label-caps !text-white/70">Today</p>
          <p className="text-[16px] leading-relaxed opacity-95">
            {nMeals === 0
              ? 'Nothing logged yet. Tell the chat what you ate — it takes one sentence.'
              : `${nMeals} meal${nMeals === 1 ? '' : 's'} logged${
                  streakDays > 0 ? ` · ${streakDays}-day streak` : ''
                }. ${remaining > 0 ? `${Math.round(remaining)} kcal left toward your goal.` : 'Daily goal reached.'}`}
          </p>
        </div>
        {/* Quiet geometric accent */}
        <svg
          className="absolute -right-5 -bottom-5 opacity-10"
          width="120"
          height="120"
          viewBox="0 0 100 100"
          fill="none"
        >
          <circle cx="50" cy="50" r="40" stroke="white" strokeWidth="10" />
          <path d="M50 10V90" stroke="white" strokeWidth="10" />
        </svg>
      </section>

      {/* Trends: heatmap + calorie sparkline */}
      <div style={{ '--i': 3 } as React.CSSProperties}>
        <TrendsSection kcalGoal={goals?.kcal_goal ?? 2000} />
      </div>

      {/* Meals by category */}
      <div style={{ '--i': 4 } as React.CSSProperties}>
        <MealCategoryCard />
      </div>

      {/* Weekly nutrient check-up */}
      <div style={{ '--i': 5 } as React.CSSProperties}>
        <NutrientCheckupCard />
      </div>

      {/* Dietary preferences */}
      {goals?.dietary_prefs && Object.keys(goals.dietary_prefs).length > 0 && (
        <section className="space-y-2.5" style={{ '--i': 6 } as React.CSSProperties}>
          <h3 className="label-caps">Dietary Focus</h3>
          <div className="flex flex-wrap gap-1.5">
            {Object.keys(goals.dietary_prefs).map((pref) => (
              <span
                key={pref}
                className="bg-container border border-sand-border text-[11px] font-medium text-ink-soft px-2.5 py-1 rounded-full capitalize"
              >
                {pref.replace('_', ' ')}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
