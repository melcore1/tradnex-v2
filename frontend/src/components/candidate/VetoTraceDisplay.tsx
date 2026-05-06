import { Badge } from '@/components/ui/badge'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'

interface VetoTraceDisplayProps {
  trace: Record<string, unknown> | null | undefined
}

export function VetoTraceDisplay({ trace }: VetoTraceDisplayProps) {
  if (!trace) return <p className="text-sm text-muted-foreground">No veto trace available.</p>

  const vetoes = (trace.vetoes as Array<Record<string, unknown>>) ?? []

  const formatted = (
    <ul className="flex flex-col gap-1 text-sm">
      {vetoes.map((v, idx) => {
        const failed = Boolean(v.failed)
        const name = (v.veto_name as string) ?? `veto_${idx}`
        const reason = (v.reason as string) ?? ''
        return (
          <li key={idx} className="flex items-start gap-2">
            <Badge variant={failed ? 'destructive' : 'success'}>{failed ? 'BLOCK' : 'OK'}</Badge>
            <div>
              <span className="font-mono text-xs">{name}</span>
              {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
            </div>
          </li>
        )
      })}
    </ul>
  )

  return <RawJsonToggle formatted={formatted} raw={trace} />
}
