import { useMemo, useState } from 'react'
import { useTrends } from '../../api/hooks'
import type { DayTrend } from '../../api/types'

const WEEKS = 13 // ~one quarter, GitHub-style
const DAY_MS = 86_400_000

/** Heatmap intensity: how close the day's kcal landed to the goal. */
function cellColor(kcal: number, goal: number): string {
  if (kcal <= 0) return 'var(--color-container-high)'
  const ratio = kcal / goal
  if (ratio < 0.35) return '#d9e2d6'
  if (ratio < 0.7) return '#b5c4b1'
  if (ratio <= 1.1) return 'var(--color-sage)' // on target
  if (ratio <= 1.3) return 'var(--color-sage-deep)'
  return 'var(--color-warn)' // well over goal
}

function isoDaysAgo(n: number): string {
  return new Date(Date.now() - n * DAY_MS).toISOString().slice(0, 10)
}

interface TrendsSectionProps {
  kcalGoal: number
}

export function TrendsSection({ kcalGoal }: TrendsSectionProps) {
  const { data: trends } = useTrends(WEEKS * 7)
  const [hovered, setHovered] = useState<DayTrend | null>(null)

  const byDate = useMemo(() => {
    const map = new Map<string, DayTrend>()
    for (const t of trends ?? []) map.set(t.date, t)
    return map
  }, [trends])

  // Grid: columns = weeks (oldest → newest), rows = Mon..Sun, like GitHub
  const columns = useMemo(() => {
    const today = new Date()
    const todayDow = (today.getDay() + 6) % 7 // Mon=0
    const cols: (DayTrend | { date: string; future?: boolean } | null)[][] = []
    for (let w = WEEKS - 1; w >= 0; w--) {
      const col: (DayTrend | { date: string; future?: boolean } | null)[] = []
      for (let d = 0; d < 7; d++) {
        const daysAgo = w * 7 + (todayDow - d)
        if (daysAgo < 0) {
          col.push(null) // future day this week
        } else {
          const iso = isoDaysAgo(daysAgo)
          col.push(byDate.get(iso) ?? { date: iso })
        }
      }
      cols.push(col)
    }
    return cols
  }, [byDate])

  // Sparkline: last 30 days, gaps as 0
  const spark = useMemo(() => {
    const days: number[] = []
    for (let i = 29; i >= 0; i--) days.push(byDate.get(isoDaysAgo(i))?.kcal ?? 0)
    return days
  }, [byDate])

  const sparkMax = Math.max(kcalGoal * 1.2, ...spark)
  const W = 300
  const H = 56
  const points = spark
    .map((v, i) => `${((i / 29) * W).toFixed(1)},${(H - (v / sparkMax) * H).toFixed(1)}`)
    .join(' ')
  const goalY = H - (kcalGoal / sparkMax) * H

  const junkDays = (trends ?? []).filter((t) => t.junk_meals > 0).length
  const loggedDays = (trends ?? []).length

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="label-caps">Last {WEEKS} weeks</h3>
        <span className="text-[11px] text-muted h-4">
          {hovered
            ? `${hovered.date} · ${Math.round(hovered.kcal)} kcal · ${hovered.n_meals} meal${
                hovered.n_meals === 1 ? '' : 's'
              }${hovered.junk_meals > 0 ? ` · ${hovered.junk_meals} junk` : ''}`
            : loggedDays > 0
              ? `${loggedDays} day${loggedDays === 1 ? '' : 's'} logged${
                  junkDays > 0 ? ` · junk on ${junkDays}` : ''
                }`
              : ''}
        </span>
      </div>

      <div className="card-sand p-4 space-y-4">
        {/* Heatmap */}
        <div className="flex gap-[3px] justify-between">
          {columns.map((col, w) => (
            <div key={w} className="flex flex-col gap-[3px] flex-1">
              {col.map((cell, d) => {
                if (cell === null) return <div key={d} className="aspect-square rounded-[3px]" />
                const t = 'kcal' in cell ? (cell as DayTrend) : null
                return (
                  <div
                    key={d}
                    onMouseEnter={() => t && setHovered(t)}
                    onMouseLeave={() => setHovered(null)}
                    className="relative aspect-square rounded-[3px] transition-transform duration-150 hover:scale-125"
                    style={{ background: cellColor(t?.kcal ?? 0, kcalGoal) }}
                    title={cell.date}
                  >
                    {t && t.junk_meals > 0 && (
                      <span className="absolute inset-0 m-auto w-1 h-1 rounded-full bg-warn" />
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center justify-between text-[10px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-warn inline-block" /> junk food day
          </span>
          <span className="flex items-center gap-1">
            under
            {['#d9e2d6', '#b5c4b1', 'var(--color-sage)', 'var(--color-sage-deep)', 'var(--color-warn)'].map(
              (c) => (
                <span key={c} className="w-2.5 h-2.5 rounded-[2px] inline-block" style={{ background: c }} />
              )
            )}
            over
          </span>
        </div>

        {/* Calorie sparkline, 30 days */}
        <div className="pt-1 border-t border-sand-border">
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="label-caps text-[9px]">Calories · 30 days</span>
            <span className="text-[10px] text-muted">goal {Math.round(kcalGoal).toLocaleString()}</span>
          </div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-14" preserveAspectRatio="none">
            <line
              x1="0"
              y1={goalY}
              x2={W}
              y2={goalY}
              stroke="var(--color-sand-border)"
              strokeWidth="1"
              strokeDasharray="4 3"
            />
            <polyline
              points={`0,${H} ${points} ${W},${H}`}
              fill="color-mix(in srgb, var(--color-sage) 12%, transparent)"
              stroke="none"
            />
            <polyline
              points={points}
              fill="none"
              stroke="var(--color-sage)"
              strokeWidth="1.75"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </svg>
        </div>
      </div>
    </section>
  )
}
