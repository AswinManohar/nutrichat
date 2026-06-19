import { useDashboard, useGoals } from '../../api/hooks'
import type { MealTypeEntry } from '../../api/types'

const MEAL_META: Record<string, { emoji: string; label: string }> = {
  breakfast: { emoji: '🍳', label: 'Breakfast' },
  brunch:    { emoji: '🥞', label: 'Brunch'    },
  lunch:     { emoji: '🥗', label: 'Lunch'     },
  dinner:    { emoji: '🌙', label: 'Dinner'    },
  snack:     { emoji: '🍎', label: 'Snack'     },
}

const DISPLAY_ORDER = ['breakfast', 'lunch', 'dinner', 'snack'] as const

function DonutRing({
  value,
  max,
  size,
  stroke,
  color,
}: {
  value: number
  max: number
  size: number
  stroke: number
  color: string
}) {
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const pct = Math.min(1, max > 0 ? value / max : 0)
  const cx = size / 2

  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }} aria-hidden="true">
      <circle
        cx={cx} cy={cx} r={r} fill="none"
        stroke="var(--color-sand-border)" strokeWidth={stroke}
      />
      <circle
        cx={cx} cy={cx} r={r} fill="none"
        stroke={color} strokeWidth={stroke}
        strokeDasharray={`${pct * circ} ${circ}`}
        strokeLinecap="round"
      />
    </svg>
  )
}

function MiniRing({
  value,
  max,
  color,
  label,
  unit,
}: {
  value: number
  max: number
  color: string
  label: string
  unit: string
}) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative w-10 h-10 flex-shrink-0">
        <DonutRing value={value} max={max} size={40} stroke={5} color={color} />
      </div>
      <div>
        <p className="text-[11px] font-semibold text-muted uppercase tracking-wide leading-none mb-0.5">
          {label}
        </p>
        <p className="text-[13px] font-semibold text-ink leading-none">
          {Math.round(value)}
          <span className="text-muted font-normal"> / {max}{unit}</span>
        </p>
      </div>
    </div>
  )
}

export function ChatTodayPanel() {
  const { data: totals } = useDashboard()
  const { data: goals } = useGoals()

  const kcal = totals?.kcal ?? 0
  const kcalGoal = goals?.kcal_goal ?? 2000
  const protein = totals?.protein_g ?? 0
  const proteinGoal = goals?.protein_goal ?? 120
  const fiber = totals?.fiber_g ?? 0
  const fiberGoal = goals?.fiber_goal ?? 30
  const remaining = Math.max(0, kcalGoal - kcal)

  const byType: MealTypeEntry[] = totals?.by_type ?? []
  const displayMeals = DISPLAY_ORDER.map((type) => ({
    type,
    ...MEAL_META[type],
    entry: byType.find((e) => e.meal_type === type),
  }))

  return (
    <div className="h-full flex flex-col overflow-y-auto px-5 py-5 gap-5">
      {/* Macro rings */}
      <div className="flex items-center gap-5">
        {/* Large kcal ring */}
        <div className="relative flex-shrink-0" style={{ width: 120, height: 120 }}>
          <DonutRing
            value={kcal}
            max={kcalGoal}
            size={120}
            stroke={10}
            color="var(--color-sage)"
          />
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-[22px] font-bold text-ink leading-none tabular-nums">
              {Math.round(kcal).toLocaleString()}
            </span>
            <span className="text-[10px] font-semibold text-muted uppercase tracking-widest mt-1">
              KCAL
            </span>
          </div>
        </div>

        {/* Mini rings */}
        <div className="flex flex-col gap-3">
          <MiniRing
            value={protein}
            max={proteinGoal}
            color="var(--color-protein)"
            label="Protein"
            unit="g"
          />
          <MiniRing
            value={fiber}
            max={fiberGoal}
            color="var(--color-fiber)"
            label="Fiber"
            unit="g"
          />
        </div>
      </div>

      {/* Today's meals */}
      <div className="flex flex-col gap-1.5">
        <p className="text-[11px] font-semibold text-muted uppercase tracking-wide mb-1">
          Today's Meals
        </p>
        {displayMeals.map(({ type, emoji, label, entry }) =>
          entry ? (
            <div
              key={type}
              className="flex items-center gap-3 bg-sand rounded-xl px-3 py-2.5 border border-sand-border"
            >
              <span className="text-[18px] leading-none">{emoji}</span>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-ink">{label}</p>
                <p className="text-[11px] text-muted truncate">{entry.summary}</p>
              </div>
              <span className="text-[13px] font-semibold text-ink tabular-nums flex-shrink-0">
                {Math.round(entry.kcal)}
              </span>
            </div>
          ) : (
            <div
              key={type}
              className="flex items-center gap-3 border border-dashed border-sand-border rounded-xl px-3 py-2.5"
            >
              <span className="text-[18px] leading-none opacity-30">{emoji}</span>
              <div className="flex-1">
                <p className="text-[13px] font-medium text-muted">{label}</p>
                <p className="text-[11px] text-muted/50">Not logged yet</p>
              </div>
            </div>
          )
        )}
      </div>

      {/* Coaching bubble */}
      {remaining > 0 && (
        <div className="mt-auto flex items-start gap-3 bg-sand border border-sand-border rounded-2xl px-4 py-3">
          <div className="w-8 h-8 rounded-full bg-sage flex items-center justify-center flex-shrink-0 mt-0.5">
            <span className="text-white text-[13px]" aria-hidden="true">✦</span>
          </div>
          <p className="text-[13px] text-ink-soft leading-relaxed">
            You're on track.{' '}
            ~{Math.round(remaining).toLocaleString()} kcal left for a balanced dinner.
          </p>
        </div>
      )}
    </div>
  )
}
