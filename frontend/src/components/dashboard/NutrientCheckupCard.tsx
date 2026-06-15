import { useNutrientCheckup } from '../../api/hooks'
import type { NutrientCheckupItem } from '../../api/types'

const DIRECTION_COLOR: Record<NutrientCheckupItem['direction'], string> = {
  up: 'var(--color-sage)',
  down: 'var(--color-warn)',
  flat: 'var(--color-muted)',
}

const DIRECTION_ARROW: Record<NutrientCheckupItem['direction'], string> = {
  up: '↑',
  down: '↓',
  flat: '→',
}

function formatAmount(value: number): string {
  return value >= 100 ? Math.round(value).toString() : value.toFixed(1)
}

/**
 * Horizontal bar for this week's average, with ticks marking last week's
 * average and the daily RDA target.
 */
function NutrientBar({ item, color }: { item: NutrientCheckupItem; color: string }) {
  const rdaAmount =
    item.rda_pct !== null && item.rda_pct > 0 && item.avg > 0
      ? item.avg / (item.rda_pct / 100)
      : null
  const max = Math.max(item.avg, item.prev_avg, rdaAmount ?? 1e-6)
  const avgPct = Math.min(100, (item.avg / max) * 100)
  const prevPct = Math.min(100, (item.prev_avg / max) * 100)
  const rdaPct = rdaAmount !== null ? Math.min(100, (rdaAmount / max) * 100) : null

  return (
    <div className="relative h-1.5 rounded-full bg-[var(--color-sand-border)] overflow-hidden">
      <div
        className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-300"
        style={{ width: `${avgPct}%`, background: color }}
      />
      {item.prev_avg > 0 && (
        <div
          className="absolute inset-y-0 w-px bg-ink-soft/50"
          style={{ left: `${prevPct}%` }}
          title="Last week's average"
        />
      )}
      {rdaPct !== null && (
        <div
          className="absolute inset-y-0 w-px bg-sage-deep/50"
          style={{ left: `${rdaPct}%` }}
          title="Daily recommended target"
        />
      )}
    </div>
  )
}

function NutrientRow({ item }: { item: NutrientCheckupItem }) {
  const color = DIRECTION_COLOR[item.direction]
  const arrow = DIRECTION_ARROW[item.direction]
  const trendLabel =
    item.trend_pct === null ? '' : `${arrow} ${Math.abs(Math.round(item.trend_pct * 100))}%`

  return (
    <div className="py-1.5 space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-ink">{item.name}</span>
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-ink-soft">
            {formatAmount(item.avg)} {item.unit}/day
          </span>
          {trendLabel && (
            <span className="text-xs font-medium tabular-nums" style={{ color }}>
              {trendLabel}
            </span>
          )}
        </div>
      </div>
      <NutrientBar item={item} color={color} />
    </div>
  )
}

export function NutrientCheckupCard() {
  const { data, isLoading, error } = useNutrientCheckup()

  if (isLoading) return null

  return (
    <section className="space-y-3">
      <h3 className="label-caps">Weekly Nutrient Check-up</h3>
      <div className="card-sand p-4">
        {error || !data || data.nutrients.length === 0 ? (
          <p className="text-sm text-muted">
            Log meals for a few days and your weekly nutrient averages will show up here.
          </p>
        ) : (
          <>
            {data.summary_text && (
              <p className="text-sm text-sage-deep mb-3">{data.summary_text}</p>
            )}
            <div className="divide-y divide-sand-border">
              {data.nutrients.map((item) => (
                <NutrientRow key={item.name} item={item} />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
