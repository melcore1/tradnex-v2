'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PnlBadge } from '@/components/shared/PnlBadge'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { LifecycleTimeline } from './LifecycleTimeline'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'
import { usePositionLifecycle } from '@/hooks/usePositions'
import type { PositionSummary } from '@/lib/api/positions'
import type { ActiveTrade } from '@/lib/api/dashboard'
import { fmtMoney, fmtNumber } from '@/lib/format/decimal'

interface PositionCardProps {
  trade: ActiveTrade | { position: PositionSummary; latest_monitor_evaluation?: Record<string, unknown> | null }
}

export function PositionCard({ trade }: PositionCardProps) {
  const p = trade.position
  const { data: lifecycle } = usePositionLifecycle(p.id)
  const monitor = trade.latest_monitor_evaluation
  const dte = monitor && (monitor.dte_remaining as number | null)

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="font-mono text-base">{p.contract_symbol}</CardTitle>
            <CardDescription>
              {p.ticker} · {p.side} · qty {p.quantity} · entry {fmtMoney(p.entry_price)}
              {dte !== null && dte !== undefined ? ` · DTE ${dte}` : ''}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={p.status} />
            <PnlBadge pct={p.pnl_pct} />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="status">
          <TabsList>
            <TabsTrigger value="status">Status</TabsTrigger>
            <TabsTrigger value="signals">Signals</TabsTrigger>
            <TabsTrigger value="lifecycle">Lifecycle</TabsTrigger>
          </TabsList>
          <TabsContent value="status" className="pt-3">
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">P&L $</dt>
                <dd>{fmtMoney(p.pnl, { withSign: true })}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">P&L %</dt>
                <dd>
                  <PnlBadge pct={p.pnl_pct} />
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Quantity</dt>
                <dd>{fmtNumber(p.quantity, 0)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Entry price</dt>
                <dd>{fmtMoney(p.entry_price)}</dd>
              </div>
            </dl>
          </TabsContent>
          <TabsContent value="signals" className="pt-3">
            {monitor ? (
              <RawJsonToggle formatted={<p className="text-sm text-muted-foreground">View raw JSON for full signal trace.</p>} raw={monitor} />
            ) : (
              <p className="text-sm text-muted-foreground">No monitor evaluation yet.</p>
            )}
          </TabsContent>
          <TabsContent value="lifecycle" className="pt-3">
            <LifecycleTimeline events={lifecycle} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
