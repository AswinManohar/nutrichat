import { AlertTriangle, ExternalLink } from 'lucide-react'
import type { MindfulAlert } from '../../api/types'

interface SafetyAlertCardProps {
  alert: MindfulAlert
}

export function SafetyAlertCard({ alert }: SafetyAlertCardProps) {
  return (
    <div className="rounded-xl border border-warn/50 bg-warn/10 p-3.5 space-y-1.5">
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-danger shrink-0" />
        <span className="text-[13px] font-semibold text-ink">
          {alert.nutrient} above recommended limit
        </span>
      </div>
      <p className="text-[12px] text-ink-soft">
        You've had <strong>{Math.round(alert.amount)}{alert.unit}</strong> today —
        the recommended daily upper limit is{' '}
        <strong>{Math.round(alert.limit)}{alert.unit}</strong>.
      </p>
      <a
        href={alert.url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-[11px] text-sage-deep hover:underline"
      >
        {alert.source}
        <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  )
}
