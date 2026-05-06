'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { CopyButton } from '@/components/shared/CopyButton'
import { fmtMoney } from '@/lib/format/decimal'
import { useJournal } from '@/hooks/useDashboard'
import { todayIsoDate } from '@/lib/format/datetime'

export default function JournalPage() {
  const [date, setDate] = useState(todayIsoDate())
  const { data, isLoading, error } = useJournal(date)

  const journalText = data
    ? [
        `# Journal — ${data.date}`,
        ``,
        `Scanner cycles: ${data.scanner_cycles_run}`,
        `Candidates fired: ${data.candidates_fired}`,
        ``,
        `## Decisions`,
        ...Object.entries(data.decisions).map(([k, v]) => `- ${k}: ${v}`),
        ``,
        `## P&L`,
        `${fmtMoney(data.pnl_dollars, { withSign: true })}`,
        ``,
        `## Position state changes`,
        JSON.stringify(data.position_state_changes, null, 2),
      ].join('\n')
    : ''

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-bold">Journal</h1>
        <div className="flex items-end gap-2">
          <div>
            <Label htmlFor="journal-date" className="text-xs">
              Date
            </Label>
            <Input
              id="journal-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <CopyButton text={journalText} label="Copy summary" />
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading journal…</p>
      ) : error || !data ? (
        <p className="text-sm text-destructive">Failed to load.</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <StatCard label="Cycles run" value={String(data.scanner_cycles_run)} />
            <StatCard label="Candidates fired" value={String(data.candidates_fired)} />
            <StatCard label="P&L" value={fmtMoney(data.pnl_dollars, { withSign: true })} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Decisions</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-wrap gap-2 text-sm">
                {Object.entries(data.decisions).map(([k, v]) => (
                  <li key={k}>
                    <Badge variant="info">
                      {k}: {v}
                    </Badge>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Position state changes</CardTitle>
            </CardHeader>
            <CardContent>
              {data.position_state_changes.length ? (
                <pre className="overflow-auto text-xs">
                  {JSON.stringify(data.position_state_changes, null, 2)}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground">No state changes.</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 py-6">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
        <span className="text-3xl font-bold">{value}</span>
      </CardContent>
    </Card>
  )
}
