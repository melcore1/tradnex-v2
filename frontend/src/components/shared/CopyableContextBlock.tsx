'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CopyButton } from './CopyButton'

interface CopyableContextBlockProps {
  text: string
  title?: string
}

export function CopyableContextBlock({
  text,
  title = 'Full Context',
}: CopyableContextBlockProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>{title}</CardTitle>
        <CopyButton text={text} label="Copy for Claude.ai" />
      </CardHeader>
      <CardContent>
        <pre className="overflow-auto rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap break-all max-h-96">
          <code>{text}</code>
        </pre>
      </CardContent>
    </Card>
  )
}
