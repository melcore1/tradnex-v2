import { Badge } from '@/components/ui/badge'

export function ModeBadge({ mode }: { mode: 'paper' | 'live' }) {
  if (mode === 'live') {
    return <Badge variant="destructive">[LIVE]</Badge>
  }
  return <Badge variant="success">[PAPER]</Badge>
}
