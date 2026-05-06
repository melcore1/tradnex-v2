import { Badge } from '@/components/ui/badge'
import { describeConfidence } from '@/lib/format/status'

const TONE_MAP = {
  neutral: 'neutral',
  info: 'info',
  warning: 'warning',
  success: 'success',
  destructive: 'destructive',
  pending: 'pending',
} as const

export function ConfidenceBadge({ confidence }: { confidence: string | null | undefined }) {
  const { label, tone } = describeConfidence(confidence)
  return <Badge variant={TONE_MAP[tone]}>{label}</Badge>
}
