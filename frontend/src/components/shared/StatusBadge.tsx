import { Badge } from '@/components/ui/badge'
import { describeStatus, type StatusTone } from '@/lib/format/status'

const TONE_MAP: Record<StatusTone, 'default' | 'secondary' | 'destructive' | 'success' | 'warning' | 'info' | 'pending' | 'neutral'> = {
  neutral: 'neutral',
  info: 'info',
  warning: 'warning',
  success: 'success',
  destructive: 'destructive',
  pending: 'pending',
}

export function StatusBadge({ status }: { status: string }) {
  const { label, tone } = describeStatus(status)
  return <Badge variant={TONE_MAP[tone]}>{label}</Badge>
}
