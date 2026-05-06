'use client'

import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/shared/CopyButton'
import { ConfidenceBadge } from '@/components/shared/ConfidenceBadge'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { RuleTraceDisplay } from './RuleTraceDisplay'
import { VetoTraceDisplay } from './VetoTraceDisplay'
import { LlmEvaluationDisplay } from './LlmEvaluationDisplay'
import { ContractDisplay } from './ContractDisplay'
import { RawJsonToggle } from '@/components/shared/RawJsonToggle'
import { RejectDialog } from './RejectDialog'
import { useApprove, useCandidateDetail, useReject } from '@/hooks/useCandidates'
import type { CandidateSummary } from '@/lib/api/candidates'
import { fmtRelative } from '@/lib/format/datetime'

interface ApprovalCardProps {
  summary: CandidateSummary
}

export function ApprovalCard({ summary }: ApprovalCardProps) {
  const { data: detail, isLoading } = useCandidateDetail(summary.id)
  const approve = useApprove()
  const reject = useReject()

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2">
              <span>
                {summary.ticker} — {summary.direction}
              </span>
              <span className="text-xs text-muted-foreground font-normal">
                {summary.candidate_kind}
              </span>
              {summary.candidate_kind === 'entry' ? <ConfidenceBadge confidence={summary.confidence} /> : null}
              <StatusBadge status={summary.status} />
            </CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              fired {fmtRelative(summary.created_ts)} · #{summary.id}
            </p>
          </div>
          <CopyButton
            text={detail?.copyable_text ?? ''}
            label="Copy Full Context"
            variant="outline"
            size="sm"
          />
        </div>
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading detail…</p>
        ) : !detail ? (
          <p className="text-sm text-destructive">Failed to load.</p>
        ) : (
          <Tabs defaultValue={summary.candidate_kind === 'entry' ? 'reasoning' : 'rules'}>
            <TabsList className="flex flex-wrap gap-1">
              <TabsTrigger value="reasoning">Claude</TabsTrigger>
              <TabsTrigger value="rules">Rules</TabsTrigger>
              <TabsTrigger value="vetoes">Vetoes</TabsTrigger>
              <TabsTrigger value="contract">Contract</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
            <TabsContent value="reasoning" className="pt-3">
              <LlmEvaluationDisplay evaluation={detail.llm_evaluation} />
            </TabsContent>
            <TabsContent value="rules" className="pt-3">
              <RuleTraceDisplay trace={detail.rule_trace} />
            </TabsContent>
            <TabsContent value="vetoes" className="pt-3">
              <VetoTraceDisplay trace={detail.veto_trace} />
            </TabsContent>
            <TabsContent value="contract" className="pt-3">
              <ContractDisplay contract={detail.selected_contract} />
            </TabsContent>
            <TabsContent value="raw" className="pt-3">
              <RawJsonToggle formatted={null} raw={detail} />
            </TabsContent>
          </Tabs>
        )}
      </CardContent>

      <CardFooter className="gap-2">
        <Button
          variant="success"
          size="lg"
          onClick={() => approve.mutate({ id: summary.id, body: {} })}
          disabled={approve.isPending}
        >
          Approve
        </Button>
        <RejectDialog
          loading={reject.isPending}
          onConfirm={(payload) => reject.mutate({ id: summary.id, body: payload })}
        />
      </CardFooter>
    </Card>
  )
}
