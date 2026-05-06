/**
 * Maps candidate / position status strings to UI labels and badge tones.
 *
 * Status values are validated by the migrations CHECK constraint:
 *   pending, processing_vetoes, rules_passed, vetoed, evaluated,
 *   pending_llm_evaluation, processing_llm_evaluation,
 *   pending_human_approval, rejected_by_llm, held,
 *   rejected, rejected_by_user, approved, placed, failed
 */

export type StatusTone =
  | 'neutral'
  | 'info'
  | 'warning'
  | 'success'
  | 'destructive'
  | 'pending'

export interface StatusDisplay {
  label: string
  tone: StatusTone
}

const STATUS_MAP: Record<string, StatusDisplay> = {
  pending: { label: 'Pending', tone: 'pending' },
  processing_vetoes: { label: 'Processing vetoes', tone: 'info' },
  rules_passed: { label: 'Rules passed', tone: 'info' },
  vetoed: { label: 'Vetoed', tone: 'warning' },
  evaluated: { label: 'Evaluated', tone: 'info' },
  pending_llm_evaluation: { label: 'Awaiting LLM', tone: 'pending' },
  processing_llm_evaluation: { label: 'LLM evaluating', tone: 'info' },
  pending_human_approval: { label: 'Awaiting approval', tone: 'pending' },
  rejected_by_llm: { label: 'Rejected by LLM', tone: 'destructive' },
  held: { label: 'Held', tone: 'warning' },
  rejected: { label: 'Rejected', tone: 'destructive' },
  rejected_by_user: { label: 'Rejected by user', tone: 'destructive' },
  approved: { label: 'Approved', tone: 'success' },
  placed: { label: 'Placed', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
  open: { label: 'Open', tone: 'success' },
  closed: { label: 'Closed', tone: 'neutral' },
}

export function describeStatus(status: string): StatusDisplay {
  return STATUS_MAP[status] ?? { label: status, tone: 'neutral' }
}

export function describeConfidence(c: string | null | undefined): {
  label: string
  tone: StatusTone
} {
  switch (c) {
    case 'STRONG':
      return { label: 'STRONG', tone: 'success' }
    case 'MODERATE':
      return { label: 'MODERATE', tone: 'info' }
    case 'WEAK':
      return { label: 'WEAK', tone: 'warning' }
    case 'VETO':
      return { label: 'VETO', tone: 'destructive' }
    default:
      return { label: '—', tone: 'neutral' }
  }
}
