import { Badge } from '@/components/ui/badge'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'

interface RuleTraceDisplayProps {
  trace: Record<string, unknown> | null | undefined
}

export function RuleTraceDisplay({ trace }: RuleTraceDisplayProps) {
  if (!trace) return <p className="text-sm text-muted-foreground">No rule trace available.</p>

  const rules = (trace.rules as Array<Record<string, unknown>>) ?? []
  const confidence = (trace.confidence_label as string) ?? null

  const formatted = (
    <div className="flex flex-col gap-2">
      {confidence ? (
        <div className="flex items-center gap-2 text-sm">
          <span>Confidence:</span>
          <Badge variant={confidence === 'STRONG' ? 'success' : confidence === 'WEAK' ? 'warning' : 'info'}>
            {confidence}
          </Badge>
        </div>
      ) : null}
      <ul className="flex flex-col gap-1 text-sm">
        {rules.map((r, idx) => {
          const passed = Boolean(r.passed)
          const name = (r.rule_name as string) ?? `rule_${idx}`
          const reason = (r.reason as string) ?? ''
          return (
            <li key={idx} className="flex items-start gap-2">
              <Badge variant={passed ? 'success' : 'destructive'}>{passed ? 'PASS' : 'FAIL'}</Badge>
              <div>
                <span className="font-mono text-xs">{name}</span>
                {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )

  return <RawJsonToggle formatted={formatted} raw={trace} />
}
