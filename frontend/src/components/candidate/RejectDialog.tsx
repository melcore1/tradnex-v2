'use client'

import { useState } from 'react'
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
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'

interface RejectDialogProps {
  onConfirm: (payload: { reason: string; notes?: string }) => void
  loading?: boolean
}

export function RejectDialog({ onConfirm, loading }: RejectDialogProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="destructive" size="lg">
          Reject
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject candidate</DialogTitle>
          <DialogDescription>
            Add a reason for the journal. The candidate moves to <code>rejected_by_user</code>.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div>
            <Label htmlFor="reject-reason">Reason</Label>
            <Input
              id="reject-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. macro headwinds, IV too rich"
            />
          </div>
          <div>
            <Label htmlFor="reject-notes">Notes (optional)</Label>
            <Textarea
              id="reject-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!reason || loading}
            onClick={() => {
              onConfirm({ reason, notes: notes || undefined })
              setOpen(false)
            }}
          >
            Confirm reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
