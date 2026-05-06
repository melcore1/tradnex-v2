'use client'

import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ModeBadge } from '@/components/shared/ModeBadge'
import { deriveSystemDisplay } from '@/lib/format/system'
import type { SystemStatusResponse } from '@/lib/api/system'

interface SystemStatusPanelProps {
  status: SystemStatusResponse
}

export function SystemStatusPanel({ status }: SystemStatusPanelProps) {
  const display = deriveSystemDisplay(status)
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-4 py-4">
        <ToggleStatus label="Scanner" enabled={display.scanner.enabled} override={display.scanner.override} />
        <ToggleStatus label="Monitor" enabled={display.monitor.enabled} override={display.monitor.override} />
        <ToggleStatus label="LLM" enabled={display.llm.enabled} override={display.llm.override} />
        <div className="ml-auto flex items-center gap-2">
          <ModeBadge mode={display.mode} />
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground" role="group" aria-label="Queue stats">
          <span>queue: {status.queue_depth}</span>
          <span>in flight: {status.queue_in_flight}</span>
          <span>open: {status.open_positions}</span>
          <span>pending: {status.pending_human_approvals}</span>
        </div>
      </CardContent>
    </Card>
  )
}

function ToggleStatus({
  label,
  enabled,
  override,
}: {
  label: string
  enabled: boolean
  override: string | null
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{label}</span>
        <Badge variant={enabled ? 'success' : 'destructive'}>{enabled ? 'ON' : 'OFF'}</Badge>
      </div>
      {override ? (
        <span className="text-xs text-warning" role="status">
          {override}
        </span>
      ) : null}
    </div>
  )
}
