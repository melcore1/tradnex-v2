'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useSettings, usePatchSettings } from '@/hooks/useSettings'
import { toast } from '@/components/ui/sonner'

export default function StrategySettingsPage() {
  const { data, isLoading, error } = useSettings()
  const patch = usePatchSettings()
  const [draft, setDraft] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)

  useEffect(() => {
    if (data) {
      setDraft(JSON.stringify(data.settings_json, null, 2))
    }
  }, [data])

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (error || !data) return <p className="text-sm text-destructive">Failed to load.</p>

  const save = () => {
    try {
      const parsed = JSON.parse(draft)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setParseError('Must be a JSON object')
        return
      }
      setParseError(null)
      patch.mutate({ updates: parsed })
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Invalid JSON')
      toast.error('Invalid JSON')
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy settings</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 text-xs text-muted-foreground">
          Edit the entire <code>strategy_configs.settings_json</code> blob. PATCH merges keys (existing keys are preserved).
        </p>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="min-h-[400px] font-mono text-xs"
        />
        {parseError ? <p className="mt-2 text-xs text-destructive">{parseError}</p> : null}
        <div className="mt-3 flex gap-2">
          <Button onClick={save} disabled={patch.isPending}>
            {patch.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button
            variant="ghost"
            onClick={() => setDraft(JSON.stringify(data.settings_json, null, 2))}
          >
            Reset
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
