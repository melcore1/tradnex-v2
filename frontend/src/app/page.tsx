'use client'

import Link from 'next/link'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SystemStatusPanel } from '@/components/system/SystemStatusPanel'
import { useDashboardSummary } from '@/hooks/useDashboard'
import { fmtMoney } from '@/lib/format/decimal'
import { fmtRelative } from '@/lib/format/datetime'
import { Badge } from '@/components/ui/badge'

export default function DashboardPage() {
  const { data, isLoading, error } = useDashboardSummary()

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading dashboard…</p>
  }
  if (error || !data) {
    return <p className="text-sm text-destructive">Failed to load dashboard.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <SystemStatusPanel status={data.system_status} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <SummaryStat
          label="Open positions"
          value={String(data.open_positions_count)}
          accent={fmtMoney(data.open_positions_total_pnl, { withSign: true })}
        />
        <SummaryStat
          label="Pending approvals"
          value={String(data.pending_human_approvals)}
          link={{ href: '/approvals', label: 'Review' }}
        />
        <SummaryStat
          label="In LLM queue"
          value={String(data.pending_llm_evaluations)}
          link={{ href: '/settings/system', label: 'System' }}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Today&apos;s watchlist</CardTitle>
          <CardDescription>
            <Link href="/watchlist" className="underline hover:text-foreground">
              Edit
            </Link>
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.today_watchlist?.tickers?.length ? (
            <div className="flex flex-wrap gap-2">
              {data.today_watchlist.tickers.map((t) => (
                <Badge key={t} variant="secondary">
                  {t}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Empty — set today&apos;s watchlist on the Watchlist screen.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_events?.length ? (
            <ul className="flex flex-col gap-2 text-sm">
              {data.recent_events.map((e, i) => {
                const ev = e as { id?: number; service?: string; event_type?: string; level?: string; timestamp?: number }
                const tsIso = ev.timestamp ? new Date(ev.timestamp * 1000).toISOString() : null
                return (
                  <li key={ev.id ?? i} className="flex items-baseline gap-2">
                    <Badge variant={ev.level === 'error' ? 'destructive' : ev.level === 'warn' ? 'warning' : 'neutral'}>
                      {ev.service}
                    </Badge>
                    <span className="font-mono text-xs">{ev.event_type}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{fmtRelative(tsIso)}</span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No recent activity.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SummaryStat({
  label,
  value,
  accent,
  link,
}: {
  label: string
  value: string
  accent?: string
  link?: { href: string; label: string }
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 py-6">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
        <span className="text-3xl font-bold">{value}</span>
        {accent ? <span className="text-xs text-muted-foreground">{accent}</span> : null}
        {link ? (
          <Link className="text-xs text-primary underline" href={link.href}>
            {link.label} →
          </Link>
        ) : null}
      </CardContent>
    </Card>
  )
}
