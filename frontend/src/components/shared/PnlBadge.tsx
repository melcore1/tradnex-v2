import { Badge } from '@/components/ui/badge'
import { fmtPct } from '@/lib/format/decimal'

interface PnlBadgeProps {
  pct: string | number | null | undefined
}

export function PnlBadge({ pct }: PnlBadgeProps) {
  if (pct === null || pct === undefined) return <Badge variant="neutral">—</Badge>
  const n = typeof pct === 'number' ? pct : Number(pct)
  if (Number.isNaN(n)) return <Badge variant="neutral">—</Badge>
  const variant = n >= 0 ? 'success' : 'destructive'
  return <Badge variant={variant}>{fmtPct(n, { withSign: true })}</Badge>
}
