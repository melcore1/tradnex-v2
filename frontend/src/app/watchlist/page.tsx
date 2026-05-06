'use client'

import { useState, useMemo, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useMorningView } from '@/hooks/useDashboard'
import { useSetWatchlist } from '@/hooks/useWatchlist'
import { fmtRelative } from '@/lib/format/datetime'

export default function WatchlistPage() {
  const { data, isLoading, error } = useMorningView()
  const setMutation = useSetWatchlist()

  const universe = useMemo(() => data?.universe ?? [], [data])
  const initialSelected = useMemo(
    () => new Set(data?.today_watchlist?.tickers ?? []),
    [data],
  )

  const [selected, setSelected] = useState<Set<string>>(initialSelected)

  // Sync local state when data refetches
  useEffect(() => {
    setSelected(new Set(data?.today_watchlist?.tickers ?? []))
  }, [data])

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading morning view…</p>
  if (error || !data) return <p className="text-sm text-destructive">Failed to load.</p>

  const toggle = (ticker: string) => {
    const next = new Set(selected)
    if (next.has(ticker)) next.delete(ticker)
    else next.add(ticker)
    setSelected(next)
  }

  const save = () => {
    setMutation.mutate({
      tickers: [...selected].sort(),
      per_ticker_overrides: data.today_watchlist?.per_ticker_overrides ?? {},
      notes: data.today_watchlist?.notes ?? undefined,
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Today&apos;s watchlist</h1>

      <Card>
        <CardHeader>
          <CardTitle>Calendar — next 7 days</CardTitle>
        </CardHeader>
        <CardContent>
          {data.upcoming_calendar.length ? (
            <ul className="flex flex-col gap-1 text-sm">
              {data.upcoming_calendar.map((e, i) => {
                const ev = e as { event_type?: string; ticker?: string; date?: string; time?: string }
                return (
                  <li key={i} className="flex items-baseline gap-2">
                    <Badge variant="info">{ev.event_type ?? '—'}</Badge>
                    <span className="font-mono text-xs">{ev.ticker ?? '—'}</span>
                    <span className="text-xs text-muted-foreground">{ev.date ?? ''}</span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No upcoming events.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pre-market gaps</CardTitle>
          <CardDescription>Detected on universe tickers</CardDescription>
        </CardHeader>
        <CardContent>
          {data.pre_market_gaps.length ? (
            <pre className="overflow-auto text-xs">{JSON.stringify(data.pre_market_gaps, null, 2)}</pre>
          ) : (
            <p className="text-sm text-muted-foreground">No gaps.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configure today&apos;s watchlist</CardTitle>
          <CardDescription>
            Tap a ticker to toggle. {selected.size} of {universe.length} selected.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {universe.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Universe is empty — add tickers in Settings → Universe.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {universe.map((t) => {
                const on = selected.has(t)
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => toggle(t)}
                    className="tap-target"
                    aria-pressed={on}
                  >
                    <Badge variant={on ? 'success' : 'neutral'}>{t}</Badge>
                  </button>
                )
              })}
            </div>
          )}
          <div className="mt-4 flex gap-2">
            <Button onClick={save} disabled={setMutation.isPending}>
              {setMutation.isPending ? 'Saving…' : 'Save watchlist'}
            </Button>
            {data.today_watchlist ? (
              <span className="self-center text-xs text-muted-foreground">
                last updated {fmtRelative(data.today_watchlist.date)}
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
