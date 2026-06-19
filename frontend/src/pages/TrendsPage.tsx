import { useMemo, useState } from 'react'
import { BookMarked, SlidersHorizontal, Trash2, Plus, ChevronDown, Check } from 'lucide-react'
import { useTrends, useGoals, useMyMeals, useDeleteMeal, useLogMyMeal } from '../api/hooks'
import type { DayTrend, MealCategory, MyMealSummary } from '../api/types'
import { MEAL_CATEGORIES } from '../api/types'
import { AppSidebar } from '../components/nav/AppSidebar'
import { TrendsSection } from '../components/dashboard/TrendsSection'
import { CATEGORY_LABELS } from '../components/chat/meal-categories'
import { MyMealCustomizer } from '../components/chat/MyMealCustomizer'

type Period = 7 | 30 | 91

const PERIODS: Period[] = [7, 30, 91]
const PERIOD_LABELS: Record<Period, string> = { 7: 'Week', 30: 'Month', 91: '90 days' }

// ── Stacked macro bar chart ───────────────────────────────────────────────────

interface BarChartProps {
  data: DayTrend[]
  period: Period
}

function MacroBarChart({ data, period }: BarChartProps) {
  const byDate = useMemo(() => {
    const map = new Map<string, DayTrend>()
    for (const t of data) map.set(t.date, t)
    return map
  }, [data])

  const days = useMemo(() => {
    const result: Array<{ date: string; trend: DayTrend | null }> = []
    for (let i = period - 1; i >= 0; i--) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      const iso = d.toISOString().slice(0, 10)
      result.push({ date: iso, trend: byDate.get(iso) ?? null })
    }
    return result
  }, [byDate, period])

  const maxTotal = useMemo(() => {
    const m = Math.max(
      ...days.map((d) => (d.trend?.carbs_g ?? 0) + (d.trend?.protein_g ?? 0) + (d.trend?.fiber_g ?? 0)),
      100
    )
    return m * 1.15
  }, [days])

  const W = 500
  const H = 150
  const PAD_T = 8
  const PAD_B = 22
  const PAD_H = 4
  const chartH = H - PAD_T - PAD_B
  const totalW = W - PAD_H * 2
  const gap = totalW / days.length
  const barW = Math.max(gap * 0.65, 2)

  const showLabel = (i: number) => {
    if (period === 7) return true
    if (period === 30) return i % 5 === 0 || i === days.length - 1
    return i % 10 === 0 || i === days.length - 1
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: 150 }}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {days.map(({ date, trend }, i) => {
        const x = PAD_H + i * gap + (gap - barW) / 2
        const carbs = trend?.carbs_g ?? 0
        const protein = trend?.protein_g ?? 0
        const fiber = trend?.fiber_g ?? 0
        const baseY = PAD_T + chartH

        const carbsH = (carbs / maxTotal) * chartH
        const proteinH = (protein / maxTotal) * chartH
        const fiberH = (fiber / maxTotal) * chartH

        const d = new Date(date + 'T12:00:00')
        const label =
          period === 7
            ? d.toLocaleDateString('en-US', { weekday: 'short' }).charAt(0)
            : d.getDate().toString()

        return (
          <g key={date}>
            {carbs > 0 && (
              <rect
                x={x}
                y={baseY - carbsH}
                width={barW}
                height={carbsH}
                fill="var(--color-carbs)"
                opacity={0.85}
                rx={1}
              />
            )}
            {protein > 0 && (
              <rect
                x={x}
                y={baseY - carbsH - proteinH}
                width={barW}
                height={proteinH}
                fill="var(--color-protein)"
                opacity={0.85}
                rx={1}
              />
            )}
            {fiber > 0 && (
              <rect
                x={x}
                y={baseY - carbsH - proteinH - fiberH}
                width={barW}
                height={fiberH}
                fill="var(--color-fiber)"
                opacity={0.85}
                rx={1}
              />
            )}
            {!trend && (
              <rect
                x={x}
                y={baseY - 3}
                width={barW}
                height={3}
                fill="var(--color-container-high)"
                rx={1}
              />
            )}
            {showLabel(i) && (
              <text
                x={x + barW / 2}
                y={H - 5}
                textAnchor="middle"
                fontSize={period === 7 ? 10 : 8}
                fill="var(--color-muted)"
              >
                {label}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string
  value: string | number
  unit?: string
  sub?: string
}

function StatCard({ label, value, unit, sub }: StatCardProps) {
  return (
    <div className="card-sand p-4 flex flex-col gap-1 min-w-0">
      <span className="text-[10px] uppercase tracking-widest text-muted font-medium">{label}</span>
      <span className="font-display text-[26px] leading-tight text-ink">
        {value}
        {unit && <span className="text-[13px] text-muted ml-1 font-sans font-normal">{unit}</span>}
      </span>
      {sub && <span className="text-[11px] text-muted">{sub}</span>}
    </div>
  )
}

// ── My Meals section ──────────────────────────────────────────────────────────

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

// ── Page ──────────────────────────────────────────────────────────────────────

export function TrendsPage() {
  const [period, setPeriod] = useState<Period>(7)
  const { data: trends = [] } = useTrends(91)
  const { data: goals } = useGoals()
  const { data: meals, isLoading: mealsLoading } = useMyMeals()

  const kcalGoal = goals?.kcal_goal ?? 2000

  const periodData = useMemo(() => {
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - (period - 1))
    const cutoffStr = cutoff.toISOString().slice(0, 10)
    return trends.filter((t) => t.date >= cutoffStr)
  }, [trends, period])

  const avgKcal = useMemo(() => {
    if (!periodData.length) return 0
    return Math.round(periodData.reduce((s, t) => s + t.kcal, 0) / periodData.length)
  }, [periodData])

  const avgProtein = useMemo(() => {
    if (!periodData.length) return 0
    return Math.round(periodData.reduce((s, t) => s + t.protein_g, 0) / periodData.length)
  }, [periodData])

  const streak = useMemo(() => {
    if (goals?.streak_days != null) return goals.streak_days
    // Compute from trend data: consecutive days ending today with n_meals > 0
    let count = 0
    const today = new Date().toISOString().slice(0, 10)
    const byDate = new Map(trends.map((t) => [t.date, t]))
    for (let i = 0; i <= 365; i++) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      const iso = d.toISOString().slice(0, 10)
      if (iso > today) continue
      const t = byDate.get(iso)
      if (t && t.n_meals > 0) {
        count++
      } else if (iso < today) {
        break
      }
    }
    return count
  }, [trends, goals?.streak_days])

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <AppSidebar />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">

          {/* Header */}
          <div className="flex items-center justify-between">
            <h1 className="font-display text-[22px] font-bold text-ink">Your patterns</h1>
            <div className="flex items-center gap-1 bg-sand rounded-xl p-1">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPeriod(p)}
                  className={`px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-colors ${
                    period === p
                      ? 'bg-paper text-ink shadow-sm'
                      : 'text-muted hover:text-ink'
                  }`}
                >
                  {PERIOD_LABELS[p]}
                </button>
              ))}
            </div>
          </div>

          {/* Stat cards */}
          <div className="grid grid-cols-3 gap-3">
            <StatCard
              label="Avg kcal"
              value={avgKcal.toLocaleString()}
              sub={kcalGoal ? `goal ${kcalGoal.toLocaleString()}` : undefined}
            />
            <StatCard label="Avg protein" value={avgProtein} unit="g" />
            <StatCard label="Streak" value={streak} unit={streak === 1 ? 'day' : 'days'} />
          </div>

          {/* Macro bar chart */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-semibold text-ink">Macro breakdown</h2>
              <div className="flex items-center gap-3 text-[11px] text-muted">
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm inline-block bg-carbs opacity-85" />
                  Carbs
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm inline-block bg-protein opacity-85" />
                  Protein
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm inline-block bg-fiber opacity-85" />
                  Fiber
                </span>
              </div>
            </div>
            <div className="card-sand p-4">
              <MacroBarChart data={trends} period={period} />
            </div>
          </section>

          {/* Consistency heatmap */}
          <TrendsSection kcalGoal={kcalGoal} />

          {/* My Meals */}
          <section className="space-y-4">
            <div className="flex items-center gap-3 border-t border-sand-border pt-6">
              <div className="w-8 h-8 rounded-xl bg-container border border-sand-border text-sage-deep flex items-center justify-center">
                <BookMarked className="w-4 h-4" />
              </div>
              <div>
                <h2 className="font-display font-semibold text-[17px] text-ink">My Meals</h2>
                <p className="text-[11px] text-muted">
                  Saved meals — log one in a tap, or customize the portion first.
                </p>
              </div>
            </div>

            {mealsLoading ? (
              <p className="text-[13px] text-muted">Loading…</p>
            ) : !meals || meals.length === 0 ? (
              <div className="card-sand p-5 text-center">
                <p className="text-[13px] text-muted">
                  No saved meals yet. Log a meal, then tap{' '}
                  <span className="font-medium text-ink">Save to My Meals</span> on the
                  confirmation card.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {meals.map((meal) => (
                  <MealRow key={meal.id} meal={meal} />
                ))}
              </div>
            )}
          </section>

        </div>
      </div>
    </div>
  )
}
