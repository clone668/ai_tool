import { statusLabels } from '../format'
import type { HealthStatus } from '../types'

interface StatusBadgeProps {
  status: HealthStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge ${status}`}>
      <span className={`status-dot ${status}`} />
      {statusLabels[status]}
    </span>
  )
}
