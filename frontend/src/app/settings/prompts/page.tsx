'use client'

import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { CopyButton } from '@/components/shared/CopyButton'
import {
  useActivePrompt,
  useActivatePrompt,
  useCreatePrompt,
  usePromptHistory,
  useRollbackPrompt,
} from '@/hooks/usePrompts'
import { fmtRelative } from '@/lib/format/datetime'
import type { PromptTemplateName } from '@/lib/api/prompts'
import { toast } from '@/components/ui/sonner'

const TEMPLATES: PromptTemplateName[] = ['entry_evaluation', 'exit_evaluation']

export default function PromptsSettingsPage() {
  const [tpl, setTpl] = useState<PromptTemplateName>('entry_evaluation')
  return (
    <div className="flex flex-col gap-4">
      <Tabs value={tpl} onValueChange={(v) => setTpl(v as PromptTemplateName)}>
        <TabsList>
          {TEMPLATES.map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>
        {TEMPLATES.map((t) => (
          <TabsContent key={t} value={t}>
            <PromptTemplatePanel template={t} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

function PromptTemplatePanel({ template }: { template: PromptTemplateName }) {
  const { data: active } = useActivePrompt(template)
  const { data: history } = usePromptHistory(template)
  const create = useCreatePrompt()
  const activate = useActivatePrompt()
  const rollback = useRollbackPrompt()

  const [draft, setDraft] = useState<string>('')
  const [schemaDraft, setSchemaDraft] = useState<string>('{}')
  const [notes, setNotes] = useState<string>('')

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Active version</CardTitle>
            {active ? (
              <CardDescription>
                v{active.version_number} · activated {fmtRelative(active.activated_ts)}
              </CardDescription>
            ) : null}
          </div>
          {active ? <CopyButton text={active.template_text} label="Copy text" /> : null}
        </CardHeader>
        <CardContent>
          {active ? (
            <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
              {active.template_text}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No active version.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Create new version (status=pending)</CardTitle>
          <CardDescription>Activate from history once you&apos;re happy.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div>
            <Label htmlFor="prompt-text">Template text</Label>
            <Textarea
              id="prompt-text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-[200px] font-mono text-xs"
              placeholder="Render with {ticker}, {direction}, {rule_trace}, …"
            />
          </div>
          <div>
            <Label htmlFor="prompt-schema">JSON-Schema for response</Label>
            <Textarea
              id="prompt-schema"
              value={schemaDraft}
              onChange={(e) => setSchemaDraft(e.target.value)}
              className="min-h-[120px] font-mono text-xs"
            />
          </div>
          <div>
            <Label htmlFor="prompt-notes">Notes (optional)</Label>
            <Input id="prompt-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <Button
            onClick={() => {
              try {
                const parsed = JSON.parse(schemaDraft)
                create.mutate({
                  template_name: template,
                  template_text: draft,
                  response_schema: parsed,
                  notes: notes || undefined,
                })
              } catch {
                toast.error('Invalid schema JSON')
              }
            }}
            disabled={create.isPending || draft.length < 10}
          >
            {create.isPending ? 'Saving…' : 'Save draft'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent>
          {history?.length ? (
            <ul className="flex flex-col gap-2 text-sm">
              {history.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-2 border-b py-2">
                  <span className="font-mono text-xs">v{v.version_number}</span>
                  <Badge variant={v.status === 'active' ? 'success' : v.status === 'pending' ? 'pending' : 'neutral'}>
                    {v.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{fmtRelative(v.created_ts)}</span>
                  {v.notes ? <span className="text-xs italic text-muted-foreground">{v.notes}</span> : null}
                  <div className="ml-auto flex gap-2">
                    {v.status !== 'active' ? (
                      <Button size="sm" variant="outline" onClick={() => activate.mutate(v.id)} disabled={activate.isPending}>
                        Activate
                      </Button>
                    ) : null}
                    {v.status === 'deprecated' ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          rollback.mutate({ template, version_number: v.version_number })
                        }
                      >
                        Rollback to here
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No history.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
