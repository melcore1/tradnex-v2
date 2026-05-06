'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useUniverse, useAddUniverseTicker, useRemoveUniverseTicker } from '@/hooks/useWatchlist'
import { X } from 'lucide-react'

export default function UniverseSettingsPage() {
  const { data, isLoading, error } = useUniverse()
  const add = useAddUniverseTicker()
  const remove = useRemoveUniverseTicker()
  const [ticker, setTicker] = useState('')

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (error || !data) return <p className="text-sm text-destructive">Failed to load.</p>

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Add ticker</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="NVDA"
              className="max-w-32 font-mono"
              maxLength={5}
              pattern="[A-Z]+"
            />
            <Button
              onClick={() => {
                add.mutate(ticker)
                setTicker('')
              }}
              disabled={!ticker || add.isPending}
            >
              Add
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Universe ({data.tickers.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {data.tickers.length === 0 ? (
            <p className="text-sm text-muted-foreground">Empty.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {data.tickers.map((t) => (
                <li key={t} className="flex items-center gap-1 rounded-md border bg-secondary px-2 py-1">
                  <Badge variant="neutral" className="font-mono">
                    {t}
                  </Badge>
                  <button
                    type="button"
                    onClick={() => remove.mutate(t)}
                    disabled={remove.isPending}
                    aria-label={`Remove ${t}`}
                    className="tap-target text-muted-foreground hover:text-destructive"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
