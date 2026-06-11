import { useEffect, useState } from 'react'
import type { TodayTotals, GoalData } from '../../api/types'

interface RingProps {
  pct: number
  size: number
  stroke: number
  trackWidth: number
  colorVar: string
  children?: React.ReactNode
}

/** SVG progress ring that eases from 0 to pct on mount. */
function Ring({ pct, size, stroke, trackWidth, colorVar, children }: RingProps) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true))
    return () => cancelAnimationFrame(id)
  }, [])

  const r = size / 2 - stroke
  const c = 2 * Math.PI * r
  const shown = mounted ? Math.min(100, pct) : 0
  const offset = c - (shown / 100) * c

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="transparent"
          stroke="var(--color-container-high)"
          strokeWidth={trackWidth}
        />
        <circle
          className="ring-progress"
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="transparent"
          stroke={`var(${colorVar})`}
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  )
}

interface MacroRingsProps {
  totals?: TodayTotals
  goals?: GoalData
}

export function MacroRings({ totals, goals }: MacroRingsProps) {
  const kcal = totals?.kcal ?? 0
  const protein = totals?.protein_g ?? 0
  const fiber = totals?.fiber_g ?? 0

  const kcalGoal = goals?.kcal_goal ?? 2000
  const proteinGoal = goals?.protein_goal ?? 120
  const fiberGoal = goals?.fiber_goal ?? 30

  return (
    <div className="card-sand p-6 flex items-center justify-around gap-6">
      {/* Primary kcal ring */}
      <Ring pct={(kcal / kcalGoal) * 100} size={136} stroke={8} trackWidth={4} colorVar="--color-sage">
        <span className="font-display text-[32px] leading-none text-ink">
          {Math.round(kcal).toLocaleString()}
        </span>
        <span className="label-caps mt-1 text-[10px]">kcal</span>
      </Ring>

      {/* Mini rings */}
      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-3">
          <Ring pct={(protein / proteinGoal) * 100} size={44} stroke={4} trackWidth={2} colorVar="--color-protein" />
          <div>
            <p className="label-caps">Protein</p>
            <p className="text-[16px] font-semibold text-ink-soft">
              {Math.round(protein)}g <span className="font-normal text-muted">/ {Math.round(proteinGoal)}g</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Ring pct={(fiber / fiberGoal) * 100} size={44} stroke={4} trackWidth={2} colorVar="--color-fiber" />
          <div>
            <p className="label-caps">Fiber</p>
            <p className="text-[16px] font-semibold text-ink-soft">
              {Math.round(fiber)}g <span className="font-normal text-muted">/ {Math.round(fiberGoal)}g</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
