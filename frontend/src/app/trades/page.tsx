'use client'

import { useActiveTrades } from '@/hooks/useDashboard'
import { PositionCard } from '@/components/position/PositionCard'
import { Card, CardContent } from '@/components/ui/card'

export default function TradesPage() {
  const { data, isLoading, error } = useActiveTrades()

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Active trades</h1>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading positions…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Failed to load.</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No open positions.
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((t) => (
            <PositionCard key={t.position.id} trade={t} />
          ))}
        </div>
      )}
    </div>
  )
}
