import { Badge } from '@/components/ui/badge'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'

interface LlmEvaluationDisplayProps {
  evaluation: Record<string, unknown> | null | undefined
}

export function LlmEvaluationDisplay({ evaluation }: LlmEvaluationDisplayProps) {
  if (!evaluation) return <p className="text-sm text-muted-foreground">No LLM evaluation available.</p>

  const decision = (evaluation.decision as string) ?? null
  const reasoning = (evaluation.reasoning as string) ?? ''
  const confidence = (evaluation.confidence as number | null) ?? null
  const fallback = Boolean(evaluation.fallback_used)
  const fallbackReason = (evaluation.fallback_reason as string | null) ?? null
  const model = (evaluation.model_used as string) ?? null
  const elapsed = (evaluation.elapsed_ms as number | null) ?? null

  const formatted = (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {decision ? (
          <Badge
            variant={
              decision === 'STRONG' || decision === 'CLOSE'
                ? 'success'
                : decision === 'VETO' || decision === 'REJECT'
                  ? 'destructive'
                  : 'info'
            }
          >
            {decision}
          </Badge>
        ) : null}
        {fallback ? <Badge variant="warning">Fallback ({fallbackReason ?? 'unknown'})</Badge> : null}
        {confidence !== null ? (
          <span className="text-xs text-muted-foreground">conf: {confidence.toFixed(2)}</span>
        ) : null}
        {model ? <span className="text-xs text-muted-foreground">{model}</span> : null}
        {elapsed !== null ? <span className="text-xs text-muted-foreground">{elapsed} ms</span> : null}
      </div>
      {reasoning ? <p className="whitespace-pre-wrap text-sm">{reasoning}</p> : null}
    </div>
  )

  return <RawJsonToggle formatted={formatted} raw={evaluation} />
}
