import { Badge } from '@/components/ui/badge'
import { fmtRelative } from '@/lib/format/datetime'

interface LifecycleTimelineProps {
  events: Array<Record<string, unknown>> | undefined
}

export function LifecycleTimeline({ events }: LifecycleTimelineProps) {
  if (!events?.length) {
    return <p className="text-sm text-muted-foreground">No lifecycle events.</p>
  }
  return (
    <ol className="flex flex-col gap-2 text-sm">
      {events.map((e, i) => {
        const ev = e as { id?: number; event_type?: string; timestamp?: string; payload?: unknown }
        return (
          <li key={ev.id ?? i} className="flex items-baseline gap-2">
            <Badge variant="info">{ev.event_type ?? '—'}</Badge>
            <span className="text-xs text-muted-foreground">{fmtRelative(ev.timestamp)}</span>
          </li>
        )
      })}
    </ol>
  )
}
