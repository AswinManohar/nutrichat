import { useMindfulToday } from '../../api/hooks'
import { SafetyAlertCard } from './SafetyAlertCard'

function formatAmount(amount: number): string {
  return amount >= 100 ? Math.round(amount).toString() : amount.toFixed(1)
}

export function MindfulPanel() {
  const { data, isLoading } = useMindfulToday()

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h3 className="label-caps">Consumed today</h3>
        {isLoading ? (
          <p className="text-[12px] text-muted">Loading…</p>
        ) : !data || data.nutrients.length === 0 ? (
          <p className="text-[12px] text-muted">
            Nothing logged yet. Tell the chat what you ate — no targets, just the
            facts.
          </p>
        ) : (
          <div className="card-sand p-4 divide-y divide-sand-border">
            {data.nutrients.map((n) => (
              <div
                key={n.name}
                className="flex items-baseline justify-between py-2 first:pt-0 last:pb-0"
              >
                <span className="text-[13px] text-ink">{n.name}</span>
                <span className="text-[13px] font-semibold text-ink tabular-nums">
                  {formatAmount(n.amount)}
                  <span className="text-[11px] text-muted ml-0.5">{n.unit}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {data && data.alerts.length > 0 && (
        <section className="space-y-2">
          <h3 className="label-caps">Safety alerts</h3>
          {data.alerts.map((a) => (
            <SafetyAlertCard key={a.nutrient} alert={a} />
          ))}
        </section>
      )}
    </div>
  )
}
