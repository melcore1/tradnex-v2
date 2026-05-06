'use client'

import { useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useDeleteCredential, useUpsertCredential } from '@/hooks/useCredentials'
import type { CredentialRecord, CredentialType } from '@/lib/api/credentials'
import { fmtRelative } from '@/lib/format/datetime'

export interface CredentialField {
  /** Key the backend expects in `secrets` (e.g. 'api_key', 'api_secret'). */
  name: string
  label: string
  type: 'text' | 'password'
  placeholder?: string
}

interface CredentialEditorProps {
  type: CredentialType
  title: string
  description?: string
  warning?: string
  fields: readonly CredentialField[]
  record: CredentialRecord | undefined
  /** When true, the editor is read-only (e.g., Schwab while pending API approval). */
  disabled?: boolean
  disabledMessage?: string
}

export function CredentialEditor({
  type,
  title,
  description,
  warning,
  fields,
  record,
  disabled = false,
  disabledMessage,
}: CredentialEditorProps) {
  const upsert = useUpsertCredential()
  const remove = useDeleteCredential()
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, ''])),
  )
  const [notes, setNotes] = useState('')

  const isConfigured = record?.is_configured ?? false

  const handleSave = () => {
    // Skip empty fields — backend rejects empty secrets dict.
    const trimmed: Record<string, string> = {}
    for (const f of fields) {
      const v = values[f.name]?.trim()
      if (v) trimmed[f.name] = v
    }
    if (Object.keys(trimmed).length === 0) return
    upsert.mutate(
      { type, body: { secrets: trimmed, notes: notes || undefined } },
      {
        onSuccess: () => {
          setOpen(false)
          setValues(Object.fromEntries(fields.map((f) => [f.name, ''])))
          setNotes('')
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-row items-start justify-between gap-2">
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2">
              <span>{title}</span>
              {disabled ? (
                <Badge variant="neutral">Coming soon</Badge>
              ) : isConfigured ? (
                <Badge variant="success">Configured</Badge>
              ) : (
                <Badge variant="neutral">Not configured</Badge>
              )}
            </CardTitle>
            {description ? <CardDescription>{description}</CardDescription> : null}
            {warning ? (
              <CardDescription className="text-warning mt-1">
                {warning}
              </CardDescription>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        {disabled ? (
          <p className="text-sm text-muted-foreground">
            {disabledMessage ?? 'Available in a future phase.'}
          </p>
        ) : (
          <>
            {isConfigured && record ? (
              <span className="text-xs text-muted-foreground">
                Updated {fmtRelative(record.updated_ts)}
                {record.last_used_ts ? ` · last used ${fmtRelative(record.last_used_ts)}` : ''}
              </span>
            ) : null}

            <div className="ml-auto flex items-center gap-2">
              <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Pencil className="h-4 w-4" aria-hidden />
                    {isConfigured ? 'Update' : 'Add'}
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>
                      Values are encrypted at rest. Existing values are never
                      shown — leave blank to keep what&apos;s configured.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex flex-col gap-3">
                    {fields.map((f) => (
                      <div key={f.name} className="flex flex-col gap-1.5">
                        <Label htmlFor={`${type}-${f.name}`}>{f.label}</Label>
                        <Input
                          id={`${type}-${f.name}`}
                          type={f.type}
                          autoComplete="off"
                          spellCheck={false}
                          value={values[f.name] ?? ''}
                          onChange={(e) =>
                            setValues((prev) => ({ ...prev, [f.name]: e.target.value }))
                          }
                          placeholder={f.placeholder ?? '(write-only)'}
                        />
                      </div>
                    ))}
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`${type}-notes`}>Notes (optional)</Label>
                      <Input
                        id={`${type}-notes`}
                        type="text"
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button variant="ghost" onClick={() => setOpen(false)}>
                      Cancel
                    </Button>
                    <Button
                      onClick={handleSave}
                      disabled={upsert.isPending}
                    >
                      {upsert.isPending ? 'Saving…' : 'Save'}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              {isConfigured ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => remove.mutate(type)}
                  disabled={remove.isPending}
                  aria-label={`Remove ${title}`}
                >
                  <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
                </Button>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
