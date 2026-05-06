'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { useSystemStatus, useToggle } from '@/hooks/useSystemStatus'
import { deriveSystemDisplay } from '@/lib/format/system'
import { ModeBadge } from '@/components/shared/ModeBadge'
import type { ToggleName } from '@/lib/api/system'

export default function SystemSettingsPage() {
  const { data, isLoading, error } = useSystemStatus()
  const toggle = useToggle()

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (error || !data) return <p className="text-sm text-destructive">Failed to load.</p>

  const display = deriveSystemDisplay(data)

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Trading mode</CardTitle>
            <CardDescription>Phase 7 ships paper-only; live arrives in Phase 8.</CardDescription>
          </div>
          <ModeBadge mode={display.mode} />
        </CardHeader>
      </Card>

      <ToggleRow
        title="Scanner"
        description="Periodically scans the watchlist for entry candidates."
        enabled={display.scanner.enabled}
        override={display.scanner.override}
        onChange={(v) => toggle.mutate({ name: 'paused', enabled: v })}
        disabled={toggle.isPending}
      />
      <ToggleRow
        title="Monitor"
        description="Evaluates open positions for exit signals every cycle."
        enabled={display.monitor.enabled}
        override={display.monitor.override}
        onChange={(v) => toggle.mutate({ name: 'monitor_paused', enabled: v })}
        disabled={toggle.isPending}
      />
      <ToggleRow
        title="LLM evaluator"
        description="Routes pending candidates through Claude. When off, the rule-based fallback runs instead."
        enabled={display.llm.enabled}
        override={display.llm.override}
        onChange={(v) => toggle.mutate({ name: 'llm_enabled' as ToggleName, enabled: v })}
        disabled={toggle.isPending}
      />

      <Card>
        <CardHeader>
          <CardTitle>Queue</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            <Stat label="Queue depth" value={data.queue_depth} />
            <Stat label="In flight" value={data.queue_in_flight} />
            <Stat label="Open positions" value={data.open_positions} />
            <Stat label="Pending approvals" value={data.pending_human_approvals} />
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}

function ToggleRow({
  title,
  description,
  enabled,
  override,
  onChange,
  disabled,
}: {
  title: string
  description: string
  enabled: boolean
  override: string | null
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4">
        <div className="flex-1">
          <Label className="text-base">{title}</Label>
          <p className="text-xs text-muted-foreground">{description}</p>
          {override ? <p className="mt-1 text-xs text-warning">{override}</p> : null}
        </div>
        <Switch checked={enabled} onCheckedChange={onChange} disabled={disabled} aria-label={`Toggle ${title}`} />
      </CardContent>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold">{value}</dd>
    </div>
  )
}
