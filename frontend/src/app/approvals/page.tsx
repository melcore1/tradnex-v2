'use client'

import { useCandidates } from '@/hooks/useCandidates'
import { ApprovalCard } from '@/components/candidate/ApprovalCard'
import { Card, CardContent } from '@/components/ui/card'

export default function ApprovalsPage() {
  const { data, isLoading, error } = useCandidates({ status: 'pending_human_approval', limit: 50 })

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Pending approvals</h1>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading candidates…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Failed to load.</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            Nothing awaiting approval.
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {data.map((c) => (
            <ApprovalCard key={c.id} summary={c} />
          ))}
        </div>
      )}
    </div>
  )
}
