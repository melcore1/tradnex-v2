'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CopyButton } from './CopyButton'
import type { ReactNode } from 'react'

interface RawJsonToggleProps {
  formatted: ReactNode
  raw: unknown
  label?: string
  /** Default tab. */
  defaultValue?: 'formatted' | 'raw'
}

export function RawJsonToggle({
  formatted,
  raw,
  label = 'Raw JSON',
  defaultValue = 'formatted',
}: RawJsonToggleProps) {
  const rawString = JSON.stringify(raw, null, 2)
  return (
    <Tabs defaultValue={defaultValue} className="w-full">
      <div className="flex items-center justify-between">
        <TabsList>
          <TabsTrigger value="formatted">View</TabsTrigger>
          <TabsTrigger value="raw">{label}</TabsTrigger>
        </TabsList>
        <CopyButton text={rawString} label="Copy JSON" />
      </div>
      <TabsContent value="formatted">{formatted}</TabsContent>
      <TabsContent value="raw">
        <pre className="overflow-auto rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap break-all max-h-96">
          <code>{rawString}</code>
        </pre>
      </TabsContent>
    </Tabs>
  )
}
